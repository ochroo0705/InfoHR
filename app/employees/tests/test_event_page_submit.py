"""event_page.submit and the cancel services: the POST branches of `views.event_form` and `views.event_cancel` without
the request. A refusal writes nothing and returns the bound page again."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from checklists.models import Checklist, ChecklistState, ChecklistTemplate
from checklists.services import gate
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils import timezone
from macs.models import FiredReason

from employees.models import Employee, Event, HrOrder, OrderState
from employees.services import events, history, macs_writes, slots
from employees.services.event_page import cancel_page, submit, submit_cancel
from employees.services.events import EventError

from .conftest import named
from .helpers import next_order_number, record_signed
from .test_access import user_in
from .test_events import PAST

pytestmark = pytest.mark.django_db


def future_day() -> date:
    return timezone.localdate() + timedelta(days=30)


@pytest.fixture
def hr(db: None) -> User:
    return user_in("HR", "hr_submit")


@pytest.fixture
def admin(db: None) -> User:
    return user_in("Admin", "admin_submit")


def transfer_values(emp: Employee, **extra: str) -> dict[str, str]:
    """A transfer to a new department, on a future date, with an order number."""
    job = emp.job_records.get()
    new_dept = macs_writes.save_department("Санхүү 2")
    return {
        "effective": future_day().isoformat(),
        "department": str(new_dept.pk),
        "position": str(job.position_id),
        "manager": "",
        "reason": "",
        "note": "",
        "order-number": next_order_number(),
        **extra,
    }


def test_valid_transfer_records_event_and_order(hired: Employee, hr: User) -> None:
    before = Event.objects.count()
    outcome = submit(hr, hired, "transfer", transfer_values(hired))
    assert outcome.ok is True
    assert Event.objects.count() == before + 1
    assert outcome.order is not None
    assert outcome.order.event is not None and outcome.order.event.employee_id == hired.pk


def test_invalid_form_returns_not_ok_and_writes_nothing(hired: Employee, hr: User) -> None:
    before = Event.objects.count()
    outcome = submit(hr, hired, "transfer", transfer_values(hired, effective=""))
    assert outcome.ok is False
    assert "effective" in outcome.page.form.errors
    assert outcome.order is None
    assert Event.objects.count() == before


def test_event_error_on_order_number_lands_on_order_block(hired: Employee, hr: User, monkeypatch: Any) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise EventError({"order_number": "x"})

    monkeypatch.setattr(events, "record", refuse)
    outcome = submit(hr, hired, "transfer", transfer_values(hired))
    assert outcome.ok is False
    assert outcome.page.order_form is not None
    assert "number" in outcome.page.order_form.errors
    assert "order_number" not in outcome.page.form.errors


def test_event_error_other_key_lands_on_form_or_non_field(hired: Employee, hr: User, monkeypatch: Any) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise EventError({"reason": "Шалтгаан буруу", "zzz": "Тодорхойгүй алдаа"})

    monkeypatch.setattr(events, "record", refuse)
    outcome = submit(hr, hired, "transfer", transfer_values(hired))
    assert outcome.ok is False
    assert "reason" in outcome.page.form.errors
    assert "Тодорхойгүй алдаа" in outcome.page.form.non_field_errors()


def test_rehire_slot_blocked_adds_message_and_writes_nothing(
    hired: Employee, hr: User, admin: User, monkeypatch: Any
) -> None:
    record_signed(
        hired,
        type="termination",
        effective=PAST,
        changes={},
        salary=None,
        reason="",
        note="",
        by=admin,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )

    def blocked(**kwargs: Any) -> None:
        raise slots.SlotBlocked("Орон тоо дүүрсэн байна.")

    monkeypatch.setattr(slots, "gate", blocked)
    job = hired.job_records.order_by("-start_date", "-id").first()
    assert job is not None
    before = Event.objects.count()
    values = {
        "effective": "2026-05-01",
        "position": str(job.position_id),
        "department": str(job.department_id),
        "manager": "",
        "employee_type": "full_time",
        "contract_type": "open_ended",
        "reason": "",
        "note": "",
        "order-number": next_order_number(),
    }
    outcome = submit(admin, hired, "rehire", values)
    assert outcome.ok is False
    assert "Орон тоо дүүрсэн байна." in outcome.page.form.non_field_errors(), outcome.page.form.errors.as_text()
    assert outcome.order is None
    assert Event.objects.count() == before


def test_termination_runs_the_gate_with_reason_and_override(hired: Employee, monkeypatch: Any) -> None:
    perm = Permission.objects.get(content_type__app_label="checklists", codename="override_offboarding")
    hr = user_in("HR", "hr_term")
    hr.user_permissions.add(perm)
    hr = User.objects.get(pk=hr.pk)  # fresh permission cache
    fired = named(FiredReason, "Өөрийн хүсэлтээр")
    gate_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(gate, "prepare", lambda employee, **kw: gate_calls.append({"employee": employee, **kw}))
    recorded: dict[str, Any] = {}
    real_record = events.record

    def spy(*args: Any, **kwargs: Any) -> Event:
        recorded.update(kwargs)
        return real_record(*args, **kwargs)

    monkeypatch.setattr(events, "record", spy)
    effective = future_day()
    values = {
        "effective": effective.isoformat(),
        "fired_reason": str(fired.pk),
        "offboarding_override": "Шалтгаан",
        "note": "",
        "order-number": next_order_number(),
    }
    outcome = submit(hr, hired, "termination", values)
    assert outcome.ok is True
    assert len(gate_calls) == 1
    assert gate_calls[0]["reason"] == str(fired.pk)
    assert gate_calls[0]["anchor_day"] == effective
    assert gate_calls[0]["by"] == hr
    assert recorded["offboarding_override"] == "Шалтгаан"


def test_salary_equal_to_current_is_ignored_except_salary_change(
    hired: Employee, admin: User, monkeypatch: Any
) -> None:
    current = history.salary_on(hired, future_day())
    assert current is not None
    recorded: dict[str, Any] = {}
    real_record = events.record

    def spy(*args: Any, **kwargs: Any) -> Event:
        recorded.update(kwargs)
        return real_record(*args, **kwargs)

    monkeypatch.setattr(events, "record", spy)
    same = str(current.base_salary)
    submit(admin, hired, "promotion", {**transfer_values(hired), "salary": same, "order-number": next_order_number()})
    assert recorded["salary"] is None  # untouched pay box: no pay change

    recorded.clear()
    outcome = submit(admin, hired, "salary_change", {"effective": future_day().isoformat(), "salary": same})
    # The pay is kept (a salary change always carries its pay), and events.record refuses a change to the same pay.
    assert recorded["salary"] == Decimal(same)
    assert outcome.ok is False
    assert "salary" in outcome.page.form.errors


def test_cancel_page_unknown_or_applied_event_404(hired: Employee, admin: User, hr: User) -> None:
    with pytest.raises(Http404):
        cancel_page(hr, hired, 999999)
    applied = record_signed(
        hired,
        type="transfer",
        effective=PAST,
        changes={"department": macs_writes.save_department("Санхүү 3")},
        salary=None,
        reason="",
        note="",
        by=admin,
    )
    with pytest.raises(Http404):
        cancel_page(hr, hired, applied.pk)


def test_cancel_page_signed_order_hint_and_required_cancel_order_no(hired: Employee, admin: User) -> None:
    event = record_signed(
        hired,
        type="transfer",
        effective=future_day(),
        changes={"department": macs_writes.save_department("Санхүү 4")},
        salary=None,
        reason="",
        note="",
        by=admin,
    )
    order = HrOrder.objects.get(event=event)
    assert order.state == OrderState.SIGNED
    page = cancel_page(admin, hired, event.pk)
    assert page.form.fields["cancel_order_no"].required
    assert page.title == f"Цуцлах: {event.get_type_display()} ({event.effective:%Y-%m-%d})"
    assert page.hint == (
        "Өөрчлөлт болон түүний тушаал цуцлагдсан гэж түүхэнд үлдэнэ. "
        "Өөрчлөлт аль хэдийн бүртгэгдсэн бол ажилтны албан тушаал, цалин өмнөх утгад буцна. "
        f"Цуцлах дугаар нь № {order.number} тушаалыг хүчингүй болгосон ШИНЭ тушаалын дугаар."
    )

    # A change with no order (a pay change) gets the base hint and no cancel order number.
    leave = events.record(
        hired,
        type="leave_start",
        effective=future_day() + timedelta(days=60),  # the signed change above already holds future_day()
        changes={},
        salary=None,
        reason="maternity",
        note="",
        by=admin,
    )
    plain = cancel_page(admin, hired, leave.pk)
    assert "cancel_order_no" not in plain.form.fields
    assert plain.hint == (
        "Өөрчлөлт цуцлагдсан гэж түүхэнд үлдэнэ. "
        "Өөрчлөлт аль хэдийн бүртгэгдсэн бол ажилтны албан тушаал, цалин өмнөх утгад буцна."
    )


def test_refused_termination_keeps_started_checklist(hired: Employee, hr: User) -> None:
    """The real offboarding gate refuses (open required tasks): the checklist it started stays, no termination."""
    ChecklistTemplate.objects.update(active=True)  # the seeded offboarding template gates the termination again
    fired = named(FiredReason, "Өөрийн хүсэлтээр")
    values = {
        "effective": future_day().isoformat(),
        "fired_reason": str(fired.pk),
        "note": "",
        "order-number": next_order_number(),
    }
    outcome = submit(hr, hired, "termination", values)
    assert outcome.ok is False
    assert Checklist.objects.get(employee=hired).state == ChecklistState.OPEN
    assert not Event.objects.filter(type="termination").exists()


def test_cancel_page_forbidden_without_right(hired: Employee, admin: User) -> None:
    event = record_signed(
        hired,
        type="transfer",
        effective=future_day(),
        changes={"department": macs_writes.save_department("Санхүү 5")},
        salary=None,
        reason="",
        note="",
        by=admin,
    )
    with pytest.raises(PermissionDenied):
        cancel_page(user_in("Accountant", "acc_cancel"), hired, event.pk)


def test_submit_cancel_ok_cancels_event_and_order(hired: Employee, admin: User, hr: User) -> None:
    event = record_signed(
        hired,
        type="transfer",
        effective=future_day(),
        changes={"department": macs_writes.save_department("Санхүү 6")},
        salary=None,
        reason="",
        note="",
        by=admin,
    )
    ok, form = submit_cancel(hr, hired, event.pk, {"reason": "алдаа", "cancel_order_no": "А/60"})
    assert ok is True, form.errors.as_text()
    event.refresh_from_db()
    assert event.cancelled_at is not None
    order = HrOrder.objects.get(event=event)
    assert order.state == OrderState.CANCELLED


def test_submit_cancel_blank_reason_not_ok(hired: Employee, admin: User, hr: User) -> None:
    event = record_signed(
        hired,
        type="transfer",
        effective=future_day(),
        changes={"department": macs_writes.save_department("Санхүү 7")},
        salary=None,
        reason="",
        note="",
        by=admin,
    )
    ok, form = submit_cancel(hr, hired, event.pk, {"reason": " "})
    assert ok is False
    assert "reason" in form.errors
    event.refresh_from_db()
    assert event.cancelled_at is None


def test_submit_cancel_event_error_on_cancel_order_no(hired: Employee, admin: User, hr: User, monkeypatch: Any) -> None:
    event = record_signed(
        hired,
        type="transfer",
        effective=future_day(),
        changes={"department": macs_writes.save_department("Санхүү 8")},
        salary=None,
        reason="",
        note="",
        by=admin,
    )

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise EventError({"cancel_order_no": "Дугаар буруу байна."})

    monkeypatch.setattr(events, "cancel", refuse)
    ok, form = submit_cancel(hr, hired, event.pk, {"reason": "алдаа", "cancel_order_no": "А/1"})
    assert ok is False
    assert "Дугаар буруу байна." in form.errors["cancel_order_no"]


def test_refused_page_has_prev_effective_summary_and_reload(hired: Employee, hr: User, monkeypatch: Any) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise EventError({"reason": "Шалтгаан буруу"})

    monkeypatch.setattr(events, "record", refuse)
    values = transfer_values(hired)
    outcome = submit(hr, hired, "transfer", values)
    page = outcome.page
    assert page.prev_effective == future_day().isoformat()
    assert page.reload is True
    assert page.when == "future"
    assert page.summary.endswith(f"{future_day():%Y-%m-%d}-нээс") and "→" in page.summary

    # An unreal date: the typed text stays, only the date errors, the last real date is kept, the summary is empty.
    bad = {**values, "effective": "2026-13-45", "prev_effective": "2026-01-02"}
    outcome = submit(hr, hired, "transfer", bad)
    page = outcome.page
    assert outcome.ok is False
    assert page.form.data["effective"] == "2026-13-45"
    assert "effective" in page.form.errors
    assert page.form.fields["effective"].widget.input_type == "text"
    assert page.prev_effective == "2026-01-02"
    assert page.summary == ""
    assert page.when == ""
    assert page.reload is True
