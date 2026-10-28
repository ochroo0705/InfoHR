"""Readers of Event rows must ignore a change that waits for its signed order (signed-order plan, Task 7a).

A waiting change has written no job, salary or MACS rows, so every reader that looks at Event rows by date or type
must use `applied()`. Scheduled-change lists (attention) are not for waiting changes either: they show nothing for
them here. The header's "next change" link does count a future waiting change (task 8b), see the test below."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.utils import timezone
from leave.services import entitlement as leave_entitlement
from macs.models import ContactRow, ContactType, FiredReason

from employees import attention
from employees.listing import employee_rows, row_for
from employees.models import Employee, JobRecord, JobStatus
from employees.services import events, history, macs_writes
from employees.tests.conftest import named, set_ext
from employees.tests.helpers import record_signed
from employees.views import _next_event, change_rows, order_rows

pytestmark = pytest.mark.django_db

REASON = "Өөрийн хүсэлтээр"


@pytest.fixture
def today() -> date:
    return timezone.localdate()


@pytest.fixture
def emp(hired: Employee) -> Employee:
    """Quiet employee for the attention box: setup done, emergency contact present, no pending order reminder."""
    set_ext(hired, setup_required=False)
    ContactRow.objects.filter(employee=hired).delete()
    ContactRow.objects.create(
        employee=hired, contact_type=named(ContactType, "Утас"), name="А", relative="Ах", value="99"
    )
    hired.hr_orders.update(state="registered")
    return hired


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("hr_reader", password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name="HR"))
    return user


def _attention_texts(user: User, today: date) -> list[str]:
    rows = employee_rows(Employee.objects.all(), today)
    return [a.text for a in attention.items(user, rows, today)]


def _waiting_termination(emp: Employee, actor: User, effective: date) -> None:
    ev = events.record(
        emp,
        type="termination",
        effective=effective,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, REASON),
    )
    assert ev.applied_at is None


@pytest.mark.parametrize("offset", [-3, 5])
def test_waiting_termination_keeps_employee_active_and_macs_row(
    emp: Employee, actor: User, today: date, offset: int
) -> None:
    _waiting_termination(emp, actor, today + timedelta(days=offset))
    emp.refresh_from_db()
    row = row_for(emp, today)
    assert row.state == "active"
    job = history.job_on(emp, today)
    assert job is not None and job.status == JobStatus.ACTIVE
    # The waiting termination is in the event table, but _flags must not see it: a left job would pick it up.
    left_view = JobRecord(employee=emp, status=JobStatus.LEFT)
    assert macs_writes._flags(emp, left_view, today) == {
        "taken_leave": 0,
        "leave_type": None,
        "fired_reason_id": None,
        "died": "no",
    }
    assert macs_writes.sync_current(emp, today) is False
    emp.refresh_from_db()
    assert emp.fired_reason_id is None
    assert emp.died == "no"


def test_applied_past_termination_is_seen_by_flags(emp: Employee, actor: User, today: date) -> None:
    """Control: the same reader does pick up a signed termination, so the test above is not vacuous."""
    record_signed(
        emp,
        type="termination",
        effective=today - timedelta(days=3),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, REASON),
    )
    left_view = JobRecord(employee=emp, status=JobStatus.LEFT)
    flags = macs_writes._flags(emp, left_view, today)
    assert flags["fired_reason_id"] is not None


def test_waiting_future_transfer_not_in_scheduled_attention(
    emp: Employee, actor: User, hr_user: User, today: date
) -> None:
    engineering = macs_writes.save_department("Инженер")
    ev = events.record(
        emp,
        type="transfer",
        effective=today + timedelta(days=7),
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert ev.applied_at is None
    assert not [t for t in _attention_texts(hr_user, today) if t.startswith("Төлөвлөсөн")]


def test_applied_future_transfer_is_in_scheduled_attention(
    emp: Employee, actor: User, hr_user: User, today: date
) -> None:
    engineering = macs_writes.save_department("Инженер")
    ev = record_signed(
        emp,
        type="transfer",
        effective=today + timedelta(days=7),
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert ev.applied_at is not None
    expected = f"Төлөвлөсөн: {ev.get_type_display()} {ev.effective:%Y-%m-%d}"
    assert expected in _attention_texts(hr_user, today)


def test_waiting_future_transfer_is_the_next_change(emp: Employee, actor: User, today: date) -> None:
    engineering = macs_writes.save_department("Инженер")
    events.record(
        emp,
        type="transfer",
        effective=today + timedelta(days=7),
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    nxt = _next_event(emp, True, today)
    assert nxt is not None and nxt.applied_at is None


def test_waiting_rehire_does_not_count_as_rehire(emp: Employee, actor: User) -> None:
    """Leave entitlement start and the production start date ignore a rehire that waits for its order."""
    record_signed(
        emp,
        type="termination",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, REASON),
    )
    rehire = events.record(
        emp,
        type="rehire",
        effective=date(2026, 5, 1),
        changes={"position": macs_writes.save_position("Программист")},
        salary=Decimal("3100000"),
        reason="",
        note="",
        by=actor,
    )
    assert rehire.applied_at is None
    assert leave_entitlement.employment_start(emp) == emp.first_hire_date
    assert macs_writes.hr_employment_start(emp) == date(2026, 1, 5)


def test_work_tab_history_has_no_row_for_waiting_change(emp: Employee, actor: User, today: date) -> None:
    engineering = macs_writes.save_department("Инженер")
    waiting = events.record(
        emp,
        type="transfer",
        effective=today - timedelta(days=2),
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert waiting.applied_at is None
    jobs = list(emp.job_records.select_related("position", "department", "manager", "event").order_by("-period"))
    rows, _ = change_rows(jobs, order_rows(emp))
    assert not [r for r in rows if getattr(r, "event", None) is not None and r.event.pk == waiting.pk]
    assert len(rows) == len(jobs)  # only the hire: the waiting change has no history row


def test_signed_change_has_its_work_tab_row(emp: Employee, actor: User, today: date) -> None:
    """Control for the test above: once signed, the same change does get a history row."""
    engineering = macs_writes.save_department("Инженер")
    signed = record_signed(
        emp,
        type="transfer",
        effective=today - timedelta(days=2),
        changes={"department": engineering},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert signed.applied_at is not None
    jobs = list(emp.job_records.select_related("position", "department", "manager", "event").order_by("-period"))
    rows, _ = change_rows(jobs, order_rows(emp))
    assert [r for r in rows if getattr(r, "event", None) is not None and r.event.pk == signed.pk]
