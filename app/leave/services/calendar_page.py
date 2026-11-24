"""The team calendar's rules: the month, the department filter, one cell per day and the prev/next months.

The Django view and the API both call this module. Rules only; drawing is the caller's job. The caller passes the first
day of the month: nothing here reads the clock.
"""

import calendar as pycal
from dataclasses import dataclass, field
from datetime import date, timedelta

from accounts.models import User
from employees import access as employee_access
from employees import listing
from employees.models import Employee, JobStatus

from leave.services import calendar, rows
from leave.services.list_page import parse_id
from leave.services.rows import LeaveRow

MIN_YEAR, MAX_YEAR = 1900, 2100

ANNUAL_COLOR = "bg-violet-200"  # counted leave of a type that uses the annual balance
OTHER_COLOR = "bg-amber-200"  # any other counted leave
# Long leave (maternity and the like) is sky, the same colour as the «Урт чөлөөтэй» state chip (employees/_state.html).
LONG_LEAVE_COLOR = "bg-sky-200"


@dataclass
class CalendarCell:
    day: date
    off: bool
    leave: LeaveRow | None
    color: str = ""
    long_leave: bool = False  # on «Урт чөлөөтэй» (job status), with no counted leave that day and a working day


@dataclass
class CalendarLine:
    employee: Employee
    cells: list[CalendarCell]


@dataclass
class CalendarPage:
    first: date  # the first day of the month
    days: list[date]
    holidays: set[date]
    lines: list[CalendarLine]
    prev: str  # YYYY-MM, or "" at the 1900 edge
    next: str  # YYYY-MM, or "" at the 2100 edge
    off: set[date] = field(default_factory=set)  # the days that are not working days (weekends and holidays)


def parse_month(value: str | None, fallback: date) -> date:
    """The first day of the month named by `YYYY-MM`; junk or a year outside 1900..2100 gives the fallback's month."""
    try:
        y, m = (int(x) for x in (value or "").split("-"))
        if not MIN_YEAR <= y <= MAX_YEAR:
            raise ValueError
        return date(y, m, 1)
    except ValueError:
        return fallback.replace(day=1)


def parse_department(value: str | None) -> int | None:
    """A department id from user input, or None when the input is junk."""
    return parse_id(value)


def _color(lv: LeaveRow) -> str:
    """Annual leave is violet; every other counted leave is amber (one colour per kind the screen can tell apart)."""
    return ANNUAL_COLOR if lv.type_ext.uses_annual_balance else OTHER_COLOR


def build_calendar(user: User, first: date, department: int | None) -> CalendarPage:
    """The month that starts on `first`: every visible person whose job on its first or last day is not «left»
    (and, with `department`, is in that department), with one cell per day."""
    last = first.replace(day=pycal.monthrange(first.year, first.month)[1])
    days = [first.replace(day=n) for n in range(1, last.day + 1)]
    holidays = calendar.holidays_between(first, last)
    people = list(employee_access.visible_employees(user).prefetch_related("job_records"))
    counted: dict[int, list[LeaveRow]] = {}
    for lv in rows.leaves(employee_ids=[e.pk for e in people], start=first, end=last):
        if lv.counts:
            counted.setdefault(lv.employee_id, []).append(lv)
    lines = []
    for e in people:
        jobs = [listing.prefetched_job_on(e, first), listing.prefetched_job_on(e, last)]
        if all(j is None or j.status == JobStatus.LEFT for j in jobs):
            continue
        if department is not None and not any(j and j.department_id == department for j in jobs):
            continue
        mine = counted.get(e.pk, [])
        cells = []
        for d in days:
            hit = next((lv for lv in mine if lv.start <= d <= lv.end), None)
            off = not calendar.is_working_day(d, holidays)
            color = _color(hit) if hit and not off else ""
            # Counted leave wins; long leave shows only on a working day with no counted leave (in memory, no query).
            long = (
                not off
                and hit is None
                and (job := listing.prefetched_job_on(e, d)) is not None
                and job.status == JobStatus.LONG_LEAVE
            )
            if long:
                color = LONG_LEAVE_COLOR
            cells.append(CalendarCell(d, off, hit if not off else None, color, long_leave=long))
        lines.append(CalendarLine(e, cells))
    prev_m = (first - timedelta(days=1)).strftime("%Y-%m") if first.year > MIN_YEAR else ""
    next_m = (last + timedelta(days=1)).strftime("%Y-%m") if last.year < MAX_YEAR else ""
    off_days = {d for d in days if not calendar.is_working_day(d, holidays)}
    return CalendarPage(first, days, holidays, lines, prev_m, next_m, off_days)
