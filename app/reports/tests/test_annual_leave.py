import re
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee
from leave.models import GrantKind
from leave.services import ledger, writes
from leave.tests.conftest import annual, make_employee  # noqa: F401 (fixtures)
from macs.models import LeaveTypeRow

from reports.annual_leave import REPORT, Line
from reports.filters import Filters

pytestmark = pytest.mark.django_db

ROW_DAY = date(2026, 6, 1)


def _grant(employee: Employee, leave_type: LeaveTypeRow, start: date, end: date, days: int, by: User) -> None:
    writes.add_grant(employee, leave_type, start, end, days, "", GrantKind.MANUAL, by)


def _line(lines: list[Line], employee: Employee) -> Line:
    return next(line for line in lines if line.person.employee.pk == employee.pk)


def _cells(line: Line) -> dict[str, Any]:
    return {c.key: c.value(line) for c in REPORT.columns}


def test_row_shows_granted_taken_left_for_the_work_year(
    client: Client,
    login_as: Any,
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    _grant(emp, annual, date(2026, 3, 1), date(2027, 2, 28), 15, actor)
    writes.record_assign(emp, annual, date(2026, 6, 1), date(2026, 6, 5), 5, "", actor)
    line = _line(REPORT.rows(hr_user, Filters(as_of=ROW_DAY)), emp)
    assert line.period is not None
    assert (line.period.granted, line.period.taken, line.period.left) == (15, 5, 10)
    cells = _cells(line)
    assert (cells["granted"], cells["taken"], cells["left"]) == (15, 5, 10)
    assert cells["start"] == date(2026, 3, 1) and cells["end"] == date(2027, 2, 28)
    login_as(client, "HR")
    page = client.get("/reports/annual-leave/?as_of=2026-06-01").content.decode()
    assert "Үлдэгдэл" in page


def test_period_is_chosen_by_the_as_of_date(hr_user: User, actor: User, annual: LeaveTypeRow) -> None:  # noqa: F811
    emp = make_employee(actor, hired=date(2024, 3, 1))
    _grant(emp, annual, date(2025, 3, 1), date(2026, 2, 28), 14, actor)
    _grant(emp, annual, date(2026, 3, 1), date(2027, 2, 28), 15, actor)
    older = _line(REPORT.rows(hr_user, Filters(as_of=date(2025, 6, 1))), emp)
    current = _line(REPORT.rows(hr_user, Filters(as_of=ROW_DAY)), emp)
    assert older.period is not None and current.period is not None
    assert (older.period.start, older.period.granted) == (date(2025, 3, 1), 14)
    assert (current.period.start, current.period.granted) == (date(2026, 3, 1), 15)


def test_person_without_period_gets_blank_numbers(hr_user: User, actor: User, annual: LeaveTypeRow) -> None:  # noqa: F811
    emp = make_employee(actor, hired=date(2024, 3, 1))
    line = _line(REPORT.rows(hr_user, Filters(as_of=ROW_DAY)), emp)
    assert line.period is None
    cells = _cells(line)
    assert cells["granted"] is None and cells["taken"] is None and cells["left"] is None
    assert cells["note"] == "Ажлын жилийн эрх бүртгэгдээгүй"


def test_cancelled_leave_is_not_taken(hr_user: User, actor: User, annual: LeaveTypeRow) -> None:  # noqa: F811
    emp = make_employee(actor, hired=date(2024, 3, 1))
    _grant(emp, annual, date(2026, 3, 1), date(2027, 2, 28), 15, actor)
    leave = writes.record_assign(emp, annual, date(2026, 6, 1), date(2026, 6, 5), 5, "", actor)
    writes.cancel_assign(leave, writes.snapshot(leave), "Буруу", mistake=False, by=actor)
    line = _line(REPORT.rows(hr_user, Filters(as_of=ROW_DAY)), emp)
    assert line.period is not None
    assert (line.period.taken, line.period.left) == (0, 15)


def test_left_employee_is_not_listed(hr_user: User, left_employee: Employee, annual: LeaveTypeRow) -> None:  # noqa: F811
    before = [line.person.employee.pk for line in REPORT.rows(hr_user, Filters(as_of=date(2026, 2, 1)))]
    after = [line.person.employee.pk for line in REPORT.rows(hr_user, Filters(as_of=date(2026, 4, 1)))]
    assert left_employee.pk in before
    assert left_employee.pk not in after


def test_accountant_may_open_but_employee_role_is_refused(client: Client, login_as: Any) -> None:
    login_as(client, "Accountant")
    assert client.get("/reports/annual-leave/").status_code == 200
    client.logout()
    login_as(client, "Employee", "own")
    assert client.get("/reports/annual-leave/").status_code == 403


def test_matches_the_balances_page(
    client: Client,
    login_as: Any,
    monkeypatch: pytest.MonkeyPatch,
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    _grant(emp, annual, date(2026, 3, 1), date(2027, 2, 28), 17, actor)
    writes.record_assign(emp, annual, date(2026, 6, 1), date(2026, 6, 5), 3, "", actor)
    monkeypatch.setattr("leave.views.today", lambda: ROW_DAY)
    line = _line(REPORT.rows(hr_user, Filters(as_of=ROW_DAY)), emp)
    assert line.period is not None
    assert line.period.left == 14
    login_as(client, "HR")
    page = client.get("/leave/balances/").content.decode()
    # the balances row of this employee: the one <tr> block that names them; its last cell is Үлдэгдэл
    row = next(block for block in page.split("<tr") if emp.full_name in block)
    balance_cell = re.findall(r'<span class="[^"]*">(-?\d+)</span></td>', row)
    assert balance_cell and int(balance_cell[-1]) == line.period.left


def test_no_annual_type_configured_says_so_in_the_note(hr_user: User, actor: User) -> None:
    # no leave type uses the annual balance: the row's note is the ledger's, not the missing-period text
    emp = make_employee(actor, hired=date(2024, 3, 1))
    line = _line(REPORT.rows(hr_user, Filters(as_of=ROW_DAY)), emp)
    assert _cells(line)["note"] == ledger.NOT_CONFIGURED
