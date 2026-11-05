"""Tests for the answer service's action path: a field plan or a leave_form plan gives an ACTION outcome (or NONE when
the builder finds nothing), the log row keeps the tool and the field key but never the value, and the hints reach the
provider."""

import itertools
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

import pytest
from accounts.models import AccessScope, User
from django.urls import reverse
from django.utils import timezone
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import _no_offboarding_templates, hire_values  # noqa: F401 (autouse)
from macs.models import Branch

from assistant import services
from assistant.entries import HelpEntry
from assistant.fields import hints_for
from assistant.models import HelpQuestion, Outcome
from assistant.plan import Plan
from assistant.services import ASK_PER_HOUR, answer
from assistant.tests.helpers import left
from assistant.words import FilterWords

DAY = date(2026, 11, 5)
_ACTOR = "action_plan_actor"
_REGISTER = itertools.count(1)
PHONE = "88112233"


class FieldProvider:
    """A fake provider whose plan() is the Plan it was given. It records the field hints it was offered."""

    name = "fake"
    model = "fake-model"

    def __init__(self, plan: Plan) -> None:
        self.table = plan
        self.field_hints: list[str] = []
        self.calls = 0

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Any:
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
        field_hints: Sequence[Any] = (),
    ) -> Plan:
        self.calls += 1
        self.field_hints = [hint.key for hint in field_hints]
        return self.table


def _plan(**changes: Any) -> Plan:
    base: dict[str, Any] = {
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
    return Plan(**base)


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


def _log_fields(row: HelpQuestion) -> list[str]:
    """Every text column of a log row except the question itself (the question is logged as asked, as before)."""
    return [row.entry, row.also, row.allowed, row.provider, row.model, row.error, row.tool, row.query, row.not_applied]


@pytest.mark.django_db
def test_field_plan_with_one_visible_person_is_an_action(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    person = _person()
    provider = FieldProvider(_plan(field="private_phone"))
    result = answer(user, "Номины утас", DAY, provider)
    assert result.outcome == Outcome.ACTION
    assert result.tool == "field"
    assert result.field is not None
    assert result.field.status == "value"
    assert result.field.text == PHONE
    assert result.field.url == reverse("employees:detail", args=[person.pk]) + "#personal-private_phone"
    assert result.leave is None


@pytest.mark.django_db
def test_field_plan_outside_scope_is_the_same_none_as_unknown(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    person = _person()
    Employee.objects.filter(pk=person.pk).update(branch_id=north.pk)
    AccessScope.objects.update_or_create(user=user, defaults={"limited": True, "branch_ids": [south.pk]})
    limited = User.objects.get(pk=user.pk)
    outside = answer(limited, "Номины утас", DAY, FieldProvider(_plan(field="private_phone")))
    unknown = answer(limited, "Батын утас", DAY, FieldProvider(_plan(field="private_phone")))
    assert outside.outcome == unknown.outcome == Outcome.NONE
    assert outside.field is None and unknown.field is None
    assert outside.tool == unknown.tool == "field"
    assert outside.query == unknown.query
    rows = list(HelpQuestion.objects.filter(user=user).order_by("pk"))
    assert len(rows) == 2
    for column in ("outcome", "tool", "query", "entry", "also", "error"):
        assert getattr(rows[0], column) == getattr(rows[1], column)


@pytest.mark.django_db
def test_field_plan_with_a_leaver_and_a_current_employee_is_a_pick(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    leaver = _person("Номин", "Туяа")
    left(User.objects.get(username=_ACTOR), leaver)
    _person("Номин", "Оюун")
    result = answer(user, "Номины утас", DAY, FieldProvider(_plan(field="private_phone")))
    assert result.outcome == Outcome.ACTION
    assert result.field is not None
    assert result.field.status == "pick"
    assert result.field.url == ""
    assert len(result.field.people) == 2


@pytest.mark.django_db
def test_field_plan_with_two_current_people_is_a_pick(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    _person("Номин", "Туяа")
    _person("Номин", "Оюун")
    result = answer(user, "Номины утас", DAY, FieldProvider(_plan(field="private_phone")))
    assert result.outcome == Outcome.ACTION
    assert result.field is not None
    assert result.field.status == "pick"
    assert result.field.url == ""
    assert len(result.field.people) == 2


@pytest.mark.django_db
def test_field_builder_error_is_one_logged_error_row(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    _person()

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError(f"{PHONE} Номин Туяа")

    monkeypatch.setattr(services, "field_answer", broken)
    result = answer(user, "Номины утас", DAY, FieldProvider(_plan(field="private_phone")))
    assert result.outcome == Outcome.ERROR
    assert result.field is None
    rows = HelpQuestion.objects.filter(user=user)
    assert rows.count() == 1
    row = rows.get()
    assert row.outcome == "error"
    assert row.error == "RuntimeError (unexpected)"
    for column in _log_fields(row):
        assert PHONE not in column
        assert "Номин" not in column
        assert "Туяа" not in column


@pytest.mark.django_db
def test_leave_form_builder_error_is_one_logged_error_row(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    _person()

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Номин Туяа 2026-11-10")

    monkeypatch.setattr(services, "leave_form_answer", broken)
    plan = _plan(tool="leave_form", start="2026-11-10", end="2026-11-12")
    result = answer(user, "Номинд чөлөө авмаар", DAY, FieldProvider(plan))
    assert result.outcome == Outcome.ERROR
    assert result.leave is None
    rows = HelpQuestion.objects.filter(user=user)
    assert rows.count() == 1
    row = rows.get()
    assert row.outcome == "error"
    for column in _log_fields(row):
        assert "Номин" not in column
        assert "Туяа" not in column
        assert "2026-11-10" not in column


@pytest.mark.django_db
def test_field_plan_with_unknown_key_is_none(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    _person()
    result = answer(user, "Номины утас", DAY, FieldProvider(_plan(field="no_such_field")))
    assert result.outcome == Outcome.NONE
    assert result.field is None
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == "none"
    assert row.query == ""


@pytest.mark.django_db
def test_leave_form_plan_without_right_is_none(role_user: Callable[[str], User]) -> None:
    user = role_user("accountant")
    _person()
    plan = _plan(tool="leave_form", leave_type="Ээлжийн амралт", start="2026-11-10", end="2026-11-12")
    result = answer(user, "Номинд чөлөө", DAY, FieldProvider(plan))
    assert result.outcome == Outcome.NONE
    assert result.leave is None
    assert result.tool == "leave_form"


@pytest.mark.django_db
def test_leave_form_plan_with_right_is_an_action(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    person = _person()
    plan = _plan(tool="leave_form", leave_type="", start="2026-11-10", end="2026-11-12")
    result = answer(user, "Номинд чөлөө авмаар", DAY, FieldProvider(plan))
    assert result.outcome == Outcome.ACTION
    assert result.leave is not None
    assert result.leave.status == "form"
    assert result.leave.people[0].employee.pk == person.pk
    assert result.field is None


@pytest.mark.django_db
def test_action_row_keeps_tool_and_field_key_and_no_value(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    _person()
    answer(user, "Номины утас", DAY, FieldProvider(_plan(field="private_phone")))
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == "action"
    assert row.tool == "field"
    assert row.query == "private_phone"
    for column in _log_fields(row):
        assert PHONE not in column
        assert "Номин" not in column
        assert "Туяа" not in column


@pytest.mark.django_db
def test_leave_form_row_logs_the_action_name_only(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    _person()
    plan = _plan(tool="leave_form", start="2026-11-10", end="2026-11-12")
    answer(user, "Номинд чөлөө авмаар", DAY, FieldProvider(plan))
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == "action"
    assert row.tool == "leave_form"
    assert row.query == "leave_form"
    for column in _log_fields(row):
        assert "Номин" not in column


@pytest.mark.django_db
def test_action_rows_count_for_the_rate_limit(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    _person()
    for _ in range(ASK_PER_HOUR):
        HelpQuestion.objects.create(user=user, question="утас", outcome=Outcome.ACTION)
    result = answer(user, "Номины утас", DAY, FieldProvider(_plan(field="private_phone")))
    assert result.outcome == Outcome.LIMITED
    assert HelpQuestion.objects.filter(user=user, outcome="limited").count() == 1


@pytest.mark.django_db
def test_old_action_rows_do_not_count(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    _person()
    for _ in range(ASK_PER_HOUR):
        row = HelpQuestion.objects.create(user=user, question="утас", outcome=Outcome.ACTION)
        HelpQuestion.objects.filter(pk=row.pk).update(asked_at=timezone.now() - timedelta(hours=2))
    result = answer(user, "Номины утас", DAY, FieldProvider(_plan(field="private_phone")))
    assert result.outcome == Outcome.ACTION


@pytest.mark.django_db
def test_field_hints_reach_the_plan_call(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    _person()
    text = "Номины утас"
    provider = FieldProvider(_plan(field="private_phone"))
    answer(user, text, DAY, provider)
    expected = [hint.key for hint in hints_for(text, limit=8)]
    assert "private_phone" in expected
    assert provider.field_hints == expected
    assert len(provider.field_hints) <= 8


@pytest.mark.django_db
def test_field_key_the_question_does_not_hint_is_none(role_user: Callable[[str], User]) -> None:
    # The accountant may read base_salary, but the words of «Номины утас» do not hint it, so the key is not answered.
    user = role_user("accountant")
    _person()
    result = answer(user, "Номины утас", DAY, FieldProvider(_plan(field="base_salary")))
    assert result.outcome == Outcome.NONE
    assert result.field is None
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == "none"
    assert row.query == ""


@pytest.mark.django_db
def test_field_key_the_question_hints_is_an_action(role_user: Callable[[str], User]) -> None:
    user = role_user("accountant")
    _person()
    result = answer(user, "Номины цалин", DAY, FieldProvider(_plan(field="base_salary")))
    assert result.outcome == Outcome.ACTION
    assert result.query == "base_salary"


@pytest.mark.django_db
def test_own_field_with_an_unlinked_login_is_none(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    _person()
    result = answer(user, "миний утас", DAY, FieldProvider(_plan(field="private_phone", own=True)))
    assert result.outcome == Outcome.NONE


@pytest.mark.django_db
def test_own_field_with_a_linked_login_is_an_action(role_user: Callable[[str], User]) -> None:
    user = role_user("staff")  # a login linked to its own employee record (conftest)
    result = answer(user, "миний утас", DAY, FieldProvider(_plan(field="private_phone", own=True)))
    assert result.outcome == Outcome.ACTION
    assert result.field is not None
    assert result.field.status == "empty"  # the seeded staff record has no private phone
    assert result.field.text == ""
    assert result.field.url.endswith("#personal-private_phone")
