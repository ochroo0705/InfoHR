from datetime import date, timedelta
from decimal import Decimal

import pytest
from accounts.models import User
from macs.models import EmployeeHistory, FiredReason, Movement

from employees.models import Department, Employee, Event, EventProdRow, LeaveKind, Position
from employees.services import events, macs_writes
from employees.tests.conftest import hire_values, named
from employees.tests.test_events import future, rec

DAY = date(2026, 3, 1)


@pytest.fixture
def lead(db: None) -> Position:
    return Position.objects.create(name="Ахлах нягтлан")


@pytest.fixture
def other_dept(db: None) -> Department:
    return macs_writes.save_department("Захиргаа")


def rows(ev: Event) -> tuple[Movement | None, EmployeeHistory]:
    link = ev.prod_rows.get()
    mv = Movement.objects.get(pk=link.movement_id or 0) if link.movement_id else None
    return mv, EmployeeHistory.objects.get(pk=link.history_id or 0)


def test_transfer_writes_dep_movement_and_snapshot(hired: Employee, actor: User, other_dept: Department) -> None:
    old_dep = hired.department_id
    ev = rec(hired, actor, "transfer", DAY, changes={"department": other_dept})
    mv, snap = rows(ev)
    assert mv is not None and mv.kind == "dep" and mv.date == DAY
    assert (mv.old_department_id_value, mv.new_department_id_value) == (old_dep, other_dept.pk)
    assert snap.department_id_value == other_dept.pk and snap.changed_date == DAY


def test_dept_and_position_change_one_dep_row(
    hired: Employee, actor: User, other_dept: Department, lead: Position
) -> None:
    old_pos = hired.position_id
    ev = rec(hired, actor, "transfer", DAY, changes={"department": other_dept, "position": lead})
    mv, _ = rows(ev)
    assert mv is not None and mv.kind == "dep"
    assert Movement.objects.filter(employee=hired).exclude(kind="in").count() == 1
    assert (mv.new_department_id_value, mv.new_position_id_value) == (other_dept.pk, lead.pk)
    assert mv.old_position_id_value == old_pos


def test_promotion_writes_occ(hired: Employee, actor: User, lead: Position) -> None:
    old_pos = hired.position_id
    ev = rec(hired, actor, "promotion", DAY, changes={"position": lead})
    mv, snap = rows(ev)
    assert mv is not None and mv.kind == "occ"
    assert (mv.old_position_id_value, mv.new_position_id_value) == (old_pos, lead.pk)
    assert snap.position_id_value == lead.pk


def test_termination_writes_out_with_fired_reason_on_snapshot(hired: Employee, actor: User) -> None:
    fr = named(FiredReason, "Өөрийн хүсэлтээр")
    ev = rec(hired, actor, "termination", DAY, fired_reason=fr)
    mv, snap = rows(ev)
    assert mv is not None and mv.kind == "out" and mv.new_emptype == 3 and mv.old_emptype == 1
    assert snap.fired_date == DAY and snap.fired_reason_id_value == fr.pk
    assert (snap.emptype, snap.status) == (3, "inactive")


def test_rehire_writes_in(hired: Employee, actor: User) -> None:
    rec(hired, actor, "termination", DAY, fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"))
    ev = rec(
        hired, actor, "rehire", date(2026, 5, 1), changes={"employee_type": "full_time"}, salary=Decimal("2600000")
    )
    mv, snap = rows(ev)
    assert mv is not None and mv.kind == "in" and mv.old_emptype == 3 and mv.new_emptype == 1
    assert snap.salary == Decimal("2600000.00") and snap.fired_date is None


def test_salary_change_writes_snapshot_only(hired: Employee, actor: User) -> None:
    ev = rec(hired, actor, "salary_change", DAY, salary=Decimal("3000000"))
    mv, snap = rows(ev)
    assert mv is None
    assert snap.salary == Decimal("3000000.00") and snap.changed_date == DAY


def test_scheduled_event_rows_dated_effective(hired: Employee, actor: User, other_dept: Department) -> None:
    day = future()
    old_dep = hired.department_id
    ev = rec(hired, actor, "transfer", day, changes={"department": other_dept})
    mv, snap = rows(ev)
    assert mv is not None and mv.date == day and mv.new_department_id_value == other_dept.pk
    assert snap.department_id_value == other_dept.pk and snap.changed_date == day
    hired.refresh_from_db()
    assert hired.department_id == old_dep


def test_snapshot_history_falls_back_to_live_row_without_hr_records(actor: User) -> None:
    legacy = macs_writes.create_employee(hire_values(), {}, code=macs_writes.next_code(), by=actor)
    legacy.salary = Decimal("777")
    legacy.save(update_fields=["salary"])
    hid = macs_writes.snapshot_history(legacy, DAY, fired_reason_id=None)
    snap = EmployeeHistory.objects.get(pk=hid)
    assert snap.salary == Decimal("777.00") and snap.changed_date == DAY and snap.emptype == legacy.emptype


def test_no_link_rows_without_events(hired: Employee) -> None:
    assert EventProdRow.objects.count() == 0


def test_termination_snapshot_sets_fired_date_without_reason(hired: Employee) -> None:
    snap = EmployeeHistory.objects.get(pk=macs_writes.snapshot_history(hired, DAY, terminating=True))
    assert snap.fired_date == DAY and snap.fired_reason_id_value is None


def test_movement_old_values_come_from_day_before_effective(
    hired: Employee, actor: User, other_dept: Department, lead: Position
) -> None:
    first_dep = hired.department_id
    rec(hired, actor, "transfer", date(2026, 2, 1), changes={"department": other_dept})
    ev = rec(hired, actor, "promotion", date(2026, 3, 1), changes={"position": lead})
    mv, _ = rows(ev)
    assert mv is not None and mv.old_department_id_value == other_dept.pk != first_dep
    hired.refresh_from_db()
    assert hired.position_id == lead.pk  # live row already switched; old position still the earlier one
    assert mv.old_position_id_value != lead.pk


def test_cancel_transfer_deletes_rows(hired: Employee, actor: User, other_dept: Department) -> None:
    ev = rec(hired, actor, "transfer", future(), changes={"department": other_dept})
    link = ev.prod_rows.get()
    mv_id, hist_id = link.movement_id, link.history_id
    events.cancel(ev, reason="алдаа", by=actor, cancel_order_no="А/50")
    assert not Movement.objects.filter(pk=mv_id or 0).exists()
    assert not EmployeeHistory.objects.filter(pk=hist_id or 0).exists()
    assert not EventProdRow.objects.filter(event=ev).exists()


def test_cancel_scheduled_termination_restores_flags(hired: Employee, actor: User) -> None:
    ev = rec(hired, actor, "termination", future(), fired_reason=named(FiredReason, "Өөрийн хүслээр"))
    events.cancel(ev, reason="алдаа", by=actor, cancel_order_no="А/51")
    hired.refresh_from_db()
    assert hired.fired_reason_id is None and hired.died != "yes"
    assert not Movement.objects.filter(employee=hired, kind="out").exists()
    assert not EmployeeHistory.objects.filter(employee_id_value=hired.pk, fired_date__isnull=False).exists()
    assert not EventProdRow.objects.filter(event=ev).exists()


def test_left_without_live_termination_keeps_reason_and_died(hired: Employee) -> None:
    from employees.models import JobRecord, JobStatus

    fr = named(FiredReason, "Хуучин шалтгаан")
    macs_writes.update_employee_columns(hired, {"fired_reason_id": fr.pk, "died": "yes"})
    job = JobRecord(status=JobStatus.LEFT)
    flags = macs_writes._flags(hired, job, DAY)
    assert flags["fired_reason_id"] == fr.pk and flags["died"] == "yes"


def test_long_leave_without_live_leave_start_keeps_leave_type(hired: Employee) -> None:
    from employees.models import JobRecord, JobStatus

    macs_writes.update_employee_columns(hired, {"leave_type": 2})
    flags = macs_writes._flags(hired, JobRecord(status=JobStatus.LONG_LEAVE), DAY)
    assert flags["taken_leave"] == 1 and flags["leave_type"] == 2


def test_cancel_scheduled_long_leave_leaves_flags_clear(hired: Employee, actor: User) -> None:
    ev = rec(hired, actor, "leave_start", future(), reason=LeaveKind.values[0])
    events.cancel(ev, reason="алдаа", by=actor)
    hired.refresh_from_db()
    assert (hired.taken_leave, hired.leave_type) == (0, None)
    macs_writes.sync_current(hired, future() + timedelta(days=1))
    hired.refresh_from_db()
    assert (hired.taken_leave, hired.leave_type) == (0, None)


def test_cancel_when_rows_already_gone(hired: Employee, actor: User, other_dept: Department) -> None:
    ev = rec(hired, actor, "transfer", future(), changes={"department": other_dept})
    Movement.objects.filter(employee=hired, kind="dep").delete()
    EmployeeHistory.objects.filter(pk=ev.prod_rows.get().history_id or 0).delete()
    events.cancel(ev, reason="алдаа", by=actor, cancel_order_no="А/53")
    assert not EventProdRow.objects.filter(event=ev).exists()


def test_cancel_leaves_other_events_rows(hired: Employee, actor: User, other_dept: Department, lead: Position) -> None:
    first = rec(hired, actor, "transfer", date.today() + timedelta(days=10), changes={"department": other_dept})
    second = rec(hired, actor, "promotion", future(), changes={"position": lead})
    events.cancel(second, reason="алдаа", by=actor, cancel_order_no="А/54")
    assert first.prod_rows.count() == 1
    mv, snap = rows(first)
    assert mv is not None and snap is not None


def test_snapshot_copies_contact_and_insurance_columns(hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(
        work_phone="99112233",
        private_phone="88112233",
        email="a@b.mn",
        passport_no="P123",
        account_no="5000",
        social_insurance_no="ND1",
        health_insurance_no="EM1",
        prior_service_years=3,
    )
    hired.refresh_from_db()
    snap = EmployeeHistory.objects.get(pk=macs_writes.snapshot_history(hired))
    assert (snap.work_phone, snap.private_phone) == ("99112233", "88112233")
    assert (snap.email, snap.passport_no) == ("a@b.mn", "P123")
    assert (snap.account_no, snap.social_insurance_no, snap.health_insurance_no) == ("5000", "ND1", "EM1")
    assert snap.prior_service_years == 3
