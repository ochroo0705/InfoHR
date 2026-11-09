"""The views a report offers besides the table (board, calendar, timeline, cards, chart, pivot) and their columns.

Pure selection: no rows are read here. table.py calls `resolve` before it loads rows. This module must not import
reports.table at module level (table imports this module).
"""

import re
from calendar import monthrange
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from accounts.models import User
from django.utils import timezone

from reports import totals as totals_mod
from reports.filters import CHARTS, LAYOUTS, MAX_YEAR, MIN_MONTH_YEAR, Filters
from reports.kinds import column_kind
from reports.marks import Mark, mark_for
from reports.types import Column, Report


class TableLike(Protocol):
    """What the board needs of the table object. The table module imports this one, so that class is not imported."""

    columns: list[Column]  # the columns shown, in order
    rows: list[Any]  # every filtered, sorted raw row


CATEGORY_LAYOUTS = ("board", "chart", "pivot")  # these group rows by a category column (Report.group_options)
DATE_LAYOUTS = ("calendar", "timeline")  # these place rows by a date column (kind="date")
VALUE_LAYOUTS = ("chart", "pivot")  # these add up a value («lval»)
EMPTY_GROUP = "—"  # the blank lane and blank text; the same text as reports.table.EMPTY_GROUP (a test checks it)
BOARD_CAP = 200  # cards drawn on the board in all lanes; the lane counts still cover every row
_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])")


@dataclass(frozen=True)
class LayoutSpec:
    """The layout chosen for this viewer and the columns it draws with. A column None means the layout has none."""

    layout: str  # a key of reports.filters.LAYOUTS; "table" when no other view is used
    by: Column | None  # category (board, chart, pivot rows) or start date (calendar, timeline)
    by2: Column | None  # pivot columns, or the timeline end; the calendar end when set
    value: tuple[Column | None, str]  # what chart and pivot add up: (column or None for rows, aggregate name)
    chart: str  # a key of reports.filters.CHARTS
    month: date  # the first day of the calendar's month


def _allowed(report: Report, user: User) -> list[Column]:
    """The columns the user may see. Same rule as reports.table.allowed_columns, kept here to avoid an import cycle."""
    return [c for c in report.columns if not c.needs or user.has_perm(c.needs)]


def _is_category(report: Report, column: Column) -> bool:
    return column.key in report.group_options


def _is_date(column: Column) -> bool:
    return column.kind == "date"


def _declared_kind(column: Column) -> str:
    """The kind a column declares itself: its `kind`, else "number" for a numeric or money column, else "" (untyped).
    Values are not looked at here, so an untyped column is left to resolve, which has the rows."""
    if column.kind in ("text", "number", "date"):
        return column.kind
    return "number" if column.numeric or column.money else ""


def _aggregate_fits(column: Column, agg: str) -> bool:
    """False only when the declared kind rules the aggregate out: sum and avg need a number, min and max a number or a
    date, count always fits. An untyped column fits (resolve checks its values)."""
    kind = _declared_kind(column)
    if agg == "count" or not kind:
        return True
    if agg in ("sum", "avg"):
        return kind == "number"
    return kind in ("number", "date")


def clean_params(report: Report, user: User, filters: Filters) -> dict[str, str]:
    """The layout column parameters this viewer may keep, for restricted_filters: lby and lby2 only when they name a
    column the viewer may see that is a category or a date; lval only when its column is one the viewer may see and
    the declared kind allows the aggregate. Anything else becomes "" (the default). Used for saved views too, so a
    hidden column never survives. A layout the viewer is not offered clears every layout parameter, layout included."""
    if filters.layout not in offered_layouts(report, user):
        return {"layout": "", "lby": "", "lby2": "", "lval": "", "lchart": "", "lmonth": ""}
    visible = {c.key: c for c in _allowed(report, user)}

    def place(key: str) -> str:
        column = visible.get(key)
        return key if column is not None and (_is_category(report, column) or _is_date(column)) else ""

    lval = ""
    if filters.lval == "count":
        lval = "count"
    elif filters.lval:
        key, _, agg = filters.lval.partition(":")
        column = visible.get(key)
        if column is not None and agg in totals_mod.AGGS and _aggregate_fits(column, agg):
            lval = filters.lval
    return {
        "layout": filters.layout,
        "lby": place(filters.lby),
        "lby2": place(filters.lby2),
        "lval": lval,
        "lchart": filters.lchart,
        "lmonth": filters.lmonth,
    }


def offered_layouts(report: Report, user: User) -> list[str]:
    """The views this user may switch to: "table" first, then the report's declared layouts that have a suitable column
    the user may see, in the order of LAYOUTS. Cards need no column."""
    allowed = _allowed(report, user)
    has_category = any(_is_category(report, c) for c in allowed)
    has_date = any(_is_date(c) for c in allowed)
    offered = ["table"]
    for name in LAYOUTS:
        if name == "table" or name not in report.layouts:
            continue
        if name in CATEGORY_LAYOUTS and not has_category:
            continue
        if name in DATE_LAYOUTS and not has_date:
            continue
        offered.append(name)
    return offered


def _named(pool: list[Column], key: str) -> Column | None:
    """The column of this key from the pool, if it is there."""
    return next((c for c in pool if c.key == key), None)


def _value(allowed: list[Column], text: str, rows: Sequence[Any]) -> tuple[Column | None, str]:
    """The lval text as a (column, aggregate) pair when the column is allowed and the aggregate fits its kind, else the
    count of rows. Sum, average, min and max need a number column (a date with min or max falls back to count);
    count fits any column."""
    pairs = totals_mod.parse_totals(text) if text not in ("", "count") else ()
    if not pairs:
        return (None, "count")
    key, agg = pairs[0]
    column = _named(allowed, key)
    if column is None:
        return (None, "count")
    kind = column_kind(column, rows)
    if agg == "count":
        return (column, agg)
    if agg in ("sum", "avg") and kind == "number":
        return (column, agg)
    if agg in ("min", "max") and kind == "number":
        return (column, agg)
    return (None, "count")


def _month(text: str) -> date:
    """The month of «YYYY-MM» as its first day, with a year from MIN_MONTH_YEAR to MAX_YEAR; else this month. Never
    raises."""
    match = _MONTH.fullmatch(text or "")
    if match is not None and MIN_MONTH_YEAR <= int(match.group(1)) <= MAX_YEAR:
        try:
            return date(int(match.group(1)), int(match.group(2)), 1)
        except ValueError:
            pass
    return timezone.localdate().replace(day=1)


@dataclass(frozen=True)
class Choices:
    """What the layout bar may pick, as (key, label) pairs: the main column (by), the second column (by2) and the value
    (value: «count», then «col:agg» for each number column the viewer may see)."""

    by: list[tuple[str, str]]
    by2: list[tuple[str, str]]
    value: list[tuple[str, str]]


def layout_choices(report: Report, user: User, layout: str) -> Choices:
    """The choices of the layout bar for this layout, from the columns the viewer may see."""
    allowed = _allowed(report, user)
    if layout in CATEGORY_LAYOUTS:
        pool = [c for c in allowed if _is_category(report, c)]
    elif layout in DATE_LAYOUTS:
        pool = [c for c in allowed if _is_date(c)]
    else:
        pool = []
    numbers = [c for c in allowed if _declared_kind(c) == "number"]
    value = [("count", AGG_TEXT["count"])]
    value += [
        (f"{c.key}:{agg}", f"{c.label} ({AGG_TEXT[agg]})") for c in numbers for agg in ("sum", "avg", "min", "max")
    ]
    pairs = [(c.key, c.label) for c in pool]
    return Choices(by=pairs, by2=list(pairs), value=value)


def value_text(value: tuple[Column | None, str]) -> str:
    """The lval address text of a (column, aggregate) pair: «count», or «col:agg»."""
    column, agg = value
    return "count" if column is None or agg == "count" else f"{column.key}:{agg}"


def used_params(filters: Filters, spec: LayoutSpec) -> Filters:
    """The filters with the layout's resolved parameters, so links, print and saved views keep the view. A table
    writes none of them. Only the parameters the layout uses are written."""
    if spec.layout == "table":
        return replace(filters, layout="", lby="", lby2="", lval="", lchart="", lmonth="")
    # defaults stay out of the address: the bar's default chart (bar) and this month are written only when the request
    # named a month other than this one, and a chart other than bar
    month = f"{spec.month:%Y-%m}"
    named_month = spec.layout == "calendar" and bool(filters.lmonth) and month != f"{timezone.localdate():%Y-%m}"
    return replace(
        filters,
        layout=spec.layout,
        lby=spec.by.key if spec.by is not None else "",
        lby2=spec.by2.key if spec.by2 is not None else "",
        lval=value_text(spec.value) if spec.layout in VALUE_LAYOUTS else "",
        lchart=spec.chart if spec.layout == "chart" and spec.chart != "bar" else "",
        lmonth=month if named_month else "",
    )


def resolve(report: Report, user: User, filters: Filters, rows: Sequence[Any] = ()) -> LayoutSpec:
    """The layout for these filters as this user may see it. An unknown or not offered layout is the table; a column the
    user may not see, or one of the wrong kind for the layout, is replaced by the layout's first suitable column."""
    layout = filters.layout if filters.layout in offered_layouts(report, user) else "table"
    allowed = _allowed(report, user)
    categories = [c for c in allowed if _is_category(report, c)]
    dates = [c for c in allowed if _is_date(c)]
    pool = categories if layout in CATEGORY_LAYOUTS else dates if layout in DATE_LAYOUTS else []
    # the report's own default start date when it is allowed here, else the first date (never a guess from the data)
    default_by = (
        (_named(dates, report.layout_date) or (dates[0] if dates else None))
        if layout in DATE_LAYOUTS
        else (pool[0] if pool else None)
    )
    by = _named(pool, filters.lby) or default_by
    others = [c for c in pool if by is None or c.key != by.key]
    by2: Column | None = None
    if layout == "timeline":  # the report's own default end date, else the next date
        default_end = _named(others, report.layout_date2) or (others[0] if others else None)
        by2 = _named(others, filters.lby2) or default_end
    elif layout == "pivot":  # the second category
        by2 = _named(others, filters.lby2) or (others[0] if others else None)
    elif layout == "calendar":
        by2 = _named(others, filters.lby2)  # the end of an entry is optional on the calendar
    value = _value(allowed, filters.lval, rows) if layout in VALUE_LAYOUTS else (None, "count")
    return LayoutSpec(
        layout=layout,
        by=by,
        by2=by2,
        value=value,
        chart=filters.lchart if filters.lchart in CHARTS else "bar",
        month=_month(filters.lmonth),
    )


@dataclass(frozen=True)
class Item:
    """One card: a row as title, subtitle and extra label-value lines, with the colour of its first passing mark."""

    title: str
    subtitle: str
    href: str  # the title column's link, "" when it has none
    mark: str  # the CSS classes of the passing mark, "" for none
    extras: tuple[tuple[str, object, bool], ...] = ()  # the remaining shown columns as (label, raw value, is money)
    photo: Any = None  # the employee whose photo the card shows (Report.photo); None = no photo slot


@dataclass(frozen=True)
class Lane:
    """One board column: its category text, how many filtered rows it holds, and the cards drawn in it."""

    label: str
    count: int
    items: list[Item]


@dataclass(frozen=True)
class Board:
    """The board: lanes in label order, the filtered row count, the cards drawn and the cap."""

    lanes: list[Lane]
    total: int
    shown: int
    cap: int


def _text(value: object) -> str:
    """The display text of a value, as reports.table._text: blank is "", a date is ISO text."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def make_items(
    table: TableLike,
    rows: Sequence[Any],
    marks: Sequence[Mark],
    today: date,
    extras: int = 0,
    photo_of: Callable[[Any], Any] | None = None,
) -> list[Item]:
    """One Item per row, in order. Title: the first shown text column not blank in every filtered row (else the first
    shown column). Subtitle: the next such text column. Colour: the marks in their own order, skipping a mark on a
    column not shown; the first that passes wins. Kinds and blanks come from all filtered rows (table.rows).
    Only shown columns' value callables are called."""
    shown = table.columns
    kinds = {c.key: column_kind(c, table.rows) for c in shown}
    filled = {c.key for c in shown if kinds[c.key] == "text" and any(not _is_blank(c.value(row)) for row in table.rows)}
    texts = [c for c in shown if kinds[c.key] == "text" and c.key in filled]
    title_col = texts[0] if texts else (shown[0] if shown else None)
    sub_col = texts[1] if len(texts) > 1 else None
    named = next((c for c in shown if c.key == "name"), None)
    if photo_of is not None and named is not None:  # a person's card is titled with the name, never the code
        title_col = named
        sub_col = next((c for c in texts if c.key not in ("name", "code")), None)
    used = {c.key for c in (title_col, sub_col) if c is not None}
    rest = [c for c in shown if c.key not in used][:extras]
    by_key = {c.key: c for c in shown}
    # the card opens the row's page: the title column's link, else the first shown column that has one (a board
    # titled with the employee code still opens the employee through the name column)
    link_col = next((c for c in (title_col, *shown) if c is not None and c.href is not None), None)
    items: list[Item] = []
    for row in rows:
        title = _text(title_col.value(row)) if title_col is not None else ""
        href = link_col.href(row) if link_col is not None and link_col.href is not None else ""
        subtitle = _text(sub_col.value(row)) if sub_col is not None else ""
        mark = ""
        for rule in marks:
            column = by_key.get(rule.column)
            if column is None:  # a mark on a column that is not shown never colours a card
                continue
            mark = mark_for((rule,), column.key, column.value(row), kinds[column.key], today)
            if mark:
                break
        items.append(
            Item(
                title=title if title.strip() else EMPTY_GROUP,
                subtitle=subtitle if subtitle.strip() else "",
                href=href,
                mark=mark,
                extras=tuple((c.label, c.value(row), c.money) for c in rest),
                photo=photo_of(row) if photo_of is not None else None,
            )
        )
    return items


def _is_blank(value: object) -> bool:
    """A value with nothing to show: None, or text that is empty or only spaces."""
    return value is None or (isinstance(value, str) and not value.strip())


def build_board(table: TableLike, spec: LayoutSpec, marks: Sequence[Mark], today: date) -> Board:
    """The board of the filtered rows: one lane per category text (label order, blank «—» last), each with its filtered
    count and its cards in table order. Only the first BOARD_CAP rows in table order are drawn."""
    rows = table.rows
    by = spec.by
    keys = [_text(by.value(row)) if by is not None else "" for row in rows]
    counts: dict[str, int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    drawn = rows[:BOARD_CAP]
    items = make_items(table, drawn, marks, today)
    per_lane: dict[str, list[Item]] = {}
    for key, item in zip(keys[:BOARD_CAP], items, strict=True):
        per_lane.setdefault(key, []).append(item)
    named = sorted((k for k in counts if k.strip()), key=lambda k: k.casefold())
    spaces = [k for k in counts if k and not k.strip()]  # spaces only: its own lane, labelled «—», before the blank one
    order = named + spaces + ([""] if "" in counts else [])
    lanes = [Lane(label=k if k.strip() else EMPTY_GROUP, count=counts[k], items=per_lane.get(k, [])) for k in order]
    return Board(lanes=lanes, total=len(rows), shown=len(drawn), cap=BOARD_CAP)


CALENDAR_PER_DAY = 3  # entries drawn on one day; the rest is the «+N» count
ENTRY_MAX_DAYS = 62  # a multi-day entry is drawn on at most this many days
TIMELINE_CAP = 100  # bars drawn; the counts still cover every row
TIMELINE_YEARS = 5  # the axis reaches at most this many years from the first start
MIN_BAR_PCT = 0.5  # the narrowest bar, so a one-day marker stays visible


@dataclass(frozen=True)
class Day:
    """One cell of the calendar grid: its day, whether it is in the shown month, its entries (at most 3) and the
    count of the entries not drawn."""

    day: date
    in_month: bool
    items: list[Item]
    more: int


@dataclass(frozen=True)
class Calendar:
    """The month grid: Monday-first weeks, the blank-date count and the arrows' months as «YYYY-MM»."""

    month: date
    weeks: list[list[Day]]
    undated: int
    prev: str
    next: str

    @property
    def busy_days(self) -> list[Day]:
        """The days of the shown month that have entries, in order (the phone's day list)."""
        return [day for week in self.weeks for day in week if day.in_month and day.items]


@dataclass(frozen=True)
class Bar:
    """One timeline row: its item, its start and end dates, and its place on the axis in percent."""

    item: Item
    start: date
    end: date
    left_pct: float
    width_pct: float

    @property
    def tip(self) -> str:
        """The hover text: the dates and how many days the bar spans (both ends count)."""
        days = (self.end - self.start).days + 1
        dates = self.start.isoformat() if days <= 1 else f"{self.start.isoformat()} – {self.end.isoformat()}"
        return f"{dates} · {max(days, 1)} өдөр"


@dataclass(frozen=True)
class Timeline:
    """The timeline: bars in row order, the axis first and last day (None when no drawn row has a start), the
    blank-start count, whether the axis was clipped to TIMELINE_YEARS, the row count, the drawn rows that start after
    a clipped axis (off_axis, not drawn), the bars drawn (shown) and the cap (TIMELINE_CAP)."""

    bars: list[Bar]
    first: date | None
    last: date | None
    undated: int
    clipped: bool
    total: int
    off_axis: int
    shown: int
    cap: int

    @property
    def over_cap(self) -> int:
        """The rows past the cap: not drawn, not undated and not off the axis."""
        return self.total - self.shown - self.undated - self.off_axis


def _as_date(value: object) -> date | None:
    """A date value as a date (a datetime keeps its day); anything else is None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def entry_days(start: date, end: date) -> list[date]:
    """The days an entry is drawn on: start to end inclusive, at most ENTRY_MAX_DAYS of them. An end before the start
    gives just the start day. Uses ordinals, so no date arithmetic can overflow."""
    first = start.toordinal()
    last = max(end.toordinal(), first)
    last = min(last, first + ENTRY_MAX_DAYS - 1)
    return [date.fromordinal(o) for o in range(first, last + 1)]


def _month_start(month: date) -> date:
    """The first day of the month, its year kept within MIN_MONTH_YEAR..MAX_YEAR so the grid stays in range."""
    year = min(max(month.year, MIN_MONTH_YEAR), MAX_YEAR)
    return date(year, month.month, 1)


def _shift_month(month: date, step: int) -> date:
    """The first day of the month `step` months away. A result outside the year bounds gives the month itself."""
    index = month.year * 12 + month.month - 1 + step
    year = index // 12
    if not MIN_MONTH_YEAR <= year <= MAX_YEAR:
        return month
    return date(year, index % 12 + 1, 1)


def _month_text(month: date) -> str:
    return f"{month.year:04d}-{month.month:02d}"


def _years_later(day: date, years: int) -> date:
    """The same day `years` years later; 29 February becomes 28 February; past 9999 gives the last date."""
    year = day.year + years
    if year > date.max.year:
        return date.max
    try:
        return day.replace(year=year)
    except ValueError:
        return day.replace(year=year, day=28)


def build_calendar(table: TableLike, spec: LayoutSpec, marks: Sequence[Mark], today: date) -> Calendar:
    """The month grid for spec.month. Each row with a start date is placed on that day (and on each day up to its end
    when spec.by2 is set, see entry_days); a row with no start is counted in `undated`. The grid starts on the Monday
    on or before the 1st and has whole weeks."""
    month = _month_start(spec.month)
    rows = table.rows
    items = make_items(table, rows, marks, today)
    first_day = month - timedelta(days=month.weekday())
    weeks_count = (month.weekday() + monthrange(month.year, month.month)[1] + 6) // 7
    grid_first = first_day.toordinal()
    grid_last = grid_first + weeks_count * 7 - 1
    per_day: dict[int, list[Item]] = {}
    undated = 0
    for row, item in zip(rows, items, strict=True):
        start = _as_date(spec.by.value(row)) if spec.by is not None else None
        if start is None:
            undated += 1
            continue
        end = _as_date(spec.by2.value(row)) if spec.by2 is not None else None
        days = entry_days(start, end) if end is not None else [start]
        for day in days:
            if grid_first <= day.toordinal() <= grid_last:
                per_day.setdefault(day.toordinal(), []).append(item)
    cells = []
    for ordinal in range(grid_first, grid_last + 1):
        day = date.fromordinal(ordinal)
        entries = per_day.get(ordinal, [])
        cells.append(
            Day(
                day=day,
                in_month=day.year == month.year and day.month == month.month,
                items=entries[:CALENDAR_PER_DAY],
                more=max(len(entries) - CALENDAR_PER_DAY, 0),
            )
        )
    weeks = [cells[i : i + 7] for i in range(0, len(cells), 7)]
    return Calendar(
        month=month,
        weeks=weeks,
        undated=undated,
        prev=_month_text(_shift_month(month, -1)),
        next=_month_text(_shift_month(month, 1)),
    )


def build_timeline(table: TableLike, spec: LayoutSpec, marks: Sequence[Mark], today: date) -> Timeline:
    """The bars of the rows with a start date, in row order, for the first TIMELINE_CAP such rows (the drawn rows). A
    missing or earlier end is the start. The axis runs from the first drawn start to the latest drawn end, at most
    TIMELINE_YEARS years (clipped=True when longer); undrawn rows never stretch it. A drawn row that starts after a
    clipped axis end is not drawn and is counted in off_axis. Every bar is placed inside the axis, with left and width
    in percent and the width at least MIN_BAR_PCT."""
    rows = table.rows
    dated: list[tuple[Any, date, date]] = []
    undated = 0
    for row in rows:
        start = _as_date(spec.by.value(row)) if spec.by is not None else None
        if start is None:
            undated += 1
            continue
        end = _as_date(spec.by2.value(row)) if spec.by2 is not None else None
        if end is None or end < start:
            end = start
        dated.append((row, start, end))
    drawn = dated[:TIMELINE_CAP]
    if not drawn:
        return Timeline(
            bars=[],
            first=None,
            last=None,
            undated=undated,
            clipped=False,
            total=len(rows),
            off_axis=0,
            shown=0,
            cap=TIMELINE_CAP,
        )
    first = min(start for _, start, _ in drawn)
    latest = max(end for _, _, end in drawn)
    limit = _years_later(first, TIMELINE_YEARS)
    clipped = latest > limit
    last = limit if clipped else latest
    on_axis = [(row, start, end) for row, start, end in drawn if start <= last]
    off_axis = len(drawn) - len(on_axis)
    span = (last - first).days + 1
    items = make_items(table, [row for row, _, _ in on_axis], marks, today)
    bars: list[Bar] = []
    for item, (_, start, end) in zip(items, on_axis, strict=True):
        start_c = min(max(start, first), last)
        end_c = min(max(end, start_c), last)
        left = (start_c - first).days / span * 100
        width = ((end_c - start_c).days + 1) / span * 100
        left = min(max(left, 0.0), 100.0 - MIN_BAR_PCT)
        width = min(max(width, MIN_BAR_PCT), 100.0 - left)
        bars.append(Bar(item=item, start=start, end=end, left_pct=left, width_pct=width))
    return Timeline(
        bars=bars,
        first=first,
        last=last,
        undated=undated,
        clipped=clipped,
        total=len(rows),
        off_axis=off_axis,
        shown=len(bars),
        cap=TIMELINE_CAP,
    )


CHART_CAP = 30  # categories drawn in the chart, the last one «Бусад» included
PIVOT_ROW_CAP = 30  # pivot rows drawn, the last one «Бусад» included
PIVOT_COL_CAP = 12  # pivot columns drawn, the last one «Бусад» included
FOLDED = "Бусад"  # the label of the categories folded past a cap
TOTAL_COLUMN = "Нийт"  # the one column of a pivot without a column category
AGG_TEXT = {
    "sum": "Нийлбэр",
    "avg": "Дундаж",
    "min": "Хамгийн бага",
    "max": "Хамгийн их",
    "count": "Тоо",
}  # as views.AGG_LABELS


@dataclass(frozen=True)
class Point:
    """One chart bar, line point or donut slice: its category text, its value (None when nothing to aggregate) and
    whether the value is money."""

    label: str
    value: object
    money: bool


@dataclass(frozen=True)
class Chart:
    """The chart: its kind (a key of CHARTS), the points in category order, the value's label and whether categories
    were folded into FOLDED."""

    kind: str
    points: list[Point]
    value_label: str
    folded: bool


@dataclass(frozen=True)
class Pivot:
    """The pivot: row and column labels in order, the cells (rows by columns), the row and column totals, the grand
    total, whether the value is money, and the value's label."""

    row_labels: list[str]
    col_labels: list[str]
    cells: list[list[object]]
    row_totals: list[object]
    col_totals: list[object]
    grand: object
    money: bool
    value_label: str


def _key(column: Column | None, row: Any) -> str:
    """The category text of a row, as the table groups it; no column gives the blank text for every row."""
    return _text(column.value(row)) if column is not None else ""


def _order(keys: Sequence[str]) -> list[str]:
    """The distinct keys in display order: named ones by casefold (first seen wins a tie), then keys of only spaces,
    then the empty key last. The last two both show «—» but stay separate buckets."""
    distinct = list(dict.fromkeys(keys))
    named = sorted((k for k in distinct if k.strip() != ""), key=str.casefold)
    spaces = [k for k in distinct if k != "" and k.strip() == ""]  # shown as «—», its own bucket, before the empty key
    return named + spaces + ([""] if "" in distinct else [])


def _plan(keys: Sequence[str], cap: int) -> tuple[list[str], dict[str, int], bool]:
    """The labels to draw, the index each key lands in, and whether keys were folded. Up to cap keys are drawn as they
    are; beyond it the first cap-1 keys are drawn and the rest share the last label, FOLDED."""
    order = _order(keys)
    if len(order) <= cap:
        return [_label(k) for k in order], {k: i for i, k in enumerate(order)}, False
    index = {k: i for i, k in enumerate(order[: cap - 1])}
    index.update({k: cap - 1 for k in order[cap - 1 :]})
    return [_label(k) for k in order[: cap - 1]] + [FOLDED], index, True


def _label(key: str) -> str:
    return key if key.strip() != "" else EMPTY_GROUP


def _measure(rows: Sequence[Any], value: tuple[Column | None, str]) -> object:
    """The value of one bucket: its row count for count (or no column), else the aggregate over the column's values."""
    column, agg = value
    if column is None or agg == "count":
        return len(rows)
    return totals_mod.aggregate([column.value(row) for row in rows], agg)


def _is_money(value: tuple[Column | None, str]) -> bool:
    column, agg = value
    return column is not None and column.money and agg != "count"


def _value_label(value: tuple[Column | None, str]) -> str:
    column, agg = value
    if column is None or agg == "count":
        return AGG_TEXT["count"]
    return f"{column.label} ({AGG_TEXT.get(agg, agg)})"


def build_chart(table: TableLike, spec: LayoutSpec) -> Chart:
    """The chart of the filtered rows: one point per category (spec.by) in table order, the value from spec.value over
    every row of the category. Beyond CHART_CAP categories the rest fold into FOLDED, aggregated over their rows."""
    rows = table.rows
    keys = [_key(spec.by, row) for row in rows]
    labels, index, folded = _plan(keys, CHART_CAP)
    members: list[list[Any]] = [[] for _ in labels]
    for row, key in zip(rows, keys, strict=True):
        members[index[key]].append(row)
    money = _is_money(spec.value)
    points = [
        Point(label=label, value=_measure(group, spec.value), money=money)
        for label, group in zip(labels, members, strict=True)
    ]
    return Chart(kind=spec.chart, points=points, value_label=_value_label(spec.value), folded=folded)


def build_pivot(table: TableLike, spec: LayoutSpec) -> Pivot:
    """The pivot of the filtered rows: rows by spec.by, columns by spec.by2 (one column «Нийт» without it), each cell
    the value over its rows. Rows fold past PIVOT_ROW_CAP, columns past PIVOT_COL_CAP; totals are aggregated over the
    rows, never added up from the cells."""
    rows = table.rows
    row_keys = [_key(spec.by, row) for row in rows]
    col_keys = [_key(spec.by2, row) for row in rows]
    row_labels, row_index, _ = _plan(row_keys, PIVOT_ROW_CAP)
    if spec.by2 is None:
        col_labels, col_index = [TOTAL_COLUMN], {"": 0}
    else:
        col_labels, col_index, _ = _plan(col_keys, PIVOT_COL_CAP)
    grid: list[list[list[Any]]] = [[[] for _ in col_labels] for _ in row_labels]
    row_members: list[list[Any]] = [[] for _ in row_labels]
    col_members: list[list[Any]] = [[] for _ in col_labels]
    for row, rk, ck in zip(rows, row_keys, col_keys, strict=True):
        r, c = row_index[rk], col_index[ck]
        grid[r][c].append(row)
        row_members[r].append(row)
        col_members[c].append(row)
    return Pivot(
        row_labels=row_labels,
        col_labels=col_labels,
        cells=[[_measure(cell, spec.value) for cell in line] for line in grid],
        row_totals=[_measure(group, spec.value) for group in row_members],
        col_totals=[_measure(group, spec.value) for group in col_members],
        grand=_measure(rows, spec.value),
        money=_is_money(spec.value),
        value_label=_value_label(spec.value),
    )
