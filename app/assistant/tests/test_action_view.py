"""Tests for the action card in the panel: the field card (value, empty, pick, who) and the leave form card (the form
link and its pick rows), rendered through the ask view with a fake provider. Nothing is opened by a pick; every value
is escaped."""

import itertools
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from urllib.parse import unquote

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import _no_offboarding_templates, hire_values  # noqa: F401 (autouse)

from assistant import views
from assistant.entries import HelpEntry
from assistant.plan import Plan
from assistant.providers import Choice
from assistant.words import FilterWords

URL = reverse("assistant:ask")
DAY = date(2026, 11, 5)
_ACTOR = "action_card_actor"
_REGISTER = itertools.count(1)
PHONE = "88112233"


class ActionProvider:
    """A fake provider whose plan() is the Plan it was given."""

    name = "fake"
    model = "fake-model"

    def __init__(self, plan: Plan) -> None:
        self.table = plan

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        raise AssertionError("the plan path is used, not choose()")

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
        return self.table


def _plan(**changes: object) -> Plan:
    base: dict[str, object] = {
        "tool": "field",
        "entry": "",
        "also": "",
        "lead": "",
        "parts": (),
        "unmapped": (),
        "want": "list",
        "chart_kind": "",
        "chart_by": "",
    }
    base.update(changes)
    return Plan(**base)  # type: ignore[arg-type]


def _person(given: str = "Номин", family: str = "Туяа", phone: str = PHONE) -> Employee:
    actor = User.objects.get_or_create(username=_ACTOR, defaults={"is_superuser": True, "is_staff": True})[0]
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {**hire_values(f"УБ{next(_REGISTER):08d}"), "given_name": given, "family_name": family}
    person = history.hire(values, {}, start=date(2026, 1, 5), job=job, salary=None, by=actor)
    if phone:
        macs_writes.update_employee_columns(person, {"private_phone": phone})
    return person


def _ask(client: Client, monkeypatch: pytest.MonkeyPatch, plan: Plan, question: str) -> str:
    monkeypatch.setattr(views, "get_provider", lambda: ActionProvider(plan))
    return client.post(URL, {"q": question}).content.decode()


@pytest.mark.django_db
def test_field_card_shows_name_job_value_and_link(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    person = _person()
    client.force_login(role_user("hr"))
    body = _ask(client, monkeypatch, _plan(tool="field", field="private_phone"), "Номины утас")
    assert "Туяа Номин" in body
    assert "Нягтлан · Санхүү" in body
    assert PHONE in body
    assert f'href="{reverse("employees:detail", args=[person.pk])}#personal-private_phone"' in body
    assert "Нээх →" in body
    assert "data-palette-modal" not in body  # the field link is an ordinary link, not a pop-up


@pytest.mark.django_db
def test_field_value_is_escaped(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _person(phone="<script>1")  # the phone column holds 14 characters
    client.force_login(role_user("hr"))
    body = _ask(client, monkeypatch, _plan(tool="field", field="private_phone"), "Номины утас")
    assert "<script>1" not in body
    assert "&lt;script&gt;1" in body


@pytest.mark.django_db
def test_empty_value_says_not_recorded(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _person(phone="")
    client.force_login(role_user("hr"))
    body = _ask(client, monkeypatch, _plan(tool="field", field="private_phone"), "Номины утас")
    assert "бүртгэгдээгүй байна" in body
    assert "Нээх →" in body


@pytest.mark.django_db
def test_field_pick_lists_rows_and_opens_nothing(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _person("Номин", "Туяа")
    second = _person("Номин", "Оюун")
    client.force_login(role_user("hr"))
    body = _ask(client, monkeypatch, _plan(tool="field", field="private_phone"), "Номины утас")
    assert "Аль ажилтан бэ?" in body
    assert f'href="{reverse("employees:detail", args=[first.pk])}#personal-private_phone"' in body
    assert f'href="{reverse("employees:detail", args=[second.pk])}#personal-private_phone"' in body
    assert "Туяа Номин" in body and "Оюун Номин" in body
    assert "Нээх →" not in body
    assert PHONE not in body


@pytest.mark.django_db
def test_who_card_asks_whose_field(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _person()
    client.force_login(role_user("hr"))
    body = _ask(client, monkeypatch, _plan(tool="field", field="private_phone"), "Утас")
    assert "Хэний мэдээллийг?" in body
    assert "Нээх →" not in body


@pytest.mark.django_db
def test_leave_card_links_the_form_as_a_pop_up(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    person = _person()
    client.force_login(role_user("hr"))
    plan = _plan(tool="leave_form", start="2026-11-10", end="2026-11-12")
    body = _ask(client, monkeypatch, plan, "Номинд чөлөө авмаар")
    assert "Туяа Номин" in body
    assert "Ажилтан: Туяа Номин" in body
    assert "Эхлэх: 2026-11-10" in body
    assert f"employee={person.pk}" in body
    assert "from=assistant" in body
    assert "data-palette-modal" in body
    assert "Нээх →" in body


@pytest.mark.django_db
def test_leave_pick_rows_open_nothing(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _person("Номин", "Туяа")
    second = _person("Номин", "Оюун")
    client.force_login(role_user("hr"))
    body = _ask(client, monkeypatch, _plan(tool="leave_form", start="2026-11-10"), "Номинд чөлөө авмаар")
    assert "Аль ажилтан бэ?" in body
    assert f"employee={first.pk}" in body
    assert f"employee={second.pk}" in body
    assert "Нээх →" not in body
    assert "Ажилтан: " not in body


@pytest.mark.django_db
def test_leave_pick_rows_keep_the_sentence_dates(
    client: Client, role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _person("Номин", "Туяа")
    second = _person("Номин", "Оюун")
    client.force_login(role_user("hr"))
    plan = _plan(tool="leave_form", start="2026-11-03", end="2026-11-07")
    body = _ask(client, monkeypatch, plan, "Номинд 11 сарын 3-аас 7 хүртэл чөлөө авмаар")
    for person in (first, second):
        assert f"employee={person.pk}" in body
    assert "start=2026-11-03" in body
    assert "end=2026-11-07" in body
    assert "from=assistant" in body
    hrefs = [unquote(href) for href in re.findall(r'href="([^"]*)"', body)]
    assert hrefs  # the pick rows are links
    assert not any("чөлөө" in href for href in hrefs)  # the question's own words never reach an address
    assert "Нээх →" not in body
