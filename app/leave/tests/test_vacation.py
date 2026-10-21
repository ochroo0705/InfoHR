"""emp_vacation: one total row per employee per year for annual leave (Q-13; user 2026-10-19: one total per year)."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.db import connection
from macs.models import Employee, LeaveAssign, LeaveTypeRow

from leave.services import writes

pytestmark = pytest.mark.django_db


def _rows(employee: Employee) -> list[tuple[Any, ...]]:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT myear, mmonth, v_day, is_vacation, start_date::date, end_date::date, dep_ident, xmonth"
            " FROM emp_vacation WHERE emp_ident = %s ORDER BY myear, mmonth",
            [employee.pk],
        )
        return list(cur.fetchall())


def test_record_annual_writes_year_row(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    writes.record_assign(employee, annual, date(2026, 2, 17), date(2026, 2, 19), 3, "", actor)
    dep = Employee.objects.get(pk=employee.pk).department_id
    assert _rows(employee) == [(2026, 2, 3, "yes", date(2026, 2, 17), date(2026, 2, 19), dep, 0)]


def test_existing_empty_row_updated_not_duplicated(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    with connection.cursor() as cur:  # what the old INSERT_VACATION procedure left behind
        cur.execute(
            "INSERT INTO emp_vacation (emp_ident, dep_ident, xmonth, myear, mmonth) VALUES (%s, NULL, 0, 2026, 1)",
            [employee.pk],
        )
    writes.record_assign(employee, annual, date(2026, 7, 13), date(2026, 7, 17), 5, "", actor)
    rows = _rows(employee)
    assert len(rows) == 1
    assert rows[0][:6] == (2026, 7, 5, "yes", date(2026, 7, 13), date(2026, 7, 17))


def test_split_leave_is_one_total(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    writes.record_assign(employee, annual, date(2026, 12, 7), date(2026, 12, 11), 5, "", actor)
    writes.record_assign(employee, annual, date(2026, 2, 17), date(2026, 2, 19), 3, "", actor)
    assert [r[:6] for r in _rows(employee)] == [(2026, 2, 8, "yes", date(2026, 2, 17), date(2026, 12, 11))]


def test_cancel_last_leave_resets_row(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = writes.record_assign(employee, annual, date(2026, 2, 17), date(2026, 2, 19), 3, "", actor)
    writes.cancel_assign(a, writes.snapshot(a), "буруу", mistake=False, by=actor)
    assert [r[:6] for r in _rows(employee)] == [(2026, 2, 0, "no", None, None)]


def test_non_annual_type_writes_nothing(employee: Employee, actor: User) -> None:
    sick = LeaveTypeRow.objects.create(name="Өвчний чөлөө")
    writes.record_assign(employee, sick, date(2026, 2, 17), date(2026, 2, 19), 3, "", actor)
    assert _rows(employee) == []


def test_move_to_next_year_updates_both(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = writes.record_assign(employee, annual, date(2026, 12, 7), date(2026, 12, 11), 5, "", actor)
    writes.update_assign(
        a,
        writes.snapshot(a),
        leave_type=annual,
        start=date(2027, 1, 11),
        end=date(2027, 1, 15),
        days=5,
        comment="",
        by=actor,
    )
    assert [r[:6] for r in _rows(employee)] == [
        (2026, 12, 0, "no", None, None),
        (2027, 1, 5, "yes", date(2027, 1, 11), date(2027, 1, 15)),
    ]


def test_old_program_row_counts_in_total(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    LeaveAssign.objects.create(  # old program: no ext row, no day count, no status
        employee=employee, leave_type=annual, date1=date(2026, 3, 2), date2=date(2026, 3, 3), status=None, adays=None
    )
    writes.record_assign(employee, annual, date(2026, 2, 17), date(2026, 2, 19), 3, "", actor)
    assert [r[:6] for r in _rows(employee)] == [(2026, 2, 5, "yes", date(2026, 2, 17), date(2026, 3, 3))]
