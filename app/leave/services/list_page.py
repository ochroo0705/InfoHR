"""The leave list screen's rules: how the query string becomes a filter, which rows a batch holds, and the page banners.

The Django list view and the API both call this module, so the two show the same rows. Rules only; drawing is the
caller's job.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from accounts.models import User
from employees import access as employee_access
from employees.models import Employee
from macs.dialect import search_match

from leave.services import calendar, ledger, rows
from leave.services.rows import LeaveRow

MAX_INT = 2_147_483_647  # production ids are 32-bit integers


def parse_id(value: str | None) -> int | None:
    """A non-negative 32-bit id from user input, or None (never raises)."""
    if not value or len(value) > 12 or not value.isdecimal():
        return None
    number = int(value)
    return number if number <= MAX_INT else None


def parse_iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class LeaveFilter:
    q: str  # the search words, or the full name of the person the `employee` link chose
    employee: int | None  # a person's id from the employee page link; when set, `q` is not used to search
    status: str  # «recorded» (default), «cancelled», «mistake», «rejected», «all», or any other text (matches nothing)
    type_id: int | None
    start: date | None
    end: date | None


def parse_filter(user: User, query: Mapping[str, str]) -> LeaveFilter:
    """The filter the query string asks for. A `employee` link shows that person only and sets `q` to their name, but
    only when the user may see that person; otherwise `q` stays as typed."""
    q = query.get("q", "").strip()
    employee_id = parse_id(query.get("employee"))
    if employee_id is not None:  # link from the employee page
        person = employee_access.visible_employees(user).filter(pk=employee_id).first()
        q = person.full_name if person else q
    return LeaveFilter(
        q=q,
        employee=employee_id,
        status=query.get("status", "recorded"),
        type_id=parse_id(query.get("type")),
        start=parse_iso(query.get("from", "")),
        end=parse_iso(query.get("to", "")),
    )


def list_batch(user: User, flt: LeaveFilter, offset: int, size: int) -> tuple[list[tuple[LeaveRow, Employee]], bool]:
    """One batch of the list (newest first) with each row's employee, and whether more rows follow it."""
    people = employee_access.visible_employees(user)
    if flt.employee is not None:
        people = people.filter(pk=flt.employee)
    else:
        for word in flt.q.split():  # every word must match a name part or the code
            people = people.filter(search_match(word, "family_name", "given_name", "code", icase=True))
    state = None if flt.status == "all" else flt.status.upper()
    page, more = rows.leaves_page(
        people.order_by(),
        offset=offset,
        size=size,
        start=flt.start,
        end=flt.end,
        type_id=flt.type_id,
        state=state,
    )
    names = Employee.objects.in_bulk([lv.employee_id for lv in page])  # only the people on this batch
    return [(lv, names[lv.employee_id]) for lv in page], more


def not_configured_text() -> str:
    """The warning that no annual leave type is set, or «» when one is (every leave page shows it)."""
    return "" if ledger.annual_configured() else ledger.NOT_CONFIGURED


def banners(today: date) -> tuple[str, list[int]]:
    """The page banners: the not-configured text, and the years whose public holidays are missing (this year, and
    next year in December)."""
    not_configured = not_configured_text()
    missing = [
        y
        for y in (today.year, today.year + 1)
        if (y == today.year or today.month == 12) and not calendar.has_holidays(y)
    ]
    return not_configured, missing
