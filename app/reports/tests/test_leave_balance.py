from datetime import date
from typing import Any

import pytest
from accounts.models import User
from employees.models import Employee
from leave.models import GrantKind, LeaveTypeExt
from leave.services import writes
from leave.tests.conftest import annual, make_employee, sick  # noqa: F401 (fixtures)
from macs.models import LeaveTypeRow

from reports.filters import Filters
from reports.leave_balance import REPORT, Line

pytestmark = pytest.mark.django_db

ROW_DAY = date(2026, 6, 1)


def _lines(user: User, f: Filters) -> list[Line]:
    return REPORT.rows(user, f)


def _for(lines: list[Line], employee: Employee, leave_type: LeaveTypeRow) -> Line:
    return next(
        line for line in lines if line.person.employee.pk == employee.pk and line.leave_type.pk == leave_type.pk
    )


def _cells(line: Line) -> dict[str, Any]:
    return {c.key: c.value(line) for c in REPORT.columns}


def test_annual_type_row_carries_the_balance(
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.add_grant(emp, annual, date(2026, 3, 1), date(2027, 2, 28), 15, "", GrantKind.MANUAL, actor)
    writes.record_assign(emp, annual, date(2026, 6, 1), date(2026, 6, 5), 5, "", actor)
    line = _for(_lines(hr_user, Filters(as_of=ROW_DAY)), emp, annual)
    assert line.counts_balance is True
    cells = _cells(line)
    assert (cells["granted"], cells["taken"], cells["left"]) == (15, 5, 10)
    assert cells["note"] is None


def test_other_type_row_shows_days_taken_without_balance(
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.record_assign(emp, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    line = _for(_lines(hr_user, Filters(as_of=ROW_DAY)), emp, sick)
    assert line.counts_balance is False
    assert line.taken == 3
    assert line.granted is None and line.left is None
    assert _cells(line)["note"] == "үлдэгдэл тооцохгүй"


def test_other_type_with_no_leave_has_no_row(
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    lines = _lines(hr_user, Filters(as_of=ROW_DAY))
    assert not [line for line in lines if line.person.employee.pk == emp.pk and line.leave_type.pk == sick.pk]
    assert [line for line in lines if line.person.employee.pk == emp.pk and line.leave_type.pk == annual.pk]


def test_leave_type_filter_limits_rows(
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.record_assign(emp, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    lines = _lines(hr_user, Filters(as_of=ROW_DAY, leave_type=sick.pk))
    assert lines
    assert all(line.leave_type.pk == sick.pk for line in lines)


def test_employee_filter_limits_rows(
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112244")
    writes.record_assign(emp, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    writes.record_assign(other, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    lines = _lines(hr_user, Filters(as_of=ROW_DAY, employee=emp.pk))
    assert lines
    assert {line.person.employee.pk for line in lines} == {emp.pk}


def test_cancelled_sick_leave_is_not_counted(
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    leave = writes.record_assign(emp, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    writes.cancel_assign(leave, writes.snapshot(leave), "Буруу", mistake=False, by=actor)
    lines = _lines(hr_user, Filters(as_of=ROW_DAY))
    assert not [line for line in lines if line.person.employee.pk == emp.pk and line.leave_type.pk == sick.pk]


def test_leave_starting_last_year_is_not_counted_this_year(
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.record_assign(emp, sick, date(2025, 12, 29), date(2026, 1, 3), 3, "", actor)
    lines = _lines(hr_user, Filters(as_of=ROW_DAY))
    assert not [line for line in lines if line.person.employee.pk == emp.pk and line.leave_type.pk == sick.pk]
    writes.record_assign(emp, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    line = _for(_lines(hr_user, Filters(as_of=ROW_DAY)), emp, sick)
    assert line.taken == 3


def test_annual_row_without_period_is_blank_in_c2(
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    line = _for(_lines(hr_user, Filters(as_of=ROW_DAY)), emp, annual)
    cells = _cells(line)
    assert (cells["granted"], cells["taken"], cells["left"]) == (None, None, None)
    assert cells["note"] == "Ажлын жилийн эрх бүртгэгдээгүй"


def test_second_annual_type_filter_keeps_the_pooled_row(
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
) -> None:
    # two annual types exist; picking the second one in «Төрөл» must still return the pooled annual row
    second = LeaveTypeRow.objects.create(name="Нэмэлт ээлжийн амралт")
    LeaveTypeExt.objects.create(leave_type=second, uses_annual_balance=True, is_paid=True)
    emp = make_employee(actor, hired=date(2024, 3, 1))
    lines = _lines(hr_user, Filters(as_of=ROW_DAY, leave_type=second.pk))
    line = _for(lines, emp, annual)
    assert line.counts_balance
    assert all(line.counts_balance for line in lines)
