"""Signing an order applies the change it waits for, at its own date (signed-order plan, Task 5). A refused change
leaves the order registered with no scan. Changes that need no order and hires are not affected."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from accounts.models import User
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from macs.models import EmployeeHistory, FiredReason, Movement

from employees.models import (
    ChangeType,
    Employee,
    Event,
    EventProdRow,
    EventType,
    HrOrder,
    JobRecord,
    JobStatus,
    OrderState,
    OrderType,
)
from employees.services import events, history, macs_writes, orders
from employees.services.events import EventError
from employees.services.orders import OrderError
from employees.tests.conftest import named
from employees.tests.helpers import record_signed, sign_event

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)
LATER = date(2026, 4, 1)


def job_at(employee: Employee, day: date) -> JobRecord:
    job = history.job_on(employee, day)
    assert job is not None
    return job


def _stored_files() -> set[str]:
    """Every file under the order files folder (the test fixture points it at a temporary folder)."""
    root = Path(settings.ORDER_FILES_ROOT)
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def _transfer(employee: Employee, actor: User, day: date, department: str) -> Event:
    return events.record(
        employee,
        type="transfer",
        effective=day,
        changes={"department": macs_writes.save_department(department)},
        salary=None,
        reason="",
        note="",
        by=actor,
    )


def test_signing_applies_waiting_change(hired: Employee, actor: User) -> None:
    old_id = hired.department_id
    engineering = macs_writes.save_department("Инженер")
    ev = events.record(
        hired,
        type="transfer",
        effective=DAY,
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert ev.applied_at is None
    sign_event(ev, by=actor)
    order = HrOrder.objects.get(event=ev)
    assert order.state == OrderState.SIGNED
    ev.refresh_from_db()
    assert ev.applied_at is not None
    assert job_at(hired, DAY).department_id == engineering.pk
    assert job_at(hired, DAY - timedelta(days=1)).department_id == old_id
    assert Movement.objects.filter(employee=hired, kind="dep", date=DAY).count() == 1


def test_signing_refused_leaves_order_registered_and_no_file(hired: Employee, actor: User) -> None:
    # Same field (department) twice: the earlier change still waits, so the later one cannot be signed first.
    old_id = hired.department_id
    _transfer(hired, actor, DAY, "Инженер")
    late = _transfer(hired, actor, LATER, "Худалдаа")
    order = HrOrder.objects.get(event=late)
    today = timezone.localdate()
    orders.register(order, number=orders.suggest_number(today), date=today, summary="", issued_by="", by=actor)
    order.refresh_from_db()
    files_before = _stored_files()
    scan = SimpleUploadedFile("order.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    with pytest.raises(OrderError) as refused:
        orders.attach_signed_file(order, scan, by=actor)
    message = refused.value.errors["__all__"]
    assert "2026-03-01" in message
    assert ChangeType(EventType.TRANSFER.change_type).label in message
    assert _stored_files() == files_before  # the refused scan was never written to storage
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED
    assert not order.file
    late.refresh_from_db()
    assert late.applied_at is None
    assert job_at(hired, DAY).department_id == old_id


def test_signing_a_hire_order_does_nothing_extra(hired: Employee, actor: User) -> None:
    hire_order = orders.create_for_change(
        employee=hired,
        event=None,
        is_hire=True,
        order_type=OrderType.HIRED,
        number="",
        date=None,
        summary="",
        issued_by="",
        by=actor,
    )
    jobs_before = JobRecord.objects.filter(employee=hired).count()
    # The hire has no event, so sign_event does not apply: register it, then attach the scan.
    today = timezone.localdate()
    orders.register(hire_order, number=orders.suggest_number(today), date=today, summary="", issued_by="", by=actor)
    hire_order.refresh_from_db()
    scan = SimpleUploadedFile("order.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    signed = orders.attach_signed_file(hire_order, scan, by=actor)
    assert signed.state == OrderState.SIGNED
    assert signed.file
    assert JobRecord.objects.filter(employee=hired).count() == jobs_before


def test_signing_already_applied_change_is_noop(hired: Employee, actor: User) -> None:
    engineering = macs_writes.save_department("Инженер")
    ev = events.record(
        hired,
        type="transfer",
        effective=DAY,
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    order = HrOrder.objects.get(event=ev)
    today = timezone.localdate()
    orders.register(order, number=orders.suggest_number(today), date=today, summary="", issued_by="", by=actor)
    order.refresh_from_db()
    events.apply_waiting(ev, by=actor)  # applied already, while its order is still only registered
    jobs_before = JobRecord.objects.filter(employee=hired).count()
    moves_before = Movement.objects.filter(employee=hired).count()
    sign_event(ev, by=actor)
    signed = HrOrder.objects.get(event=ev)
    assert signed.state == OrderState.SIGNED
    assert JobRecord.objects.filter(employee=hired).count() == jobs_before
    assert Movement.objects.filter(employee=hired).count() == moves_before


def test_signing_later_change_first_is_refused(hired: Employee, actor: User) -> None:
    old_id = hired.department_id
    early = _transfer(hired, actor, DAY, "Инженер")
    late = _transfer(hired, actor, LATER, "Худалдаа")
    before = (
        JobRecord.objects.filter(employee=hired).count(),
        Movement.objects.filter(employee=hired).count(),
    )
    with pytest.raises(EventError) as refused:
        events.apply_waiting(late, by=actor)
    message = refused.value.errors["__all__"]
    assert "2026-03-01" in message
    assert "Шилжүүлсэн" in message
    assert "Эхлээд" in message
    late.refresh_from_db()
    early.refresh_from_db()
    assert late.applied_at is None
    assert early.applied_at is None
    assert (
        JobRecord.objects.filter(employee=hired).count(),
        Movement.objects.filter(employee=hired).count(),
    ) == before
    assert job_at(hired, DAY).department_id == old_id


def test_signing_earlier_then_later_both_apply(hired: Employee, actor: User) -> None:
    early = _transfer(hired, actor, DAY, "Инженер")
    late = _transfer(hired, actor, LATER, "Худалдаа")
    sign_event(early, by=actor)
    sign_event(late, by=actor)
    early.refresh_from_db()
    late.refresh_from_db()
    assert early.applied_at is not None
    assert late.applied_at is not None
    assert job_at(hired, DAY).department_id == _dept(early)
    assert job_at(hired, LATER).department_id == _dept(late)


def test_cancelled_earlier_waiting_change_does_not_block(hired: Employee, actor: User) -> None:
    early = _transfer(hired, actor, DAY, "Инженер")
    Event.objects.filter(pk=early.pk).update(cancelled_at=timezone.now())  # a cancelled change never blocks
    late = _transfer(hired, actor, LATER, "Худалдаа")
    sign_event(late, by=actor)
    late.refresh_from_db()
    assert late.applied_at is not None
    assert job_at(hired, LATER).department_id == _dept(late)
    assert job_at(hired, DAY).status == JobStatus.ACTIVE


def _register_today(order: HrOrder, actor: User) -> HrOrder:
    today = timezone.localdate()
    orders.register(order, number=orders.suggest_number(today), date=today, summary="", issued_by="", by=actor)
    order.refresh_from_db()
    return order


def _scan() -> SimpleUploadedFile:
    return SimpleUploadedFile("order.pdf", b"%PDF-1.4 test", content_type="application/pdf")


def test_register_then_sign_termination_links_order_to_history_row(hired: Employee, actor: User) -> None:
    ev = events.record(
        hired,
        type="termination",
        effective=DAY,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    order = _register_today(HrOrder.objects.get(event=ev), actor)
    sign_event(ev, by=actor)
    order.refresh_from_db()
    assert order.state == OrderState.SIGNED
    assert order.command_id is not None
    history_id = EventProdRow.objects.get(event=ev).history_id
    assert history_id is not None  # noqa: S101
    row = EmployeeHistory.objects.get(pk=history_id)
    assert row.command_id_value == order.command_id
    assert row.move_type == order.order_type


def test_signing_transfer_after_employee_left_is_refused(hired: Employee, actor: User) -> None:
    engineering = macs_writes.save_department("Инженер")
    transfer = events.record(
        hired,
        type="transfer",
        effective=LATER,
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    record_signed(
        hired,
        type="termination",
        effective=DAY,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    order = _register_today(HrOrder.objects.get(event=transfer), actor)
    jobs_before = JobRecord.objects.filter(employee=hired).count()
    with pytest.raises(OrderError) as refused:
        orders.attach_signed_file(order, _scan(), by=actor)
    assert "ажлаас гарсан байна" in refused.value.errors["__all__"]
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED
    transfer.refresh_from_db()
    assert transfer.applied_at is None
    assert JobRecord.objects.filter(employee=hired).count() == jobs_before
    assert job_at(hired, LATER).status == JobStatus.LEFT


def test_signing_after_department_was_deleted_is_refused(hired: Employee, actor: User) -> None:
    engineering = macs_writes.save_department("Инженер")
    ev = events.record(
        hired,
        type="transfer",
        effective=DAY,
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    order = _register_today(HrOrder.objects.get(event=ev), actor)
    macs_writes.delete_department(engineering)
    with pytest.raises(OrderError) as refused:
        orders.attach_signed_file(order, _scan(), by=actor)
    assert "устгагдсан байна" in refused.value.errors["__all__"]
    order.refresh_from_db()
    assert order.state == OrderState.REGISTERED
    ev.refresh_from_db()
    assert ev.applied_at is None


def _dept(event: Event) -> int:
    """The department id a waiting transfer proposed."""
    assert event.proposed is not None  # noqa: S101
    return int(event.proposed["job"]["department"])
