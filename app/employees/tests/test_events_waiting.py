"""A change that needs an HR order waits for its signature: nothing is written until the order is signed (signed-order
plan, Task 4). A change with no order applies at once, as before."""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from accounts.models import User
from django.utils import timezone
from lists.models import DEATH, MeaningfulEntry
from macs.models import EmployeeHistory, FiredReason, Movement

from employees.models import (
    ActivityEntry,
    Employee,
    EmployeeExt,
    Event,
    EventProdRow,
    HrOrder,
    JobRecord,
    JobStatus,
    LeaveKind,
    OrderState,
    OrderType,
    Position,
    SalaryRecord,
    ensure_ext,
)
from employees.services import events, history, macs_writes
from employees.services.events import EventError
from employees.tests.conftest import named
from employees.tests.helpers import record_signed, sign_event

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)
LATER = date(2026, 4, 1)


def job_at(employee: Employee, day: date) -> JobRecord:
    job = history.job_on(employee, day)
    assert job is not None
    return job


def salary_at(employee: Employee, day: date) -> SalaryRecord:
    salary = history.salary_on(employee, day)
    assert salary is not None
    return salary


def test_transfer_waits_and_writes_no_history(hired: Employee, actor: User) -> None:
    old_id = hired.department_id
    engineering = macs_writes.save_department("Инженер")
    jobs_before = JobRecord.objects.filter(employee=hired).count()
    moves_before = Movement.objects.filter(employee=hired).count()
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
    hired.refresh_from_db()
    assert old_id is not None
    assert hired.department_id == old_id
    assert job_at(hired, DAY).department_id == old_id
    assert JobRecord.objects.filter(employee=hired).count() == jobs_before
    assert Movement.objects.filter(employee=hired).count() == moves_before
    assert ev.applied_at is None
    assert ev.status(timezone.localdate()) == "awaiting_signature"
    assert HrOrder.objects.get(event=ev).state == OrderState.PENDING


def test_salary_only_applies_immediately(hired: Employee, actor: User) -> None:
    ev = events.record(
        hired,
        type="salary_change",
        effective=DAY,
        changes={},
        salary=Decimal("3000000"),
        reason="",
        note="",
        by=actor,
    )
    assert ev.applied_at is not None
    assert salary_at(hired, DAY).base_salary == Decimal("3000000")
    assert not HrOrder.objects.filter(event=ev).exists()


def test_leave_start_applies_immediately(hired: Employee, actor: User) -> None:
    ev = events.record(
        hired,
        type="leave_start",
        effective=DAY,
        changes={},
        salary=None,
        reason=LeaveKind.MATERNITY.value,
        note="",
        by=actor,
        expected_return=LATER,
    )
    assert ev.applied_at is not None
    assert job_at(hired, DAY).status == JobStatus.LONG_LEAVE
    assert job_at(hired, DAY - timedelta(days=1)).status == JobStatus.ACTIVE


def test_apply_waiting_uses_own_date(hired: Employee, actor: User) -> None:
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
    ev = sign_event(ev, by=actor)
    assert ev.applied_at is not None
    assert job_at(hired, DAY).department_id == engineering.pk
    assert job_at(hired, DAY - timedelta(days=1)).department_id == old_id
    hired.refresh_from_db()
    assert hired.department_id == engineering.pk
    assert Movement.objects.filter(employee=hired, kind="dep", date=DAY).count() == 1


def test_apply_waiting_inserts_before_later_salary_change(hired: Employee, actor: User) -> None:
    engineering = macs_writes.save_department("Инженер")
    waiting = events.record(
        hired,
        type="transfer",
        effective=DAY,
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    later = events.record(
        hired,
        type="salary_change",
        effective=LATER,
        changes={},
        salary=Decimal("3000000"),
        reason="",
        note="",
        by=actor,
    )
    assert later.applied_at is not None
    assert waiting.applied_at is None
    signed = sign_event(waiting, by=actor)
    assert signed.applied_at is not None
    assert job_at(hired, DAY).department_id == engineering.pk
    assert salary_at(hired, LATER).base_salary == Decimal("3000000")
    assert salary_at(hired, DAY).base_salary == Decimal("2500000")


def test_apply_waiting_refused_for_later_change_while_earlier_waits(hired: Employee, actor: User) -> None:
    # Ordering rule (Task 5): the later of two waiting changes cannot be signed while the earlier one still waits.
    old_id = hired.department_id
    first_dep = macs_writes.save_department("Инженер")
    second_dep = macs_writes.save_department("Худалдаа")
    early = events.record(
        hired,
        type="transfer",
        effective=DAY,
        changes={"department": first_dep},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    late = events.record(
        hired,
        type="transfer",
        effective=LATER,
        changes={"department": second_dep},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    before = _write_counts(hired)
    with pytest.raises(EventError) as refused:
        events.apply_waiting(late, by=actor)
    assert "2026-03-01" in refused.value.errors["__all__"]
    early.refresh_from_db()
    late.refresh_from_db()
    assert early.applied_at is None
    assert late.applied_at is None
    assert _write_counts(hired) == before
    assert JobRecord.objects.filter(employee=hired).count() == 1
    assert job_at(hired, DAY).department_id == old_id


def test_pension_flag_set_only_after_apply(hired: Employee, actor: User) -> None:
    ev = events.record(
        hired,
        type="contract",
        effective=DAY,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        pension=True,
    )
    assert ev.applied_at is None
    assert not EmployeeExt.objects.filter(employee=hired, is_pensioner=True).exists()
    sign_event(ev, by=actor)
    assert EmployeeExt.objects.get(employee=hired).is_pensioner is True


def test_waiting_salary_with_transfer_waits_together(hired: Employee, actor: User) -> None:
    engineering = macs_writes.save_department("Инженер")
    salaries_before = SalaryRecord.objects.filter(employee=hired).count()
    ev = events.record(
        hired,
        type="transfer",
        effective=DAY,
        changes={"department": engineering},
        salary=Decimal("3000000"),
        reason="",
        note="",
        by=actor,
    )
    assert ev.applied_at is None
    assert ev.proposed is not None and ev.proposed["salary"] == "3000000"
    assert SalaryRecord.objects.filter(employee=hired).count() == salaries_before
    assert salary_at(hired, DAY).base_salary == Decimal("2500000")
    sign_event(ev, by=actor)
    assert salary_at(hired, DAY).base_salary == Decimal("3000000")
    assert job_at(hired, DAY).department_id == engineering.pk


def test_no_order_event_has_applied_at_set(hired: Employee, actor: User) -> None:
    ev = events.record(
        hired,
        type="salary_change",
        effective=DAY,
        changes={},
        salary=Decimal("3000000"),
        reason="",
        note="",
        by=actor,
    )
    assert ev.proposed is None
    assert ev.applied_at is not None
    assert abs(ev.applied_at - timezone.now()) < timedelta(minutes=1)


def test_dump_load_round_trip(hired: Employee) -> None:
    engineering = macs_writes.save_department("Инженер")
    position = Position.objects.create(name="Ахлах нягтлан")
    new = {
        "department": engineering,
        "position": position,
        "manager": None,
        "emptype": 1,
        "status": JobStatus.ACTIVE.value,
        "contract_start": date(2026, 1, 5),
        "contract_end": None,
    }
    dumped = events._dump_changes(new)
    as_json = json.loads(json.dumps(dumped))
    assert as_json == dumped
    assert as_json["department"] == engineering.pk
    assert as_json["contract_start"] == "2026-01-05"
    assert events._load_changes(as_json) == new


def _write_counts(employee: Employee) -> tuple[int, int, int, int]:
    """Rows a change writes: activity entries, job periods, movements and production snapshots."""
    return (
        ActivityEntry.objects.filter(employee=employee).count(),
        JobRecord.objects.filter(employee=employee).count(),
        Movement.objects.filter(employee=employee).count(),
        EmployeeHistory.objects.count(),
    )


def test_waiting_termination_applies_on_signing(hired: Employee, actor: User) -> None:
    moves_before = Movement.objects.filter(employee=hired).count()
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
    assert ev.applied_at is None
    assert job_at(hired, DAY).status == JobStatus.ACTIVE
    assert Movement.objects.filter(employee=hired).count() == moves_before
    signed = sign_event(ev, by=actor)
    assert signed.applied_at is not None
    assert job_at(hired, DAY).status == JobStatus.LEFT
    assert job_at(hired, DAY - timedelta(days=1)).status == JobStatus.ACTIVE
    assert Movement.objects.filter(employee=hired, kind="out", date=DAY).count() == 1
    assert HrOrder.objects.get(event=ev).order_type == OrderType.FIRED


def test_waiting_rehire_applies_on_signing(hired: Employee, actor: User) -> None:
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
    rehire = events.record(
        hired,
        type="rehire",
        effective=LATER,
        changes={"contract_type": "fixed_term", "contract_start": LATER, "contract_end": date(2027, 3, 1)},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert rehire.applied_at is None
    assert rehire.proposed is not None and rehire.proposed["job"]["emptype"] == 5
    assert job_at(hired, LATER).status == JobStatus.LEFT
    sign_event(rehire, by=actor)
    job = job_at(hired, LATER)
    assert job.status == JobStatus.ACTIVE
    assert job.emptype == 5
    assert job.contract_type == "fixed_term"
    assert job_at(hired, LATER - timedelta(days=1)).status == JobStatus.LEFT


def test_order_refused_leaves_no_event(hired: Employee, actor: User) -> None:
    engineering = macs_writes.save_department("Инженер")
    events.record(
        hired,
        type="transfer",
        effective=DAY,
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
        order_number="7",
        order_date=DAY,
    )
    events_before = Event.objects.count()
    before = _write_counts(hired)
    with pytest.raises(EventError):
        events.record(
            hired,
            type="transfer",
            effective=LATER,
            changes={"department": macs_writes.save_department("Худалдаа")},
            salary=None,
            reason="",
            note="",
            by=actor,
            order_number="7",  # already used this year
            order_date=LATER,
        )
    assert Event.objects.count() == events_before
    assert _write_counts(hired) == before


def test_snapshot_at_signing_carries_new_placement(hired: Employee, actor: User) -> None:
    engineering = macs_writes.save_department("Инженер")
    position = Position.objects.create(name="Ахлах нягтлан")
    ev = events.record(
        hired,
        type="promotion",
        effective=DAY,
        changes={"department": engineering, "position": position},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    sign_event(ev, by=actor)
    history_id = EventProdRow.objects.get(event=ev).history_id
    assert history_id is not None
    snapshot = EmployeeHistory.objects.get(pk=history_id)
    assert snapshot.department_id_value == engineering.pk
    assert snapshot.position_id_value == position.pk


def test_signed_termination_puts_fired_reason_on_employee(hired: Employee, actor: User) -> None:
    reason = named(FiredReason, "Өөрийн хүсэлтээр")
    ev = events.record(
        hired,
        type="termination",
        effective=DAY,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=reason,
    )
    sign_event(ev, by=actor)
    hired.refresh_from_db()
    assert hired.fired_reason_id == reason.pk
    assert hired.died == "no"


def test_signed_death_termination_sets_died_on_employee(hired: Employee, actor: User) -> None:
    died = named(FiredReason, "Нас барсан")
    MeaningfulEntry.objects.create(key=DEATH, value=died.pk)
    ev = events.record(
        hired,
        type="termination",
        effective=DAY,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=died,
    )
    sign_event(ev, by=actor)
    hired.refresh_from_db()
    assert hired.fired_reason_id == died.pk
    assert hired.died == "yes"


def test_cancel_waiting_pension_keeps_pensioner_flag_set_elsewhere(hired: Employee, actor: User) -> None:
    ev = events.record(
        hired,
        type="contract",
        effective=DAY,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        pension=True,
    )
    assert ev.applied_at is None
    ext = ensure_ext(hired)
    ext.is_pensioner = True
    ext.save(update_fields=["is_pensioner"])
    events.cancel(ev, reason="Буруу бүртгэсэн", by=actor)
    assert EmployeeExt.objects.get(employee=hired).is_pensioner is True
