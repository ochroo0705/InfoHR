"""build_page: the request-free state of the event form pop-up (the GET branches of event_form)."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.http import Http404

from employees.models import Employee, EventType, Position
from employees.services import events, history, macs_writes
from employees.services.event_page import build_page

from .helpers import record_signed
from .test_access import user_in

TODAY = date(2026, 11, 19)


@pytest.fixture
def hr(db: None) -> User:
    return user_in("HR", "hr_page")


def test_first_open_prefills_values_in_force_today(hired: Employee, hr: User) -> None:
    page = build_page(hr, hired, "promotion", None, today=TODAY)
    job = history.job_on(hired, TODAY)
    assert job is not None
    assert page.form.initial["effective"] == TODAY
    assert page.form.initial["position"] == job.position_id
    assert page.summary == ""
    assert page.reload is False
    assert page.prev_effective is None
    assert page.when == ""
    assert page.order_form is not None


def test_date_change_refills_untouched_boxes_only(hired: Employee, hr: User, actor: User) -> None:
    old_job = history.job_on(hired, date(2026, 2, 1))
    assert old_job is not None
    lead = Position.objects.create(name="Ахлах нягтлан")
    new_dept = macs_writes.save_department("Санхүү 2")
    record_signed(
        hired,
        type="transfer",
        effective=date(2026, 3, 1),
        changes={"position": lead, "department": new_dept},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    edited = Position.objects.create(name="Туслах нягтлан")
    values: dict[str, Any] = {
        "effective": "2026-04-01",
        "position": str(edited.pk),  # edited by the user: differs from the old date's value, must be kept
        "department": str(old_job.department_id),  # untouched: still the old date's value, must be refilled
        "reason": "x",  # typed by the user
        "note": "",
    }
    page = build_page(hr, hired, "transfer", values, prev_effective="2026-02-01", today=TODAY)
    assert page.form.initial["position"] == str(edited.pk)
    assert page.form.initial["department"] == new_dept.pk
    assert page.form.initial["reason"] == "x"
    assert page.reload is True


def test_unreal_date_keeps_text_and_only_date_error(hired: Employee, hr: User) -> None:
    page = build_page(
        hr,
        hired,
        "promotion",
        {"effective": "2026-13-45", "reason": "x"},
        prev_effective="2026-01-02",
        today=TODAY,
    )
    assert set(page.form.errors) == {"effective"}
    assert page.form.data["effective"] == "2026-13-45"
    assert page.form.fields["effective"].widget.input_type == "text"
    assert page.summary == ""
    assert page.prev_effective == "2026-01-02"
    assert page.when == ""


def test_kind_change_keeps_typed_order_fields(hired: Employee, hr: User) -> None:
    values = {
        "effective": "2026-12-19",
        "reason": "",
        "note": "",
        "order-number": "77/1",
        "order-date": "",
        "order-summary": "typed summary",
        "order-issued_by": "Typed",
    }
    page = build_page(hr, hired, "promotion", values, prev_effective="2026-11-19", today=TODAY)
    assert page.order_form is not None
    assert page.order_form.initial["number"] == "77/1"
    assert page.order_form.initial["summary"] == "typed summary"
    assert page.reload is True


def test_empty_prev_effective_still_keeps_typed_order_fields(hired: Employee, hr: User) -> None:
    # Django sends the hidden prev_effective as an empty string after a first open with no date: key presence counts.
    values = {"effective": "2026-12-19", "order-number": "77/2", "order-summary": "typed summary"}
    page = build_page(hr, hired, "promotion", values, prev_effective="", today=TODAY)
    assert page.order_form is not None
    assert page.order_form.initial["number"] == "77/2"
    assert page.order_form.initial["summary"] == "typed summary"
    assert page.reload is True
    assert page.prev_effective is None  # the view renders the form's effective date here


@pytest.mark.parametrize(
    ("effective", "when"),
    [("2026-03-01", "past"), ("2026-12-19", "future"), ("2026-11-19", "")],
)
def test_when_note_past_future_today(hired: Employee, hr: User, effective: str, when: str) -> None:
    page = build_page(hr, hired, "promotion", {"effective": effective}, today=TODAY)
    assert page.when == when


def test_placement_type_lists_kinds_with_selected_flag(hired: Employee, hr: User) -> None:
    page = build_page(hr, hired, "transfer", None, today=TODAY)
    assert page.kinds == [(t.value, t.label, t == EventType.TRANSFER) for t in events.PLACEMENT_TYPES]
    assert page.title == events.PLACEMENT_LABEL


def test_non_placement_type_has_no_kinds(hired: Employee, hr: User) -> None:
    page = build_page(hr, hired, "termination", None, today=TODAY)
    assert page.kinds == []
    assert page.title == EventType.TERMINATION.label


def test_order_block_only_for_order_types(hired: Employee, hr: User) -> None:
    accountant = user_in("Accountant", "acc_page")
    assert build_page(hr, hired, "promotion", None, today=TODAY).order_form is not None
    assert build_page(accountant, hired, "salary_change", None, today=TODAY).order_form is None


def test_unknown_type_404(hired: Employee, hr: User) -> None:
    with pytest.raises(Http404):
        build_page(hr, hired, "bogus", None, today=TODAY)


def test_no_right_for_type_raises_permission_denied(hired: Employee, hr: User) -> None:
    with pytest.raises(PermissionDenied):
        build_page(hr, hired, "salary_change", None, today=TODAY)


def test_salary_box_only_with_salary_right(hired: Employee, hr: User) -> None:
    accountant = user_in("Accountant", "acc_salary")
    assert "salary" not in build_page(hr, hired, "promotion", None, today=TODAY).form.fields
    assert "salary" in build_page(accountant, hired, "salary_change", None, today=TODAY).form.fields
