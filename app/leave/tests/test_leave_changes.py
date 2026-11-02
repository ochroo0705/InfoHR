"""Structured old and new values in the activity log for leave records and balance adjustments (audit-logs task 12)."""

from datetime import date

import pytest
from accounts.models import User
from django.template.loader import render_to_string
from employees.models import ActivityEntry, ActivityKind, Employee
from macs.models import Entitlement, LeaveAssign, LeaveTypeRow

from leave.services import ledger, records, writes
from leave.services.records import Draft

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: TODAY)


def _latest(employee: Employee) -> ActivityEntry:
    return ActivityEntry.objects.filter(employee=employee).latest("id")


def _draft(employee: Employee, leave_type: LeaveTypeRow, start: date, end: date, **kw: object) -> Draft:
    return Draft(employee=employee, leave_type=leave_type, start_date=start, end_date=end, **kw)  # type: ignore[arg-type]


def test_record_logs_type_dates_and_days_as_new(
    employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None
) -> None:
    records.record(_draft(employee, annual, date(2026, 11, 2), date(2026, 11, 13)), actor, TODAY)
    entry = _latest(employee)
    assert entry.kind == ActivityKind.CHANGED and entry.personal is False and entry.sensitive is False
    assert entry.changes == [
        {"field": "Амралтын төрөл", "old": "", "new": str(annual)},
        {"field": "Эхлэх огноо", "old": "", "new": "2026-11-02"},
        {"field": "Дуусах огноо", "old": "", "new": "2026-11-13"},
        {"field": "Хоног", "old": "", "new": "10"},
    ]
    assert entry.message.startswith("Чөлөө бүртгэсэн: ")


def test_edit_logs_only_changed_fields_with_old_and_new(
    employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None
) -> None:
    leave = records.record(_draft(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor, TODAY)
    records.update(
        leave,
        _draft(employee, annual, date(2026, 11, 2), date(2026, 11, 4), loaded=writes.snapshot(leave)),
        actor,
        TODAY,
    )
    entry = _latest(employee)
    assert entry.message.startswith("Чөлөө засварласан: ")
    assert entry.personal is False and entry.sensitive is False
    assert entry.changes == [
        {"field": "Дуусах огноо", "old": "2026-11-06", "new": "2026-11-04"},
        {"field": "Хоног", "old": "5", "new": "3"},
    ]
    assert LeaveAssign.objects.get(pk=leave.pk).adays == 3


def test_cancel_logs_one_status_change(employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None) -> None:
    leave = records.record(_draft(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor, TODAY)
    records.cancel(leave, writes.snapshot(leave), "Шалтгаан", actor, TODAY)
    entry = _latest(employee)
    assert entry.personal is False and entry.sensitive is False
    assert entry.changes == [{"field": "Төлөв", "old": "Бүртгэсэн", "new": "Цуцалсан"}]


def test_balance_adjustment_logs_the_entered_days(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    Entitlement.objects.create(
        employee=employee,
        leave_type=annual,
        date1=date(2025, 3, 1),
        date2=date(2026, 2, 28),
        ent_days=15,
        comment="",
    )
    ledger.adjust(employee, date(2025, 3, 1), date(2026, 2, 28), -2, "Өмнө авсан", actor)
    entry = _latest(employee)
    assert entry.message.startswith("Амралтын эрх засварласан")
    assert entry.personal is False and entry.sensitive is False
    assert entry.changes == [{"field": "Засварласан хоног", "old": "", "new": "-2"}]


def _header(entry: ActivityEntry) -> str:
    return render_to_string("employees/_activity_latest.html", {"latest_activity": entry, "today": TODAY})


def test_header_shows_the_message_for_leave_writes(
    employee: Employee, annual: LeaveTypeRow, actor: User, grants_on: None
) -> None:
    leave = records.record(_draft(employee, annual, date(2026, 11, 2), date(2026, 11, 6)), actor, TODAY)
    recorded = _latest(employee)
    assert recorded.header_change is None
    assert recorded.message[:50] in _header(recorded)
    records.cancel(leave, writes.snapshot(leave), "Шалтгаан", actor, TODAY)
    cancelled = _latest(employee)
    assert cancelled.header_change is None
    assert cancelled.message[:50] in _header(cancelled)


def test_header_shows_the_message_for_a_balance_adjustment(
    employee: Employee, annual: LeaveTypeRow, actor: User
) -> None:
    Entitlement.objects.create(
        employee=employee, leave_type=annual, date1=date(2025, 3, 1), date2=date(2026, 2, 28), ent_days=15, comment=""
    )
    ledger.adjust(employee, date(2025, 3, 1), date(2026, 2, 28), -2, "Өмнө авсан", actor)
    entry = _latest(employee)
    assert entry.header_change is None
    assert entry.message[:50] in _header(entry)
