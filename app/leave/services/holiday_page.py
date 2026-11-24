"""The holidays page's rules: the year, the add and delete of one date, and the recount after an action.

The Django view calls this module now; the API routes will call it too. Rules only; drawing is the caller's
job. The caller passes the year: nothing here reads the clock.
"""

from dataclasses import dataclass
from datetime import date

from accounts.models import User

from leave.services import calendar, writes
from leave.services.calendar_page import MAX_YEAR, MIN_YEAR
from leave.services.list_page import parse_id


@dataclass(frozen=True)
class HolidayPage:
    year: int
    holidays: list[tuple[date, str]]  # every holiday day of the year, sorted, with its name
    fixed_count: int  # how many fixed-date holidays the prefill adds at most


def parse_year(value: str | None, fallback_year: int) -> int:
    """The year from user input; junk or a year outside 1900..2100 gives `fallback_year`."""
    year = parse_id(value)
    if year is None or not MIN_YEAR <= year <= MAX_YEAR:
        return fallback_year
    return year


def add_holiday(year: int, raw_date: str, raw_name: str) -> str:
    """Set one date's holiday name. Returns the error text, or "" when saved."""
    name = raw_name.strip()
    try:
        day = date.fromisoformat(raw_date)
    except ValueError:
        return "Огноо буруу эсвэл нэр хоосон байна."
    if not name:
        return "Огноо буруу эсвэл нэр хоосон байна."
    if day.year != year:
        return "Огноо сонгосон жилийнх байх ёстой."
    if len(name) > 100:
        return "Нэр 100 тэмдэгтээс урт байж болохгүй."
    names = calendar.holiday_names(year)
    names[day] = name
    writes.set_holiday_dates(year, names)
    return ""


def delete_holiday(year: int, raw_date: str) -> None:
    """Remove one date from the holidays of `year`. A bad date or a day not listed changes nothing."""
    try:
        day = date.fromisoformat(raw_date)
    except ValueError:
        return
    names = calendar.holiday_names(year)
    if names.pop(day, None) is not None:
        writes.set_holiday_dates(year, names)


def holiday_page(year: int) -> HolidayPage:
    return HolidayPage(
        year=year,
        holidays=sorted(calendar.holiday_names(year).items()),
        fixed_count=len(calendar.FIXED_HOLIDAYS),
    )


def apply_holiday_action(year: int, action: str, raw_date: str, raw_name: str, user: User) -> str:
    """Run one POST action (`prefill`, `add` or `delete`) and recount the leaves on the days that changed.

    Returns the error text of `add`, or "" when there is none. Any other action changes nothing.
    """
    before = calendar.holiday_names(year)
    error = ""
    if action == "prefill":
        calendar.prefill_year(year)
    elif action == "add":
        error = add_holiday(year, raw_date, raw_name)
    elif action == "delete":
        delete_holiday(year, raw_date)
    after = calendar.holiday_names(year)
    changed = {d for d in before.keys() | after.keys() if before.get(d) != after.get(d)}
    writes.recount_assigns(changed, user)  # Info HR rows only; old-program rows keep their days
    return error
