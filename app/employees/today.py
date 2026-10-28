"""Facts for the Today page: headcount, who is away, pending orders, birthdays and anniversaries."""

from dataclasses import dataclass
from datetime import date, timedelta

from accounts.models import User

from employees import access, attention
from employees.listing import Row
from employees.models import EmployeeExt, EventType, HrOrder, OrderState

UPCOMING_DAYS = 30
WORKING_STATES = ("active", "long_leave")
WINDOW_DAYS = 14  # the who's-away timeline: today and the 13 days after

# Marker kinds, most important first: a merged marker lists its items in this order.
MARKER_ORDER = (
    "termination",
    "transfer",
    "contract",
    "leave_start",
    "leave_return",
    "probation",
    "salary",
    "anniversary",
    "birthday",
)
EVENT_KIND = {
    EventType.TERMINATION.value: "termination",
    EventType.TRANSFER.value: "transfer",
    EventType.PROMOTION.value: "transfer",
    EventType.DEMOTION.value: "transfer",
    EventType.REHIRE.value: "transfer",
    EventType.CONTRACT.value: "contract",
    EventType.LEAVE_START.value: "leave_start",
    EventType.LEAVE_RETURN.value: "leave_return",
    EventType.SALARY_CHANGE.value: "salary",
}
# Dated rules that only the HR-dates right sees (attention.sees_hr_dates), as in the Attention box.
HR_DATES_KINDS = ("contract", "probation", "leave_return")


@dataclass(frozen=True)
class MarkerLook:
    """How a marker kind is drawn: a letter in a small circle, solid or (waiting) dashed, and its legend name.
    Colours stay in the slate/violet/amber/red classes (UI_RULES §8)."""

    kind: str
    name: str  # the legend text, in Mongolian
    glyph: str  # one letter, shown in the circle
    fill: str  # solid marker
    line: str  # waiting marker: dashed outline on white


_VIOLET = "bg-violet-600 text-white"
_VIOLET_LINE = "border-violet-600 bg-white text-violet-700"
_SLATE = "bg-slate-600 text-white"
_SLATE_LINE = "border-slate-600 bg-white text-slate-700"
_AMBER = "bg-amber-400 text-slate-900"
_AMBER_LINE = "border-amber-500 bg-white text-slate-800"
MARKER_LOOK: dict[str, MarkerLook] = {
    "termination": MarkerLook(
        "termination", "Ажлаас гарах", "Х", "bg-red-600 text-white", "border-red-600 bg-white text-red-700"
    ),
    "transfer": MarkerLook("transfer", "Шилжилт, албан тушаал", "Ш", _VIOLET, _VIOLET_LINE),
    "contract": MarkerLook("contract", "Гэрээ", "Г", _VIOLET, _VIOLET_LINE),
    "probation": MarkerLook("probation", "Туршилтын хугацаа", "Т", _VIOLET, _VIOLET_LINE),
    "leave_start": MarkerLook("leave_start", "Чөлөө эхлэх", "Ч", _SLATE, _SLATE_LINE),
    "leave_return": MarkerLook("leave_return", "Чөлөөнөөс буцах", "Б", _SLATE, _SLATE_LINE),
    "salary": MarkerLook(
        "salary", "Цалингийн өөрчлөлт", "Ц", "bg-slate-500 text-white", "border-slate-500 bg-white text-slate-600"
    ),
    "anniversary": MarkerLook("anniversary", "Ажилд орсны ой", "Ж", _AMBER, _AMBER_LINE),
    "birthday": MarkerLook("birthday", "Төрсөн өдөр", "Ө", _AMBER, _AMBER_LINE),
}


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


@dataclass(frozen=True)
class Bar:
    leave_id: int
    label: str  # the leave type's name
    start: date  # the real leave dates, not clipped to the window
    end: date
    column: int  # 1-based day inside the window
    span: int  # calendar days drawn inside the window
    annual: bool  # uses the annual balance
    cut_left: bool  # the leave began before the window
    cut_right: bool  # the leave runs past the window


@dataclass(frozen=True)
class MarkerItem:
    kind: str  # one of MARKER_ORDER
    label: str  # what happens, in Mongolian
    on: date
    waiting: bool  # the change still waits for its signed order

    @property
    def look(self) -> MarkerLook:
        return MARKER_LOOK[self.kind]


@dataclass(frozen=True)
class Marker:
    column: int  # 1-based day inside the window
    items: list[MarkerItem]  # one person, one day; most important kind first
    waiting: bool  # every item waits for its order: drawn dashed


@dataclass(frozen=True)
class TimelineLine:
    row: Row
    bars: list[Bar]
    markers: list[Marker]


@dataclass(frozen=True)
class Timeline:
    days: list[TimelineDay]
    lines: list[TimelineLine]
    away_counts: list[int | None]  # people away per day; None on an off day, all None without the leave right
    show_leave: bool  # the leave right: bars and counts are only filled then

    def _items(self) -> list[MarkerItem]:
        return [item for line in self.lines for m in line.markers for item in m.items]

    @property
    def legend(self) -> list[MarkerLook]:
        """The marker kinds drawn on the card, in MARKER_ORDER."""
        kinds = {item.kind for item in self._items()}
        return [MARKER_LOOK[k] for k in MARKER_ORDER if k in kinds]

    @property
    def any_waiting(self) -> bool:
        return any(item.waiting for item in self._items())


def headcount(rows: list[Row]) -> int:
    return sum(1 for r in rows if r.state in WORKING_STATES)


def away_on(user: User, rows: list[Row], today: date) -> list[Away]:
    """Employees with a recorded leave that covers `today`. Empty without the leave right."""
    from leave import access as leave_access  # local import: leave depends on employees, not the reverse
    from leave.services import rows as leave_rows

    if not leave_access.can_view(user):
        return []
    by_pk = {r.employee.pk: r for r in rows if r.state in WORKING_STATES}
    found = [
        lv
        for lv in leave_rows.leaves(employee_ids=list(by_pk), start=today, end=today)
        if lv.counts and lv.employee_id in by_pk
    ]
    away = [Away(by_pk[lv.employee_id], lv.leave_type.name, lv.end) for lv in found]
    return sorted(away, key=lambda a: (a.until, a.row.employee.full_name))


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


def _prime_exts(rows: list[Row]) -> None:
    """Load the HR row of every person in one query, so the rules below do not query once per person.

    A missing HR row is cached as None too, which is what `ext_of` reads as "no HR row"."""
    exts = {x.employee_id: x for x in EmployeeExt.objects.filter(employee_id__in=[r.employee.pk for r in rows])}
    for r in rows:
        type(r.employee).ext.related.set_cached_value(r.employee, exts.get(r.employee.pk))


def _markers(user: User, rows: list[Row], today: date, last: date) -> dict[int, list[Marker]]:
    """Markers of every person in `rows`, by employee pk. Events use every visible row (a left employee's
    waiting rehire counts); the dated rules skip left rows, as the Attention box does."""
    can_salary = access.can_view_salary(user)
    hr_dates = attention.sees_hr_dates(user)
    ids = [r.employee.pk for r in rows]
    found: dict[tuple[int, int], list[MarkerItem]] = {}

    def add(pk: int, on: date, kind: str, label: str, waiting: bool) -> None:
        if kind in HR_DATES_KINDS and not hr_dates:
            return
        if today <= on <= last:  # a waiting change whose date is already past is not shown
            found.setdefault((pk, (on - today).days), []).append(MarkerItem(kind, label, on, waiting))

    for ev in attention.dated_events(ids, can_salary, start=today).filter(effective__lte=last):
        add(ev.employee_id, ev.effective, EVENT_KIND[ev.type], ev.get_type_display(), False)
    for ev in attention.dated_events(ids, can_salary, waiting=True):
        add(ev.employee_id, ev.effective, EVENT_KIND[ev.type], ev.get_type_display(), True)
    for r in rows:
        if r.state == "left" or not hr_dates:
            continue
        pk = r.employee.pk
        pe = attention.probation_end(r)
        if pe is not None:
            add(pk, pe, "probation", "Туршилтын хугацаа дуусах", False)
        ce = attention.contract_end(r)
        if ce is not None:
            add(pk, ce, "contract", "Гэрээ дуусах", False)
        back = attention.planned_return(r, today)
        if back is not None:
            add(pk, back, "leave_return", "Чөлөөнөөс буцах", False)
    for u in upcoming(user, rows, today):  # working states only, within 30 days
        label = "Төрсөн өдөр" if u.kind == "birthday" else f"Ажилд орсны {u.years} жилийн ой"
        add(u.row.employee.pk, u.on, u.kind, label, False)

    out: dict[int, list[Marker]] = {}
    for (pk, index), items in found.items():
        items.sort(key=lambda i: MARKER_ORDER.index(i.kind))
        out.setdefault(pk, []).append(Marker(index + 1, items, all(i.waiting for i in items)))
    return out


def _first_column(line: TimelineLine) -> int:
    return min([b.column for b in line.bars] + [m.column for m in line.markers])


def away_timeline(user: User, rows: list[Row], today: date) -> Timeline:
    """The 14 days from `today`: who is on leave, and what is coming. Never None.

    Bars and counts need the leave right. Only recorded leave counts; half-day flags are ignored. A person is
    counted once per working day they are covered; weekends and public holidays are off and get no count.
    Markers follow the rights of each source (see `_markers`).
    """
    from leave import access as leave_access  # local import: leave depends on employees, not the reverse
    from leave.services import calendar
    from leave.services import rows as leave_rows

    show_leave = leave_access.can_view(user)
    last = today + timedelta(days=WINDOW_DAYS - 1)
    names = {
        d: name
        for year in {today.year, last.year}
        for d, name in calendar.holiday_names(year).items()
        if today <= d <= last
    }
    days = [
        TimelineDay(d, off=not calendar.is_working_day(d, set(names)), is_today=d == today, holiday=names.get(d, ""))
        for d in (today + timedelta(n) for n in range(WINDOW_DAYS))
    ]
    _prime_exts(rows)
    everyone = {r.employee.pk: r for r in rows}
    bars: dict[int, list[Bar]] = {}
    people: list[set[int]] = [set() for _ in range(WINDOW_DAYS)]
    if show_leave:
        by_pk = {r.employee.pk: r for r in rows if r.state in WORKING_STATES}
        found = [
            lv
            for lv in leave_rows.leaves(employee_ids=list(by_pk), start=today, end=last)
            if lv.counts and lv.employee_id in by_pk
        ]
        for lv in found:
            first, final = max(lv.start, today), min(lv.end, last)
            column = (first - today).days + 1
            span = (final - first).days + 1
            bars.setdefault(lv.employee_id, []).append(
                Bar(
                    leave_id=lv.id,
                    label=lv.leave_type.name,
                    start=lv.start,
                    end=lv.end,
                    column=column,
                    span=span,
                    annual=lv.type_ext.uses_annual_balance,
                    cut_left=lv.start < today,
                    cut_right=lv.end > last,
                )
            )
            for index in range(column - 1, column - 1 + span):
                if not days[index].off:
                    people[index].add(lv.employee_id)
    markers = _markers(user, rows, today, last)
    lines = [
        TimelineLine(
            everyone[pk],
            sorted(bars.get(pk, []), key=lambda b: b.column),
            sorted(markers.get(pk, []), key=lambda m: m.column),
        )
        for pk in set(bars) | set(markers)
    ]
    lines.sort(key=lambda line: (_first_column(line), line.row.employee.full_name))
    if show_leave:
        counts: list[int | None] = [None if d.off else len(people[i]) for i, d in enumerate(days)]
    else:
        counts = [None] * WINDOW_DAYS
    return Timeline(days=days, lines=lines, away_counts=counts, show_leave=show_leave)
