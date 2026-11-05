"""Tests for the ask view: login, method, blank and off cases, the answer card, and escaping."""

import itertools
from collections.abc import Callable, Mapping, Sequence
from datetime import date

import pytest
from accounts.models import AccessScope, User
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import _no_offboarding_templates, hire_values  # noqa: F401 (autouse)
from macs.models import Branch

from assistant import entries, views
from assistant.entries import HelpEntry
from assistant.models import HelpQuestion, Outcome
from assistant.plan import Plan
from assistant.providers import Choice, ProviderError
from assistant.services import ASK_PER_HOUR
from assistant.tests.helpers import fake_plan
from assistant.words import FilterWords

URL = reverse("assistant:ask")


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, choice: Choice) -> None:
        self.choice = choice

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        return self.choice

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
    ) -> Plan:
        return fake_plan(self, question, entries, refusals)


def test_anonymous_redirects_to_login(client: Client) -> None:
    response = client.post(URL, {"q": "яаж"})
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_get_is_405(client: Client, role_user: Callable[[str], User]) -> None:
    client.force_login(role_user("hr"))
    assert client.get(URL).status_code == 405


@pytest.mark.django_db
def test_blank_question_400(client: Client, role_user: Callable[[str], User]) -> None:
    client.force_login(role_user("hr"))
    assert client.post(URL, {"q": "  "}).status_code == 400


@pytest.mark.django_db
def test_ask_404_when_off(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "get_provider", lambda: None)
    client.force_login(role_user("hr"))
    assert client.post(URL, {"q": "яаж"}).status_code == 404


@pytest.mark.django_db
def test_answer_card(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө бүртгэх хэсэг."))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    response = client.post(URL, {"q": "ажилтанд чөлөө яаж оруулах вэ"})
    assert response.status_code == 200
    body = response.content.decode()
    assert "Чөлөө бүртгэх" in body
    assert "Нээх →" in body
    assert 'href="/leave/new/"' in body
    assert "data-palette-modal" in body
    assert 'role="status"' in body


@pytest.mark.django_db
def test_none_card(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(Choice(entry="", also="", lead=""))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    response = client.post(URL, {"q": "пицца захиалах вэ"})
    body = response.content.decode()
    assert "Энэ асуултад хариулт олдсонгүй" in body
    assert "data-palette-item" not in body


@pytest.mark.django_db
def test_lead_and_question_are_escaped(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="<script>x</script>"))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "<script>x</script> чөлөө яаж вэ"}).content.decode()
    assert "&lt;script&gt;" in body
    assert "<script>x" not in body


class ErrorProvider:
    name = "fake"
    model = "fake-model"

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        raise ProviderError("boom")

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
    ) -> Plan:
        return fake_plan(self, question, entries, refusals)


@pytest.mark.django_db
def test_csrf_required(role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "get_provider", lambda: FakeProvider(Choice(entry="", also="", lead="")))
    client = Client(enforce_csrf_checks=True)
    client.force_login(role_user("hr"))
    assert client.post(URL, {"q": "яаж"}).status_code == 403


@pytest.mark.django_db
def test_error_card(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "get_provider", lambda: ErrorProvider())
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "яаж чөлөө бүртгэх вэ"}).content.decode()
    assert "Хариулт авч чадсангүй. Дахин оролдоно уу." in body


@pytest.mark.django_db
def test_limited_card(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө."))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    user = role_user("hr")
    for _ in range(ASK_PER_HOUR):
        HelpQuestion.objects.create(user=user, question="чөлөө", outcome=Outcome.ANSWERED)
    client.force_login(user)
    body = client.post(URL, {"q": "чөлөө яаж авах вэ"}).content.decode()
    assert "Нэг цагт 20-оос олон асуулт асуух боломжгүй" in body


_VIEW_ACTOR = "answer_view_actor"
_VIEW_REGISTER = itertools.count(1)


def _hire_named(given: str, family: str, branch_id: int | None = None) -> Employee:
    actor = User.objects.get_or_create(username=_VIEW_ACTOR, defaults={"is_superuser": True, "is_staff": True})[0]
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {**hire_values(f"УБ{next(_VIEW_REGISTER):08d}"), "given_name": given, "family_name": family}
    person = history.hire(values, {}, start=date(2026, 1, 5), job=job, salary=None, by=actor)
    if branch_id is not None:
        Employee.objects.filter(pk=person.pk).update(branch_id=branch_id)
    return person


@pytest.fixture
def person_entry(monkeypatch: pytest.MonkeyPatch) -> HelpEntry:
    """A person-bound entry for everyone, until the area entries exist."""
    entry = HelpEntry(
        key="test.person",
        title="Ажилтны хуудас",
        steps=("Ажилтныг нээнэ.",),
        url_name="employees:list",
        modal=False,
        need=lambda user, day: True,
        labels=(),
        person_tab="",
    )
    monkeypatch.setattr(entries, "ENTRIES", (entry,))
    monkeypatch.setattr(entries, "ENTRY_BY_KEY", {entry.key: entry})
    return entry


@pytest.mark.django_db
def test_card_one_person_opens_page(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch, person_entry: HelpEntry
) -> None:
    person = _hire_named("Номин", "Туяа")
    provider = FakeProvider(Choice(entry=person_entry.key, also="", lead="Ажилтан."))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "Номин яаж харах вэ"}).content.decode()
    assert f'href="{reverse("employees:detail", args=[person.pk])}"' in body
    assert "Нээх: Туяа Номин →" in body
    assert "Нягтлан" in body
    assert "Аль ажилтан бэ?" not in body


@pytest.mark.django_db
def test_card_several_people_list(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch, person_entry: HelpEntry
) -> None:
    first = _hire_named("Номин", "Туяа")
    second = _hire_named("Номин", "Гантулга")
    provider = FakeProvider(Choice(entry=person_entry.key, also="", lead="Ажилтан."))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "Номин яаж харах вэ"}).content.decode()
    assert "Аль ажилтан бэ?" in body
    assert "Нээх: " not in body
    for pk in (first.pk, second.pk):
        assert f'href="{reverse("employees:detail", args=[pk])}" data-palette-item' in body
    assert "Туяа" in body and "Гантулга" in body
    assert "бусад" not in body


@pytest.mark.django_db
def test_card_hides_out_of_scope(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch, person_entry: HelpEntry
) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    _hire_named("Номин", "Гантулга", branch_id=north.pk)
    inside = _hire_named("Номин", "Туяа", branch_id=south.pk)
    provider = FakeProvider(Choice(entry=person_entry.key, also="", lead="Ажилтан."))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    hr = role_user("hr")
    AccessScope.objects.update_or_create(user=hr, defaults={"limited": True, "branch_ids": [south.pk]})
    client.force_login(User.objects.get(pk=hr.pk))
    body = client.post(URL, {"q": "Номин яаж харах вэ"}).content.decode()
    assert f'href="{reverse("employees:detail", args=[inside.pk])}"' in body
    assert "Гантулга" not in body
    assert "Аль ажилтан бэ?" not in body


@pytest.mark.django_db
def test_card_no_person_plain_link(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch, person_entry: HelpEntry
) -> None:
    _hire_named("Номин", "Туяа")
    provider = FakeProvider(Choice(entry=person_entry.key, also="", lead="Ажилтан."))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "Болд яаж харах вэ"}).content.decode()
    assert "Нээх →" in body
    assert f'href="{reverse("employees:list")}"' in body
    assert "Нээх: " not in body
    assert "Аль ажилтан бэ?" not in body
    assert "Туяа" not in body


@pytest.mark.django_db
def test_card_no_person_hint(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch, person_entry: HelpEntry
) -> None:
    _hire_named("Номин", "Туяа")
    provider = FakeProvider(Choice(entry=person_entry.key, also="", lead="Ажилтан."))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "Болд яаж харах вэ"}).content.decode()
    hint = "Ажилтныг жагсаалтаас олж нээнэ үү."
    assert hint in body
    assert body.index(hint) < body.index("Нээх →")


@pytest.mark.django_db
def test_none_text(client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(Choice(entry="", also="", lead=""))
    monkeypatch.setattr(views, "get_provider", lambda: provider)
    client.force_login(role_user("hr"))
    body = client.post(URL, {"q": "пицца захиалах вэ"}).content.decode()
    assert "Энэ асуултад хариулт олдсонгүй. Асуултаа өөрөөр бичээд үзнэ үү." in body
