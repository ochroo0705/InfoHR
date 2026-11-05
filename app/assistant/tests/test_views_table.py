"""Tests for the table answer in the panel: the ask view's card, the ask (buttons) and list (count, chips, link) states,
the pick view that settles a chosen row without the model, and the escaping of a department name."""

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from django.utils.html import escape
from macs.models import Department

from assistant import views
from assistant.entries import HelpEntry
from assistant.models import HelpQuestion
from assistant.plan import Part, Plan
from assistant.providers import Choice
from assistant.tests.helpers import hire_one
from assistant.words import FilterWords

URL = reverse("assistant:ask")
PICK_URL = reverse("assistant:pick")
STAFF_PATH = reverse("reports:report", args=["staff-list"])


class TableProvider:
    """A fake provider whose plan() is a canned Plan; it records the `previous` query each call received."""

    name = "fake"
    model = "fake-model"

    def __init__(self, plan: Plan) -> None:
        self.table = plan
        self.previous: list[str] = []

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        raise AssertionError("the table path must not call choose")

    def plan(
        self,
        question: str,
        entries: Sequence[HelpEntry],
        words: Sequence[FilterWords],
        phrases: Mapping[str, list[str]],
        today: date,
        previous: str = "",
        refusals: Sequence[str] = (),
        table_examples: Sequence[tuple[str, str]] = (),
        field_hints: Sequence[object] = (),
    ) -> Plan:
        self.previous.append(previous)
        return self.table


def _plan(parts: Sequence[Part] = (), want: str = "list") -> Plan:
    return Plan(
        tool="staff_table",
        entry="",
        also="",
        lead="",
        parts=tuple(parts),
        unmapped=(),
        want=want,
        chart_kind="",
        chart_by="",
    )


def _no_provider() -> None:
    raise AssertionError("the pick view must not ask the model")


def _pick_data(**overrides: str) -> dict[str, str]:
    data = {
        "query": "",
        "param": "department",
        "id": "1",
        "rest": "[]",
        "want": "list",
        "chart_kind": "",
        "chart_by": "",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_table_answer_renders_count_chips_and_link(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = role_user("hr")
    hire_one(actor)
    dept = Department.objects.get(name="Санхүү")
    monkeypatch.setattr(views, "get_provider", lambda: TableProvider(_plan([Part("department", "санхүү")])))
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "санхүүд хэн байна вэ"}).content.decode()
    query = f"department={dept.pk}"
    assert "Ажилтны хүснэгт шүүлтүүртэй нээхэд бэлэн: 1 хүн." in body
    chips = re.findall(r'<li class="[^"]*rounded-full[^"]*">([^<]*)</li>', body)
    assert any("Санхүү" in chip for chip in chips)  # a chip's own markup names the department
    assert f'href="{escape(f"{STAFF_PATH}?{query}")}" data-palette-item' in body
    assert f'data-assistant-context="{escape(query)}"' in body


@pytest.mark.django_db
def test_count_want_says_how_many(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = role_user("hr")
    hire_one(actor)
    monkeypatch.setattr(views, "get_provider", lambda: TableProvider(_plan([Part("department", "санхүү")], "count")))
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "санхүүд хэдэн хүн байна"}).content.decode()
    assert "1 хүн байна." in body


@pytest.mark.django_db
def test_zero_people_text(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    Department.objects.create(name="Маркетинг")
    monkeypatch.setattr(views, "get_provider", lambda: TableProvider(_plan([Part("department", "маркетинг")])))
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "маркетингийн хүмүүс"}).content.decode()
    assert "Хэн ч олдсонгүй. Шүүлтүүрээ багасгаад үзнэ үү." in body
    assert "data-assistant-context" in body  # a list with nobody is still a list


@pytest.mark.django_db
def test_ask_renders_buttons_with_follow_attributes(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("Санхүүгийн хяналт", "Санхүүгийн төлөвлөлт", "Санхүүгийн тайлан"):
        Department.objects.create(name=name)
    monkeypatch.setattr(views, "get_provider", lambda: TableProvider(_plan([Part("department", "санхүү")])))
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "санхүүгийн хүмүүс"}).content.decode()
    assert body.count(f'data-follow-url="{PICK_URL}"') == 3
    assert "Аль Хэлтэс вэ?" in body
    assert "Сонгосны дараа хүснэгт нээгдэнэ." in body
    assert "Хүснэгт нээх" not in body  # a partial answer has no link to the table
    assert "data-assistant-context" not in body
    pk = Department.objects.get(name="Санхүүгийн хяналт").pk
    follow = urlencode(
        {"query": "", "param": "department", "id": pk, "rest": "[]", "want": "list", "chart_kind": "", "chart_by": ""}
    )
    assert 'data-follow-label="Санхүүгийн хяналт"' in body
    assert f'data-follow-body="{escape(follow)}"' in body


@pytest.mark.django_db
def test_not_applied_block(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    actor = role_user("hr")
    hire_one(actor)
    monkeypatch.setattr(views, "get_provider", lambda: TableProvider(_plan([Part("department", "Нөхцөлгүй")])))
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "нөхцөлгүй хүмүүс"}).content.decode()
    assert 'role="note"' in body
    assert "Хэрэглэж чадаагүй:" in body
    assert "“Нөхцөлгүй” гэсэн утга олдсонгүй." in body


@pytest.mark.django_db
def test_not_applied_shown_in_ask_state(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("Санхүүгийн хяналт", "Санхүүгийн төлөвлөлт"):
        Department.objects.create(name=name)
    parts = [Part("department", "Нөхцөлгүй"), Part("department", "санхүү")]
    monkeypatch.setattr(views, "get_provider", lambda: TableProvider(_plan(parts)))
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "нөхцөлгүй санхүү"}).content.decode()
    assert "Аль Хэлтэс вэ?" in body
    assert "“Нөхцөлгүй” гэсэн утга олдсонгүй." in body


@pytest.mark.django_db
def test_pick_settles_and_renders_list(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = role_user("hr")
    hire_one(actor)
    dept = Department.objects.get(name="Санхүү")
    monkeypatch.setattr(views, "get_provider", _no_provider)
    user = role_user("hr")
    client.force_login(user)
    logs = HelpQuestion.objects.count()
    response = client.post(PICK_URL, _pick_data(id=str(dept.pk), want="count"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "1 хүн байна." in body
    assert HelpQuestion.objects.count() == logs  # a pick is not a question: no log row


@pytest.mark.django_db
def test_pick_rejects_bad_input(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    dept = Department.objects.create(name="Санхүү")
    monkeypatch.setattr(views, "get_provider", _no_provider)
    client.force_login(role_user("hr"))
    too_many = json.dumps([["emptype", "5"]] * 13)
    bad = [
        _pick_data(param="salary_from", id=str(dept.pk)),
        _pick_data(param=""),
        _pick_data(id="999999"),
        _pick_data(id="abc"),
        _pick_data(id="1.5"),
        _pick_data(id=""),
        _pick_data(id=str(dept.pk), rest="не json"),
        _pick_data(id=str(dept.pk), rest=too_many),
        _pick_data(id=str(dept.pk), rest="[" * 5000),
        _pick_data(id=str(dept.pk), rest="[" * 5000 + "]" * 5000),
        _pick_data(id=str(dept.pk), rest="{}"),
        _pick_data(id=str(dept.pk), rest="null"),
        _pick_data(id=str(dept.pk), rest='[["a"]]'),
        _pick_data(id=str(dept.pk), rest="[[1, 2]]"),
    ]
    for data in bad:
        assert client.post(PICK_URL, data).status_code == 400, data


@pytest.mark.django_db
def test_pick_missing_fields_are_400(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    dept = Department.objects.create(name="Санхүү")
    monkeypatch.setattr(views, "get_provider", _no_provider)
    client.force_login(role_user("hr"))
    no_param = {"id": str(dept.pk)}
    no_id = {"param": "department"}
    assert client.post(PICK_URL, no_param).status_code == 400
    assert client.post(PICK_URL, no_id).status_code == 400


@pytest.mark.django_db
def test_pick_get_is_405_and_anonymous_is_login(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(views, "get_provider", _no_provider)
    assert client.post(PICK_URL, _pick_data()).status_code == 302  # anonymous: login redirect
    client.force_login(role_user("hr"))
    assert client.get(PICK_URL).status_code == 405


@pytest.mark.django_db
def test_pick_denied_user_gets_the_same_card_for_any_id(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    dept = Department.objects.create(name="Санхүү")
    monkeypatch.setattr(views, "get_provider", _no_provider)
    client.force_login(role_user("staff"))  # no report right: may not open the table
    real = client.post(PICK_URL, _pick_data(id=str(dept.pk)))
    missing = client.post(PICK_URL, _pick_data(id="999999"))
    assert real.status_code == 200
    assert missing.status_code == 200  # a missing id does not show up as a 400 for this user
    assert "Ажилтны хүснэгтийг харах эрх алга." in missing.content.decode()
    assert real.content == missing.content


@pytest.mark.django_db
def test_zero_people_with_count_keeps_the_zero_text(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    Department.objects.create(name="Маркетинг")
    monkeypatch.setattr(views, "get_provider", lambda: TableProvider(_plan([Part("department", "маркетинг")], "count")))
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "маркетингийн хэдэн хүн байна"}).content.decode()
    assert "Хэн ч олдсонгүй. Шүүлтүүрээ багасгаад үзнэ үү." in body
    assert "хүн байна." not in body


@pytest.mark.django_db
def test_pick_applies_the_gate(client: Client, role_user: Callable[[str], User]) -> None:
    actor = role_user("hr")
    hire_one(actor)
    dept = Department.objects.get(name="Санхүү")
    client.force_login(role_user("hr"))  # HR may open the table but has no salary right
    response = client.post(PICK_URL, _pick_data(query="salary_from=1", id=str(dept.pk)))
    assert response.status_code == 200
    body = response.content.decode()
    assert f'href="{escape(f"{STAFF_PATH}?department={dept.pk}")}"' in body  # no salary part in the table address
    assert "salary" not in body


@pytest.mark.django_db
def test_ask_passes_prev(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    actor = role_user("hr")
    hire_one(actor)
    provider = TableProvider(_plan())
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    client.post(URL, {"q": "тэгээд хэн байна", "prev": "emptype=5"})
    assert provider.previous == ["emptype=5"]


@pytest.mark.django_db
def test_prev_too_long_is_ignored(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = TableProvider(_plan())
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    client.post(URL, {"q": "тэгээд хэн байна", "prev": "emptype=5&" + "x=1&" * 600})
    assert provider.previous == [""]


@pytest.mark.django_db
def test_fragment_is_escaped(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    actor = role_user("hr")
    hire_one(actor)
    Department.objects.create(name="<b>x</b>")
    monkeypatch.setattr(views, "get_provider", lambda: TableProvider(_plan([Part("department", "<b>x</b>")])))
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "хэлтэс"}).content.decode()
    assert "&lt;b&gt;x&lt;/b&gt;" in body
    assert "<b>x</b>" not in body
