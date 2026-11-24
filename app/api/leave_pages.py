"""Leave pages API under /api/v1/leave: the balances page and the team calendar as the React pages read them.

GET /leave/balances (one batch of the people's current leave periods) and GET /leave/calendar (one month: the day
header, one cell per person per day, the prev and next months, the department choices). The rules come from
leave.services.balance_page and leave.services.calendar_page; this module reads the request and presents the answer.
Rights: leave.view_leave (403 "forbidden" otherwise); every route needs a signed-in session (401 without one). Both
answer Cache-Control no-store: they carry people's leave data.
"""

from datetime import date

from accounts.models import User
from config import batching
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from employees.models import Department
from leave import access
from leave.services.balance_page import balance_batch
from leave.services.calendar_page import (
    ANNUAL_COLOR,
    LONG_LEAVE_COLOR,
    OTHER_COLOR,
    CalendarCell,
    CalendarPage,
    build_calendar,
    parse_department,
    parse_month,
)
from leave.services.list_page import not_configured_text
from ninja import Router, Schema
from ninja.security import django_auth

from api.errors import ApiError
from api.leave import LeaveChoiceOut
from api.params import batch_offset
from api.popups import FORBIDDEN, request_user

leave_pages_router = Router(tags=["leave"])

BALANCE_EMPTY_TEXT = "Ажилтан алга"  # the balances table's text when no row matches (_balance_rows.html)
LONG_LEAVE_TITLE = "Урт чөлөө"  # the title of a long-leave cell (calendar.html)
KIND_BY_COLOR = {ANNUAL_COLOR: "annual", OTHER_COLOR: "other", LONG_LEAVE_COLOR: "long"}  # the service picks the colour


class LeaveBalancePeriodOut(Schema):
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    granted: int
    taken: int
    left: int


class LeaveBalanceRowOut(Schema):
    employee_id: int
    employee_name: str  # «<family> <given>»
    waiting: str | None  # YYYY-MM-DD: the day the right starts, only while it has not started yet
    period: LeaveBalancePeriodOut | None  # the current period; None when the person has no grant in it


class LeaveBalanceListOut(Schema):
    today: str  # YYYY-MM-DD: the day the balances are shown for
    rows: list[LeaveBalanceRowOut]
    next_offset: int | None  # the offset of the next batch; None when this is the last one
    not_configured: str  # «» when the annual leave type is set
    can_settings: bool  # the user may manage leave settings (the «Тохируулах» link)
    empty_text: str


class LeaveCalendarDayOut(Schema):
    date: str  # YYYY-MM-DD
    day: int
    off: bool  # a Saturday, a Sunday or a public holiday
    holiday: bool
    today: bool


class LeaveCalendarCellOut(Schema):
    kind: str  # annual, other, long, or «» (no leave, or an off day)
    leave_type_id: int | None  # the counted leave's type; None for long leave and an empty cell
    title: str  # the leave type's name, «Урт чөлөө» for long leave, else «»


class LeaveCalendarLineOut(Schema):
    employee_id: int
    employee_name: str
    cells: list[LeaveCalendarCellOut]  # one per day, in the order of `days`


class LeaveCalendarOut(Schema):
    month: str  # YYYY-MM
    title: str  # «Багийн хуанли — YYYY-MM»
    days: list[LeaveCalendarDayOut]
    lines: list[LeaveCalendarLineOut]
    prev: str  # YYYY-MM, or «» at the 1900 edge
    next: str  # YYYY-MM, or «» at the 2100 edge
    this_month: str  # YYYY-MM when the shown month is not the current one, else «»
    departments: list[LeaveChoiceOut]
    department: int | None  # the department filter as sent; None when none or junk
    not_configured: str
    can_settings: bool


def _viewer(request: HttpRequest) -> User:
    user = request_user(request)
    if not access.can_view(user):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return user


def _cell_out(cell: CalendarCell) -> LeaveCalendarCellOut:
    """The cell's kind from the colour the service chose; an off day has no colour, so it has no kind."""
    if cell.off:
        return LeaveCalendarCellOut(kind="", leave_type_id=None, title="")
    kind = KIND_BY_COLOR.get(cell.color, "")
    if kind == "long":
        return LeaveCalendarCellOut(kind=kind, leave_type_id=None, title=LONG_LEAVE_TITLE)
    if kind and cell.leave is not None:
        return LeaveCalendarCellOut(kind=kind, leave_type_id=cell.leave.leave_type.pk, title=str(cell.leave.leave_type))
    return LeaveCalendarCellOut(kind="", leave_type_id=None, title="")


def _day_out(day: date, page: CalendarPage, today: date) -> LeaveCalendarDayOut:
    return LeaveCalendarDayOut(
        date=day.isoformat(),
        day=day.day,
        off=day in page.off,
        holiday=day in page.holidays,
        today=day == today,
    )


def _month_key(value: date) -> str:
    return value.strftime("%Y-%m")


@leave_pages_router.get("/balances", response=LeaveBalanceListOut, auth=django_auth)
def leave_balances(request: HttpRequest, response: HttpResponse, offset: str = "") -> LeaveBalanceListOut:
    """One batch of the balances page: the visible, still-working people in name order, with their current period."""
    user = _viewer(request)
    today = timezone.localdate()
    start = batch_offset(offset)
    size = batching.LIST_BATCH  # read at call time so tests can shrink the batch
    lines, more = balance_batch(user, start, size, today)
    response["Cache-Control"] = "no-store"
    return LeaveBalanceListOut(
        today=today.isoformat(),
        rows=[
            LeaveBalanceRowOut(
                employee_id=line.employee.pk,
                employee_name=line.employee.full_name,
                waiting=line.waiting.isoformat() if line.waiting is not None else None,
                period=(
                    LeaveBalancePeriodOut(
                        start=line.period.start.isoformat(),
                        end=line.period.end.isoformat(),
                        granted=line.period.granted,
                        taken=line.period.taken,
                        left=line.period.left,
                    )
                    if line.period is not None
                    else None
                ),
            )
            for line in lines
        ],
        next_offset=start + size if more else None,
        not_configured=not_configured_text(),
        can_settings=access.can_manage_settings(user),
        empty_text=BALANCE_EMPTY_TEXT,
    )


@leave_pages_router.get("/calendar", response=LeaveCalendarOut, auth=django_auth)
def leave_calendar(
    request: HttpRequest,
    response: HttpResponse,
    month: str | None = None,
    department: str | None = None,
) -> LeaveCalendarOut:
    """One month of the team calendar. Junk or an out-of-range month is the current month; junk department is none."""
    user = _viewer(request)
    today = timezone.localdate()
    first = parse_month(month, today)
    chosen = parse_department(department)
    page = build_calendar(user, first, chosen)
    response["Cache-Control"] = "no-store"
    return LeaveCalendarOut(
        month=_month_key(first),
        title=f"Багийн хуанли — {_month_key(first)}",
        days=[_day_out(day, page, today) for day in page.days],
        lines=[
            LeaveCalendarLineOut(
                employee_id=line.employee.pk,
                employee_name=line.employee.full_name,
                cells=[_cell_out(cell) for cell in line.cells],
            )
            for line in page.lines
        ],
        prev=page.prev,
        next=page.next,
        this_month=_month_key(today) if first != today.replace(day=1) else "",
        departments=[LeaveChoiceOut(value=d.pk, label=d.name) for d in Department.objects.exclude(ext__active=False)],
        department=chosen,
        not_configured=not_configured_text(),
        can_settings=access.can_manage_settings(user),
    )
