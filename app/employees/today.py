"""Facts for the Today page: headcount, who is away, pending orders, birthdays and anniversaries."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from accounts.models import User

from employees import access
from employees.listing import WORKING_STATES, Row, is_working
from employees.models import EmployeeExt, HrOrder, OrderState

UPCOMING_DAYS = 30
WINDOW_DAYS = 14  # the who's-away strip: today and the 13 days after


@dataclass
class Away:
    row: Row
    label: str  # the leave type's name
    until: date


@dataclass
class Upcoming:
    row: Row
    kind: str  # "birthday" | "anniversary"
    on: date
    years: int | None = None  # anniversaries only


@dataclass(frozen=True)
class TimelineDay:
    day: date
    off: bool  # weekend or public holiday
    is_today: bool
    holiday: str = ""  # the public holiday's name, empty otherwise


def headcount(rows: list[Row]) -> int:
    return sum(1 for r in rows if is_working(r))


def away_on_day(user: User, rows: list[Row], day: date) -> list[Away]:
    """Employees with a recorded leave that covers `day`. Empty without the leave right."""
    from leave import access as leave_access  # local import: leave depends on employees, not the reverse
    from leave.services import rows as leave_rows

    if not leave_access.can_view(user):
        return []
    by_pk = {r.employee.pk: r for r in rows if r.state in WORKING_STATES}
    found = [
        lv
        for lv in leave_rows.leaves(employee_ids=list(by_pk), start=day, end=day)
        if lv.counts and lv.employee_id in by_pk
    ]
    away = [Away(by_pk[lv.employee_id], lv.leave_type.name, lv.end) for lv in found]
    return sorted(away, key=lambda a: (a.until, a.row.employee.full_name))


def away_on(user: User, rows: list[Row], today: date) -> list[Away]:
    """Employees with a recorded leave that covers `today`. Empty without the leave right."""
    return away_on_day(user, rows, today)


def pending_orders(user: User, rows: list[Row]) -> int | None:
    """Orders still waiting for a number; None when the user does not handle orders (no tile)."""
    if not access.can_manage(user):
        return None
    ids = [r.employee.pk for r in rows if r.state != "left"]
    return HrOrder.objects.filter(employee_id__in=ids, state=OrderState.PENDING).count()


def _next_on(month: int, day: int, today: date) -> date:
    """The next date on or after `today` that falls on month/day (29 Feb counts as 28 Feb in other years)."""
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            d = date(year, 2, 28)
        if d >= today:
            return d
    raise AssertionError("unreachable: next year always has the date")


def upcoming(user: User, rows: list[Row], today: date) -> list[Upcoming]:
    """Birthdays and work anniversaries in the next UPCOMING_DAYS days, soonest first.

    A birthday is personal data (own record or the personal right); an anniversary is not.
    """
    horizon = today + timedelta(days=UPCOMING_DAYS)
    out: list[Upcoming] = []
    for r in rows:
        if r.state not in WORKING_STATES:
            continue
        e = r.employee
        if e.birth_date is not None and access.can_view_personal(user, e):
            on = _next_on(e.birth_date.month, e.birth_date.day, today)
            if on <= horizon:
                out.append(Upcoming(r, "birthday", on))
        if e.first_hire_date is not None:
            on = _next_on(e.first_hire_date.month, e.first_hire_date.day, today)
            years = on.year - e.first_hire_date.year
            if years >= 1 and on <= horizon:
                out.append(Upcoming(r, "anniversary", on, years))
    return sorted(out, key=lambda u: (u.on, u.row.employee.full_name))


def upcoming_counts(found: list[Upcoming]) -> dict[str, int]:
    """How many birthdays and anniversaries `found` holds; both keys are always present."""
    return {kind: sum(1 for u in found if u.kind == kind) for kind in ("birthday", "anniversary")}


def prime_exts(rows: list[Row]) -> None:
    """Load the HR row of every person in one query, so the page's rules (attention box, upcoming dates) do not
    query once per person. A missing HR row is cached as None too, which is what `ext_of` reads as "no HR row"."""
    exts = {x.employee_id: x for x in EmployeeExt.objects.filter(employee_id__in=[r.employee.pk for r in rows])}
    for r in rows:
        type(r.employee).ext.related.set_cached_value(r.employee, exts.get(r.employee.pk))


def _window_days(today: date) -> list[TimelineDay]:
    """The WINDOW_DAYS days from `today`, weekends and public holidays marked off."""
    from leave.services import calendar  # local import: leave depends on employees, not the reverse

    last = today + timedelta(days=WINDOW_DAYS - 1)
    names = {
        d: name
        for year in {today.year, last.year}
        for d, name in calendar.holiday_names(year).items()
        if today <= d <= last
    }
    return [
        TimelineDay(d, off=not calendar.is_working_day(d, set(names)), is_today=d == today, holiday=names.get(d, ""))
        for d in (today + timedelta(n) for n in range(WINDOW_DAYS))
    ]


def _window_leaves(rows: list[Row], today: date) -> list[Any]:
    """Recorded leaves of working people that touch the window. The caller has checked the leave right."""
    from leave.services import rows as leave_rows

    by_pk = {r.employee.pk for r in rows if r.state in WORKING_STATES}
    last = today + timedelta(days=WINDOW_DAYS - 1)
    return [
        lv
        for lv in leave_rows.leaves(employee_ids=list(by_pk), start=today, end=last)
        if lv.counts and lv.employee_id in by_pk
    ]


def _away_counts(days: list[TimelineDay], found: list[Any], today: date, show_leave: bool) -> list[int | None]:
    """People away per day: a person counts once per working day they are covered; None on an off day, and
    everywhere without the leave right."""
    if not show_leave:
        return [None] * WINDOW_DAYS
    people: list[set[int]] = [set() for _ in range(WINDOW_DAYS)]
    for lv in found:
        first, final = max(lv.start, today), min(lv.end, today + timedelta(days=WINDOW_DAYS - 1))
        for index in range((first - today).days, (final - today).days + 1):
            if not days[index].off:
                people[index].add(lv.employee_id)
    return [None if d.off else len(people[i]) for i, d in enumerate(days)]


@dataclass(frozen=True)
class AwayStrip:
    days: list[TimelineDay]  # WINDOW_DAYS days from today
    counts: list[int | None]  # people away per day; None on an off day or without the leave right
    today_split: list[tuple[str, int]]  # (leave type name, people) for today, largest first
    show_leave: bool


def away_strip(user: User, rows: list[Row], today: date) -> AwayStrip:
    """The 14-day strip of away counts, plus today's people grouped by leave type. Needs the leave right."""
    from leave import access as leave_access  # local import: leave depends on employees, not the reverse

    show_leave = leave_access.can_view(user)
    days = _window_days(today)
    found = _window_leaves(rows, today) if show_leave else []
    counts = _away_counts(days, found, today, show_leave)
    split: dict[str, set[int]] = {}
    for lv in found if not days[0].off else []:  # an off day has no count, so no split either
        if lv.start <= today <= lv.end:
            split.setdefault(lv.leave_type.name, set()).add(lv.employee_id)
    today_split = sorted(((name, len(ids)) for name, ids in split.items()), key=lambda t: (-t[1], t[0]))
    return AwayStrip(days=days, counts=counts, today_split=today_split, show_leave=show_leave)
