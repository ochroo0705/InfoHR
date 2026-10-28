from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.utils import timezone
from employees.models import Department, ensure_ext
from leave.services import writes
from leave.tests.conftest import annual, make_employee, sick  # noqa: F401 (fixtures)
from macs.models import LeaveTypeRow

from reports.filters import Filters
from reports.leave_requests import REPORT, Line
from reports.tests.conftest import _make_user, transfer

pytestmark = pytest.mark.django_db

YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)


def _lines(user: User, f: Filters) -> list[Line]:
    return REPORT.rows(user, f)


def _year(**values: Any) -> Filters:
    return Filters(date_from=YEAR_START, date_to=YEAR_END, **values)


def _cells(line: Line) -> dict[str, Any]:
    return {c.key: c.value(line) for c in REPORT.columns}


def test_default_period_is_this_year_and_overlap_counts(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    year = timezone.localdate().year
    emp = make_employee(actor, hired=date(2024, 3, 1))
    straddle = writes.record_assign(emp, sick, date(year - 1, 12, 29), date(year, 1, 3), 3, "", actor)
    # no dates given: the default period is the current calendar year
    assert [line.leave.id for line in _lines(hr_user, Filters())] == [straddle.pk]
    # explicit dates: the same row, as the period starts inside the leave
    lines = _lines(hr_user, Filters(date_from=date(year, 1, 1), date_to=date(year, 12, 31)))
    assert [line.leave.id for line in lines] == [straddle.pk]


def test_leaves_outside_the_period_are_not_listed(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.record_assign(emp, sick, date(2025, 11, 1), date(2025, 11, 5), 3, "", actor)
    writes.record_assign(emp, sick, date(2025, 12, 31), date(2025, 12, 31), 1, "", actor)
    assert _lines(hr_user, _year()) == []


def test_every_state_is_shown_by_default_and_the_filter_narrows(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    recorded = writes.record_assign(emp, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    cancelled = writes.record_assign(emp, sick, date(2026, 4, 6), date(2026, 4, 8), 3, "", actor)
    writes.cancel_assign(cancelled, writes.snapshot(cancelled), "Цуцалсан", mistake=False, by=actor)
    mistake = writes.record_assign(emp, sick, date(2026, 5, 4), date(2026, 5, 6), 3, "", actor)
    writes.cancel_assign(mistake, writes.snapshot(mistake), "Алдаа", mistake=True, by=actor)

    everything = _lines(hr_user, _year())
    assert {line.leave.id for line in everything} == {recorded.pk, cancelled.pk, mistake.pk}
    assert {line.leave.state.value for line in everything} == {"Бүртгэсэн", "Цуцалсан", "Буруу бүртгэсэн"}

    only_cancelled = _lines(hr_user, _year(leave_state="cancelled"))
    assert [line.leave.id for line in only_cancelled] == [cancelled.pk]


def test_old_program_row_is_marked(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.write_old_style_assign(emp, sick, date(2026, 2, 2), date(2026, 2, 4), status=None, adays=None, comment="")
    (line,) = _lines(hr_user, _year())
    assert line.leave.from_old_system is True
    assert _cells(line)["source"] == "Хуучин програм"


def test_info_hr_row_is_marked_as_such(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.record_assign(emp, sick, date(2026, 2, 2), date(2026, 2, 4), 3, "", actor)
    (line,) = _lines(hr_user, _year())
    assert _cells(line)["source"] == "Info HR"


def test_leave_type_filter(
    hr_user: User,
    actor: User,
    annual: LeaveTypeRow,  # noqa: F811
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    sick_leave = writes.record_assign(emp, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    writes.record_assign(emp, annual, date(2026, 6, 1), date(2026, 6, 5), 5, "", actor)
    (line,) = _lines(hr_user, _year(leave_type=sick.pk))
    assert line.leave.id == sick_leave.pk
    assert line.leave.leave_type.pk == sick.pk


def test_department_filter_uses_todays_department(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.record_assign(emp, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    # moved before today: today's department is the new one, so the row shows it and the old filter finds nothing
    transfer(emp, "Маркетинг", date(2026, 1, 1), actor)
    (line,) = _lines(hr_user, _year())
    assert _cells(line)["department"] == "Маркетинг"
    marketing = Department.objects.get(name="Маркетинг")
    assert [x.person.employee.pk for x in _lines(hr_user, _year(department=marketing.pk))] == [emp.pk]
    accounts = Department.objects.get(name="Санхүү")
    assert _lines(hr_user, _year(department=accounts.pk)) == []
    assert _lines(hr_user, _year(department=999999)) == []


def test_only_visible_people_appear(
    hr_user: User,
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    mine = make_employee(actor, hired=date(2024, 3, 1))
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112255")
    writes.record_assign(mine, sick, date(2026, 3, 2), date(2026, 3, 4), 3, "", actor)
    writes.record_assign(other, sick, date(2026, 3, 9), date(2026, 3, 11), 3, "", actor)
    # an Employee-role user sees only the employee record linked to their login
    own_user = _make_user("Employee", "leave-requests-self")
    ext = ensure_ext(mine)
    ext.user = own_user
    ext.save()
    lines = _lines(own_user, _year())
    assert {line.person.employee.pk for line in lines} == {mine.pk}
