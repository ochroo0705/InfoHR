"""The team calendar's rules: the month, the department filter, one cell per day and the prev/next months.

The Django view calls `build_calendar`; the API route of Task 6 will call it too, so these tests pin the rules for both.
"""

from datetime import date

import pytest
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from employees.models import Department, Employee, JobRecord, JobStatus
from employees.services import history, macs_writes
from macs.models import LeaveAssign, LeaveTypeRow

from leave.services import records, writes
from leave.services.calendar_page import (
    CalendarCell,
    CalendarLine,
    CalendarPage,
    build_calendar,
    parse_department,
    parse_month,
)
from leave.services.records import Draft
from leave.tests.conftest import make_employee

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]

NOV = date(2026, 11, 1)
PASSWORD = "x-long-pass-123"  # noqa: S105


def _line(page: CalendarPage, employee: Employee) -> CalendarLine:
    return next(line for line in page.lines if line.employee.pk == employee.pk)


def _cells(page: CalendarPage, employee: Employee) -> list[CalendarCell]:
    return _line(page, employee).cells


def test_parse_month_reads_a_valid_month() -> None:
    assert parse_month("2026-02", date(2026, 11, 24)) == date(2026, 2, 1)


def test_parse_month_falls_back_on_junk_and_out_of_range() -> None:
    fallback = date(2026, 11, 24)
    assert parse_month("garbage", fallback) == date(2026, 11, 1)
    assert parse_month("1800-01", fallback) == date(2026, 11, 1)
    assert parse_month("2101-01", fallback) == date(2026, 11, 1)
    assert parse_month(None, fallback) == date(2026, 11, 1)


def test_parse_department_junk_is_none() -> None:
    assert parse_department("abc") is None
    assert parse_department(None) is None
    assert parse_department("7") == 7


def test_annual_leave_is_violet(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    records.record(Draft(employee, annual, date(2026, 11, 2), date(2026, 11, 4)), actor, date(2026, 10, 14))
    cells = _cells(build_calendar(actor, NOV, None), employee)
    assert cells[1].color == "bg-violet-200" and cells[1].leave is not None
    assert cells[1].leave.leave_type.pk == annual.pk


def test_other_counted_leave_is_amber(employee: Employee, sick: LeaveTypeRow, actor: User) -> None:
    records.record(Draft(employee, sick, date(2026, 11, 10), date(2026, 11, 10)), actor, date(2026, 10, 14))
    cells = _cells(build_calendar(actor, NOV, None), employee)
    assert cells[9].color == "bg-amber-200" and cells[9].leave is not None


def test_cancelled_and_rejected_leave_shows_nothing(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    records.record(Draft(employee, annual, date(2026, 11, 16), date(2026, 11, 16)), actor, date(2026, 10, 14))
    records.record(Draft(employee, annual, date(2026, 11, 17), date(2026, 11, 17)), actor, date(2026, 10, 14))
    LeaveAssign.objects.filter(employee=employee, date2=date(2026, 11, 16)).update(status=LeaveAssign.REJECTED)
    LeaveAssign.objects.filter(employee=employee, date2=date(2026, 11, 17)).update(status=LeaveAssign.CANCELLED)
    cells = _cells(build_calendar(actor, NOV, None), employee)
    for i in (15, 16):
        assert cells[i].leave is None and cells[i].color == ""


def test_leave_on_a_holiday_or_weekend_shows_nothing(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    writes.set_holiday_dates(2026, {date(2026, 11, 26): "Тусгаар тогтнолын өдөр"})
    records.record(Draft(employee, annual, date(2026, 11, 25), date(2026, 11, 27)), actor, date(2026, 10, 14))
    cells = _cells(build_calendar(actor, NOV, None), employee)
    holiday = cells[25]  # 26 Nov, a public holiday
    assert holiday.off is True and holiday.leave is None and holiday.color == ""
    assert cells[0].off is True and cells[0].leave is None  # 1 Nov, Sunday
    assert cells[24].color == "bg-violet-200"  # 25 Nov, a working day with leave


def test_long_leave_shows_sky_on_a_working_day(employee: Employee, actor: User) -> None:
    JobRecord.objects.filter(employee=employee).update(status=JobStatus.LONG_LEAVE)
    cells = _cells(build_calendar(actor, NOV, None), employee)
    assert cells[1].long_leave is True and cells[1].color == "bg-sky-200"  # 2 Nov, Monday
    assert cells[0].long_leave is False and cells[0].color == ""  # 1 Nov, Sunday


def test_counted_leave_wins_over_long_leave(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    JobRecord.objects.filter(employee=employee).update(status=JobStatus.LONG_LEAVE)
    records.record(Draft(employee, annual, date(2026, 11, 2), date(2026, 11, 2)), actor, date(2026, 10, 14))
    cells = _cells(build_calendar(actor, NOV, None), employee)
    assert cells[1].color == "bg-violet-200" and cells[1].long_leave is False
    assert cells[2].long_leave is True  # 3 Nov, no counted leave


def test_person_who_left_before_the_month_is_absent(employee: Employee, actor: User) -> None:
    leaver = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112400")
    JobRecord.objects.filter(employee=leaver).update(status=JobStatus.LEFT)
    page = build_calendar(actor, NOV, None)
    assert [line.employee.pk for line in page.lines] == [employee.pk]


def test_department_filter_keeps_a_person_whose_job_on_the_last_day_is_in_it(actor: User) -> None:
    person = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112401")
    dept_a = Department.objects.get(name="Санхүү")
    dept_b = macs_writes.save_department("Бусад")
    history.change_job(
        person,
        effective=date(2026, 11, 15),
        changes={"department": dept_b},
        change_type="correction",
        note="",
        by=actor,
    )
    # Job on 1 Nov is dept A, on 30 Nov is dept B: a filter on B keeps the person, a filter on A keeps them too.
    assert _line(build_calendar(actor, NOV, dept_b.pk), person).employee.pk == person.pk
    assert _line(build_calendar(actor, NOV, dept_a.pk), person).employee.pk == person.pk
    other = macs_writes.save_department("Третэй")
    assert all(line.employee.pk != person.pk for line in build_calendar(actor, NOV, other.pk).lines)


def test_scoped_user_never_gets_another_departments_person(actor: User, employee: Employee) -> None:
    dept_a = Department.objects.get(name="Санхүү")
    dept_b = macs_writes.save_department("Бусад")
    outsider = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112402")
    Employee.objects.filter(pk=outsider.pk).update(department=dept_b)  # the scope reads this column
    JobRecord.objects.filter(employee=outsider).update(department=dept_b)

    scoped = User.objects.create_user("scoped_cal_page", password=PASSWORD)
    scoped.groups.add(Group.objects.get(name="HR"))
    AccessScope.objects.create(user=scoped, limited=True, department_ids=[dept_a.pk])

    page = build_calendar(scoped, NOV, dept_b.pk)
    assert all(line.employee.pk != outsider.pk for line in page.lines)
    assert all(line.employee.pk != employee.pk for line in page.lines)  # the filter on B also drops A's person


def test_prev_and_next_are_blank_at_the_edges(actor: User) -> None:
    assert build_calendar(actor, date(1900, 1, 1), None).prev == ""
    assert build_calendar(actor, date(2100, 12, 1), None).next == ""
    assert build_calendar(actor, date(1901, 1, 1), None).prev == "1900-12"
    assert build_calendar(actor, date(2099, 12, 1), None).next == "2100-01"


def test_february_length_follows_the_leap_year(actor: User) -> None:
    assert len(build_calendar(actor, date(2028, 2, 1), None).days) == 29
    assert len(build_calendar(actor, date(2027, 2, 1), None).days) == 28


def test_page_carries_the_month_days_and_holidays(actor: User) -> None:
    writes.set_holiday_dates(2026, {date(2026, 11, 26): "Тусгаар тогтнолын өдөр"})
    page = build_calendar(actor, NOV, None)
    assert page.first == NOV and len(page.days) == 30
    assert page.holidays == {date(2026, 11, 26)}
    assert (page.prev, page.next) == ("2026-10", "2026-12")


def test_query_count_is_the_same_for_3_and_8_people(actor: User) -> None:
    for n in range(3):
        make_employee(actor, hired=date(2024, 3, 1), register_no=f"УБ99112{420 + n}")
    # Warm-up: the first call fills the user's per-day scope cache; later calls skip that query.
    build_calendar(actor, NOV, None)
    with CaptureQueriesContext(connection) as small:
        page = build_calendar(actor, NOV, None)
    assert len(page.lines) == 3
    for n in range(5):
        make_employee(actor, hired=date(2024, 3, 1), register_no=f"УБ99112{430 + n}")
    with CaptureQueriesContext(connection) as large:
        page = build_calendar(actor, NOV, None)
    assert len(page.lines) == 8
    assert len(large.captured_queries) == len(small.captured_queries)
