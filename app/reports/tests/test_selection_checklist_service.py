"""The checklist rules of the report selection, request-free: the form model, the reading of the posted fields, the
start for each picked person and the result counts. The views are tested in test_selection_checklist.py."""

from datetime import date
from typing import Any, cast

import pytest
from accounts.models import User
from checklists import access as checklist_access
from checklists.models import ChecklistKind, ChecklistTemplate, ChecklistTemplateTask
from checklists.services import lifecycle
from employees.models import Employee
from employees.tests.conftest import named
from macs.models import FiredReason, Nationality

from reports.selection import Picked
from reports.services import selection_checklist as service
from reports.services.selection_checklist import Outcome, Values

from .conftest import legacy

pytestmark = pytest.mark.django_db

OFFBOARDING = ChecklistKind.OFFBOARDING.value
ANCHOR = date(2026, 12, 1)


def _template(kind: str, *, default: bool, reasons: tuple[str, ...] = (), active: bool = True) -> ChecklistTemplate:
    """A template of `kind` with one task. A default is made by replacing the seeded one (one default per kind)."""
    if default:
        ChecklistTemplate.objects.filter(kind=kind, is_default=True).delete()
    template = ChecklistTemplate.objects.create(
        kind=kind, name=f"{kind} {default} {reasons}", is_default=default, reasons=list(reasons), active=active
    )
    ChecklistTemplateTask.objects.create(template=template, title="Даалгавар", manager=True, due_offset_days=0)
    return template


def _picked(*employees: Employee) -> Picked:
    """A selection of these people. The start reads only the ids, so the table is not built here."""
    return Picked(table=cast(Any, None), ids=tuple(e.pk for e in employees), dropped=0)


@pytest.fixture
def offboarding_ready() -> ChecklistTemplate:
    """One active default offboarding template: starting offboarding works for everyone."""
    return _template(OFFBOARDING, default=True)


@pytest.fixture
def people(actor: User, job_values: dict[str, Any]) -> dict[str, Employee]:
    """A, B and C are working people."""
    mongol = named(Nationality, "Монгол")
    return {
        "A": legacy(actor, job_values, nationality=mongol),
        "B": legacy(actor, job_values, nationality=mongol),
        "C": legacy(actor, job_values, nationality=mongol),
    }


# form_model


def test_form_model_lists_only_reasons_some_active_offboarding_template_lists(
    offboarding_ready: ChecklistTemplate,
) -> None:
    listed = named(FiredReason, "Өөрийн хүсэлтээр")
    named(FiredReason, "Жуулчлал")  # no template lists this one
    _template(OFFBOARDING, default=False, reasons=(str(listed.pk),))
    form = service.form_model(date(2026, 11, 27))
    assert [value for value, _label in form.reasons] == [str(listed.pk)]
    assert form.reasons == [(str(listed.pk), "Өөрийн хүсэлтээр")]
    assert form.template_missing is False


def test_form_model_reports_a_missing_template_when_none_is_active(offboarding_ready: ChecklistTemplate) -> None:
    ChecklistTemplate.objects.filter(kind=OFFBOARDING).update(active=False)
    form = service.form_model(date(2026, 11, 27))
    assert form.template_missing is True
    assert form.reasons == []


def test_form_model_carries_the_anchor_limits_and_today(offboarding_ready: ChecklistTemplate) -> None:
    form = service.form_model(date(2026, 11, 27))
    assert form.anchor_min == "1990-01-01"
    assert form.anchor_max == "2100-12-31"
    assert form.today == "2026-11-27"


# read_values


@pytest.mark.parametrize("bad", ["2026-W45-1", "٢٠٢٦-١١-٠٧", "2026-13-40", ""])
def test_read_values_refuses_a_date_that_is_not_a_calendar_day_in_ascii(bad: str) -> None:
    values, anchor, errors = service.read_values("", bad)
    assert errors == [service.MSG_DATE]
    assert anchor is None
    assert values.anchor_day == bad[:10]


@pytest.mark.parametrize("out_of_range", ["1989-12-31", "2101-01-01"])
def test_read_values_refuses_a_date_outside_the_allowed_years(out_of_range: str) -> None:
    _values, anchor, errors = service.read_values("", out_of_range)
    assert errors == [service.MSG_RANGE]
    assert anchor is None


def test_read_values_refuses_a_reason_no_active_offboarding_template_lists(
    offboarding_ready: ChecklistTemplate,
) -> None:
    _values, anchor, errors = service.read_values("no-such-reason", "2026-12-01")
    assert errors == [service.MSG_REASON]
    assert anchor == ANCHOR  # the date itself is still valid


def test_read_values_accepts_a_valid_day_with_no_reason(offboarding_ready: ChecklistTemplate) -> None:
    values, anchor, errors = service.read_values("", "2026-12-01")
    assert errors == []
    assert anchor == ANCHOR
    assert values == Values(reason="", anchor_day="2026-12-01")


# start_each


def test_start_each_gives_one_outcome_per_picked_id_in_order(
    actor: User, hr_user: User, people: dict[str, Employee], offboarding_ready: ChecklistTemplate
) -> None:
    picked = _picked(people["C"], people["A"], people["B"])
    outcomes = service.start_each(hr_user, picked, Values(reason="", anchor_day="2026-12-01"), ANCHOR, ANCHOR)
    assert [item.pk for item in outcomes] == [people["C"].pk, people["A"].pk, people["B"].pk]
    assert [item.outcome for item in outcomes] == ["started", "started", "started"]
    assert all(item.employee is not None for item in outcomes)


def test_start_each_reports_a_person_who_has_left_as_left_even_with_an_open_checklist(
    actor: User,
    hr_user: User,
    job_values: dict[str, Any],
    offboarding_ready: ChecklistTemplate,
) -> None:
    dismissed = 3  # a MACS emptype the listing counts as not working: such a person has left
    gone = legacy(actor, job_values, nationality=named(Nationality, "Монгол"), emptype=dismissed)
    lifecycle.start(gone, ChecklistKind.OFFBOARDING, reason=None, anchor_day=ANCHOR, by=actor)
    outcomes = service.start_each(hr_user, _picked(gone), Values("", "2026-12-15"), date(2026, 12, 15), ANCHOR)
    assert [item.outcome for item in outcomes] == ["left"]


def test_start_each_reports_an_id_that_no_longer_reads_back_as_not_allowed(
    hr_user: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Employee.objects, "in_bulk", lambda *args, **kwargs: {})
    outcomes = service.start_each(hr_user, _picked(people["A"]), Values("", "2026-12-01"), ANCHOR, ANCHOR)
    assert len(outcomes) == 1
    assert outcomes[0].pk == people["A"].pk
    assert outcomes[0].employee is None
    assert outcomes[0].outcome == "not_allowed"


def test_start_each_turns_one_persons_exception_into_error_and_the_next_still_starts(
    hr_user: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_start = lifecycle.start

    def failing_for_b(employee: Employee, *args: Any, **kwargs: Any) -> Any:
        if employee.pk == people["B"].pk:
            raise RuntimeError("boom")
        return real_start(employee, *args, **kwargs)

    monkeypatch.setattr(lifecycle, "start", failing_for_b)
    outcomes = service.start_each(
        hr_user, _picked(people["A"], people["B"], people["C"]), Values("", "2026-12-01"), ANCHOR, ANCHOR
    )
    assert [item.outcome for item in outcomes] == ["started", "error", "started"]


def test_start_each_reports_a_person_outside_the_access_rules_as_not_allowed(
    hr_user: User,
    people: dict[str, Employee],
    offboarding_ready: ChecklistTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = people["B"].pk
    monkeypatch.setattr(checklist_access, "can_see_employee", lambda user, employee: employee.pk != blocked)
    outcomes = service.start_each(hr_user, _picked(people["A"], people["B"]), Values("", "2026-12-01"), ANCHOR, ANCHOR)
    assert [item.outcome for item in outcomes] == ["started", "not_allowed"]


# result_of


def test_result_of_counts_every_outcome_name_and_adds_up_to_the_list_length(
    actor: User, people: dict[str, Employee]
) -> None:
    outcomes = [
        Outcome(people["A"].pk, people["A"], "started"),
        Outcome(people["B"].pk, people["B"], "started"),
        Outcome(people["C"].pk, people["C"], "already_open"),
        Outcome(999, None, "not_allowed"),
    ]
    result = service.result_of(outcomes, dropped=2)
    assert set(result.counts) == set(service.OUTCOME_LABELS)
    assert result.counts["started"] == 2
    assert result.counts["already_open"] == 1
    assert result.counts["left"] == 0
    assert sum(result.counts.values()) == len(outcomes)
    assert result.dropped == 2


def test_result_of_rows_use_the_code_or_the_id_text_and_the_outcome_label(
    actor: User, people: dict[str, Employee]
) -> None:
    people["A"].code = "E-17"
    outcomes = [
        Outcome(people["A"].pk, people["A"], "started"),
        Outcome(999, None, "not_allowed"),
    ]
    result = service.result_of(outcomes, dropped=0)
    assert result.rows == [
        ("E-17", people["A"].full_name, service.OUTCOME_LABELS["started"]),
        ("999", "", service.OUTCOME_LABELS["not_allowed"]),
    ]
