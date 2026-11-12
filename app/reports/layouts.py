"""The views a report offers besides the table (board, calendar, timeline, cards, chart, pivot) and their columns.

Pure selection: no rows are read here. table.py calls `resolve` before it loads rows. This module must not import
reports.table at module level (table imports this module).
"""

import re
from calendar import monthrange
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, SupportsFloat, cast

from accounts.models import User
from django.utils import timezone

from reports import privacy
from reports import totals as totals_mod
from reports.filters import CHARTS, GRAINS, LAYOUTS, MAX_YEAR, MIN_MONTH_YEAR, SHOWS, Filters
from reports.kinds import column_kind
from reports.marks import Mark, mark_for
from reports.types import Column, Report

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison


class TableLike(Protocol):
    """What the board needs of the table object. The table module imports this one, so that class is not imported."""

    columns: list[Column]  # the columns shown, in order
    rows: list[Any]  # every filtered, sorted raw row


CATEGORY_LAYOUTS = ("board", "chart", "pivot")  # these group rows by a category column (Report.group_options)
DATE_LAYOUTS = ("calendar", "timeline")  # these place rows by a date column (kind="date")
VALUE_LAYOUTS = ("chart", "pivot")  # these add up a value: grain, show and the offer logic use it
LVAL_LAYOUTS = ("board", "chart", "pivot")  # these take the value («lval», «Утга»); the board adds it up per lane
EMPTY_GROUP = "—"  # the blank lane and blank text; the same text as reports.table.EMPTY_GROUP (a test checks it)
BOARD_CAP = 200  # cards drawn on the board in all lanes; the lane counts still cover every row
BOARD_EXTRAS = 2  # shown columns after the title and subtitle, drawn as label: value lines on a board card
_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])")
# a date category whose dates span more whole months than this is bucketed by year, else by month (auto grain)
AUTO_YEAR_AFTER_MONTHS = 36


@dataclass(frozen=True)
class LayoutSpec:
    """The layout chosen for this viewer and the columns it draws with. A column None means the layout has none."""

    layout: str  # a key of reports.filters.LAYOUTS; "table" when no other view is used
    by: Column | None  # category (board, chart, pivot rows) or start date (calendar, timeline)
    by2: Column | None  # pivot columns, or the timeline end; the calendar end when set
    value: tuple[Column | None, str]  # what chart and pivot add up: (column or None for rows, aggregate name)
    chart: str  # a key of reports.filters.CHARTS
    month: date  # the first day of the calendar's month
    grain: str = ""  # a key of reports.filters.GRAINS for a date category (chart, pivot); "" = as the dates are
    show: str = ""  # a key of reports.filters.SHOWS (chart, pivot); "" = no percent
    sort: str = ""  # a key of reports.filters.SORTS (chart); "" = the category order
    order: str = ""  # "count" = board lanes by number of cards (board); "" = alphabetical
    lane_order: tuple[str, ...] = ()  # the report's flow order of the board's lanes (Report.lane_orders); () = none
    rep: bool = False  # the calendar repeats a yearly date each year (the «Тийм» choice)
    week: date | None = None  # the calendar's week view starts on this Monday; None = the month view
    year: int | None = None  # the timeline's year window; None = no window
    all_years: bool = False  # the timeline with no window («Бүгд»): the axis covers every drawn date, not 5 years
    group: Column | None = None  # the timeline's grouping column (a category); None = no grouping
    value2: tuple[Column | None, str] | None = None  # the pivot's second value; None = no second grid


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
    hidden column never survives. A layout the viewer is not offered clears every layout parameter, layout included.
    lgroup is kept only for a visible category column; lval2 follows the same rule as lval."""
    if filters.layout not in offered_layouts(report, user):
        return {
            "layout": "",
            "lby": "",
            "lby2": "",
            "lval": "",
            "lchart": "",
            "lmonth": "",
            "lgrain": "",
            "lshow": "",
            "lsort": "",
            "lorder": "",
            "lrep": "",
            "lweek": "",
            "lyear": "",
            "lgroup": "",
            "lval2": "",
        }
    visible = {c.key: c for c in _allowed(report, user)}

    def place(key: str) -> str:
        column = visible.get(key)
        return key if column is not None and (_is_category(report, column) or _is_date(column)) else ""

    def value(text: str) -> str:
        if text == "count":
            return text
        key, _, agg = text.partition(":")
        column = visible.get(key)
        # a date column has no sum, average or min/max to plot: only count, or a number (or untyped) column, is kept
        if column is not None and agg in totals_mod.AGGS and _aggregate_fits(column, agg):
            if agg == "count" or _declared_kind(column) in ("number", ""):
                return text
        return ""

    group = visible.get(filters.lgroup)
    return {
        "layout": filters.layout,
        "lby": place(filters.lby),
        "lby2": place(filters.lby2),
        "lval": value(filters.lval) if filters.lval else "",
        "lchart": filters.lchart,
        "lmonth": filters.lmonth,
        "lgrain": filters.lgrain,
        "lshow": filters.lshow,
        "lsort": filters.lsort,
        "lorder": filters.lorder,
        "lrep": filters.lrep,
        "lweek": filters.lweek,
        "lyear": filters.lyear,
        "lgroup": filters.lgroup if group is not None and _is_category(report, group) else "",
        "lval2": value(filters.lval2) if filters.lval2 else "",
    }


def offered_layouts(report: Report, user: User) -> list[str]:
    """The views this user may switch to: "table" first, then the report's declared layouts that have a suitable column
    the user may see, in the order of LAYOUTS. Cards need no column. Chart and pivot also take a date column as their
    category (grouped by month, quarter or year), so a report with only dates offers them too; board stays category
    only."""
    allowed = _allowed(report, user)
    has_category = any(_is_category(report, c) for c in allowed)
    has_date = any(_is_date(c) for c in allowed)
    offered = ["table"]
    for name in LAYOUTS:
        if name == "table" or name not in report.layouts:
            continue
        if name in VALUE_LAYOUTS and not (has_category or has_date):
            continue
        if name == "board" and not has_category:
            continue
        if name in DATE_LAYOUTS and not has_date:
            continue
        offered.append(name)
    return offered


def _category_pool(report: Report, allowed: list[Column], layout: str) -> list[Column]:
    """The columns a layout may group by: board takes categories; chart and pivot take categories, then date columns
    (grouped by a grain). Each column appears once."""
    categories = [c for c in allowed if _is_category(report, c)]
    if layout not in VALUE_LAYOUTS:
        return categories
    keys = {c.key for c in categories}
    return categories + [c for c in allowed if _is_date(c) and c.key not in keys]


def _month_span(column: Column, rows: Sequence[Any]) -> int:
    """The whole calendar months from the earliest to the latest non-blank date of a column over rows; 0 when no row
    has a date."""
    dates = [d for d in (_as_date(column.value(row)) for row in rows) if d is not None]
    if not dates:
        return 0
    first, last = min(dates), max(dates)
    return (last.year - first.year) * 12 + last.month - first.month


def _grain(text: str, by: Column | None, by2: Column | None, rows: Sequence[Any] = ()) -> str:
    """The date grain of a chart or pivot: the address's grain when it is a known one (an explicit choice always wins).
    Else, when a date column is grouped by, "year" if the dates span more than AUTO_YEAR_AFTER_MONTHS months (the larger
    span for two date columns), else "month". Else "" (the categories are used as they are)."""
    if text in GRAINS:
        return text
    spans = [_month_span(c, rows) for c in (by, by2) if c is not None and _is_date(c)]
    if not spans:
        return ""
    return "year" if max(spans) > AUTO_YEAR_AFTER_MONTHS else "month"


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


def _same(a: tuple[Column | None, str], b: tuple[Column | None, str]) -> bool:
    """True when two (column, aggregate) pairs name the same figure (a column is compared by its key)."""
    return (a[0].key if a[0] is not None else None, a[1]) == (b[0].key if b[0] is not None else None, b[1])


def _second(
    allowed: list[Column], text: str, rows: Sequence[Any], first: tuple[Column | None, str]
) -> tuple[Column | None, str] | None:
    """The pivot's second value as a (column, aggregate) pair, or None for no second grid: an empty text, a text that
    names no column the viewer may see or no suitable aggregate, or a pair the same as the first value. «count» is a
    second value: the count of rows."""
    if text == "count":
        second: tuple[Column | None, str] = (None, "count")
    elif not text:
        return None
    else:
        second = _value(allowed, text, rows)
        if second[0] is None:  # _value's fallback to the count of rows: the text was not usable
            return None
    return None if _same(second, first) else second


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
    group: list[tuple[str, str]] = field(default_factory=list)  # the timeline's group columns; [] for other layouts


def layout_choices(report: Report, user: User, layout: str, by_key: str = "") -> Choices:
    """The choices of the layout bar for this layout, from the columns the viewer may see. The second column never
    offers the main column's key (by_key), so the same column cannot be chosen twice."""
    allowed = _allowed(report, user)
    if layout in CATEGORY_LAYOUTS:
        pool = _category_pool(report, allowed, layout)
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
    group = [(c.key, c.label) for c in allowed if _is_category(report, c)] if layout == "timeline" else []
    return Choices(by=pairs, by2=[p for p in pairs if p[0] != by_key], value=value, group=group)


def value_text(value: tuple[Column | None, str]) -> str:
    """The lval address text of a (column, aggregate) pair: «count», or «col:agg»."""
    column, agg = value
    return "count" if column is None or agg == "count" else f"{column.key}:{agg}"


def used_params(filters: Filters, spec: LayoutSpec) -> Filters:
    """The filters with the layout's resolved parameters, so links, print and saved views keep the view. A table
    writes none of them. Only the parameters the layout uses are written."""
    if spec.layout == "table":
        return replace(
            filters,
            layout="",
            lby="",
            lby2="",
            lval="",
            lchart="",
            lmonth="",
            lgrain="",
            lshow="",
            lsort="",
            lorder="",
            lrep="",
            lweek="",
            lyear="",
            lgroup="",
            lval2="",
        )
    # defaults stay out of the address: the bar's default chart (bar) and this month are written only when the request
    # named a month other than this one, and a chart other than bar
    month = f"{spec.month:%Y-%m}"
    named_month = spec.layout == "calendar" and bool(filters.lmonth) and month != f"{timezone.localdate():%Y-%m}"
    # the new parameters: each one only for the layouts that use it, and never its default ("month" grain, no value)
    return replace(
        filters,
        layout=spec.layout,
        lby=spec.by.key if spec.by is not None else "",
        lby2=spec.by2.key if spec.by2 is not None else "",
        # the board writes lval only for a column's value: its default (the count) stays out of the address
        lval=value_text(spec.value) if spec.layout in VALUE_LAYOUTS or _board_column(spec) else "",
        lchart=spec.chart if spec.layout == "chart" and spec.chart != "bar" else "",
        lmonth=month if named_month else "",
        # only the request's own grain: an auto-chosen grain is never written, and an explicit «Сар» is kept
        lgrain=filters.lgrain if spec.layout in VALUE_LAYOUTS and filters.lgrain in GRAINS else "",
        lshow=spec.show if spec.layout in VALUE_LAYOUTS else "",
        lsort=spec.sort if spec.layout == "chart" else "",
        lorder=spec.order if spec.layout == "board" else "",
        lrep=filters.lrep if spec.layout == "calendar" else "",
        lweek=spec.week.isoformat() if spec.layout == "calendar" and spec.week is not None else "",
        # the request's own lyear (digits or «all»): the default «this year» is never written
        lyear=filters.lyear if spec.layout == "timeline" else "",
        lgroup=spec.group.key if spec.layout == "timeline" and spec.group is not None else "",
        lval2=value_text(spec.value2) if spec.layout == "pivot" and spec.value2 is not None else "",
    )


def _show_for(layout: str, show: str) -> str:
    """The percent a view honours (lshow): a chart only pct; a pivot pct, rowpct or colpct; any other view none."""
    if layout == "chart":
        return show if show == "pct" else ""
    if layout == "pivot":
        return show if show in SHOWS else ""
    return ""


def _repeats(report: Report, layout: str, text: str, by: Column | None) -> bool:
    """Whether the calendar repeats its start date each year. «1» yes, «0» no; automatic («») only for a start date the
    report lists in layout_repeat (birthdays, start dates). Any other layout never repeats."""
    if layout != "calendar":
        return False
    if text in ("0", "1"):
        return text == "1"
    return by is not None and by.key in report.layout_repeat


def resolve(report: Report, user: User, filters: Filters, rows: Sequence[Any] = ()) -> LayoutSpec:
    """The layout for these filters as this user may see it. An unknown or not offered layout is the table; a column the
    user may not see, or one of the wrong kind for the layout, is replaced by the layout's first suitable column."""
    layout = filters.layout if filters.layout in offered_layouts(report, user) else "table"
    allowed = _allowed(report, user)
    categories = [c for c in allowed if _is_category(report, c)]
    dates = [c for c in allowed if _is_date(c)]
    if layout in CATEGORY_LAYOUTS:
        pool = _category_pool(report, allowed, layout)
    else:
        pool = dates if layout in DATE_LAYOUTS else []
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
    elif layout == "pivot" or (layout == "chart" and filters.lchart == "stacked"):  # the second category
        # the default second column is a category (as before Task 3); a date column is picked only by lby2
        default_by2 = next((c for c in others if _is_category(report, c)), None)
        by2 = _named(others, filters.lby2) or default_by2
    elif layout == "calendar":
        by2 = _named(others, filters.lby2)  # the end of an entry is optional on the calendar
    value = _value(allowed, filters.lval, rows) if layout in LVAL_LAYOUTS else (None, "count")
    chart = filters.lchart if filters.lchart in CHARTS else "bar"
    if layout == "chart" and chart == "stacked" and by2 is None:  # nothing to stack by: the select shows a plain bar
        chart = "bar"
    return LayoutSpec(
        layout=layout,
        by=by,
        by2=by2,
        value=value,
        chart=chart,
        month=_month(filters.lmonth),
        grain=_grain(filters.lgrain, by, by2, rows) if layout in VALUE_LAYOUTS else "",
        show=_show_for(layout, filters.lshow),
        sort=filters.lsort if layout == "chart" else "",
        order=filters.lorder if layout == "board" else "",
        lane_order=report.lane_orders.get(by.key, ()) if layout == "board" and by is not None else (),
        rep=_repeats(report, layout, filters.lrep, by),
        week=week_start(date.fromisoformat(filters.lweek)) if layout == "calendar" and filters.lweek else None,
        year=_window_year(filters.lyear) if layout == "timeline" else None,
        all_years=layout == "timeline" and filters.lyear == "all",  # «Бүгд»: no window and no 5-year clip
        group=_named(categories, filters.lgroup) if layout == "timeline" else None,
        value2=_second(allowed, filters.lval2, rows, value) if layout == "pivot" else None,
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
    note: str = ""  # a repeated calendar entry's years since its start, «36 жил»; "" for none
    links: tuple[str, ...] = ()  # the link of each extra, parallel to `extras` ("mailto:…", "tel:…"); "" for none

    @property
    def extras_linked(self) -> list[tuple[str, object, bool, str]]:
        """Each extra with its link as (label, raw value, is money, href); href is "" when it has none."""
        count = len(self.extras)
        hrefs = (list(self.links) + [""] * count)[:count]
        return [(label, value, money, href) for (label, value, money), href in zip(self.extras, hrefs, strict=True)]


@dataclass(frozen=True)
class Lane:
    """One board column: its category text, how many filtered rows it holds, and the cards drawn in it."""

    label: str
    count: int
    items: list[Item]
    key: str = ""  # the raw category text; "" for the «—» lane
    figure: object = None  # the lane's aggregate over every row of the lane, when the value is not the count; else None
    money: bool = False  # the figure is a money amount (mnt formatting; «—» when None)


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
        extra_values = [c.value(row) for c in rest]
        items.append(
            Item(
                title=title if title.strip() else EMPTY_GROUP,
                subtitle=subtitle if subtitle.strip() else "",
                href=href,
                mark=mark,
                extras=tuple((c.label, v, c.money) for c, v in zip(rest, extra_values, strict=True)),
                photo=photo_of(row) if photo_of is not None else None,
                links=tuple(_contact_href(c.action, v) for c, v in zip(rest, extra_values, strict=True)),
            )
        )
    return items


def _is_blank(value: object) -> bool:
    """A value with nothing to show: None, or text that is empty or only spaces."""
    return value is None or (isinstance(value, str) and not value.strip())


_MAIL_ADDRESS = re.compile(r"[A-Za-z0-9._+'\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_NUMBER = re.compile(r"[0-9+\-() ]{3,}")


def _contact_href(action: str, value: object) -> str:
    """The mailto: or tel: link of a contact column's value, "" when there is none. Only text that passes the pattern
    becomes an address, so a value can never break out of the link."""
    if action not in ("mailto", "tel") or _is_blank(value):
        return ""
    text = (value if isinstance(value, str) else str(value)).strip()
    if action == "mailto":
        return f"mailto:{text}" if _MAIL_ADDRESS.fullmatch(text) else ""
    if not _PHONE_NUMBER.fullmatch(text):
        return ""
    digits = re.sub(r"\D", "", text)
    if not digits:  # "+--" or "()()()" has no number to dial
        return ""
    return "tel:" + ("+" if text.startswith("+") else "") + digits


def _lane_keys(counts: dict[str, int], spec: LayoutSpec) -> list[str]:
    """The lane keys in order. «count» (lorder): the most cards first, a tie keeps the alphabetical order. Otherwise the
    report's listed flow order (lane_order) comes first, in its own order, then the rest alphabetically (Decision 7).
    Spaces-only keys and the blank key come last, the blank one last of all."""
    named = sorted((k for k in counts if k.strip()), key=lambda k: k.casefold())
    spaces = [k for k in counts if k and not k.strip()]  # spaces only: its own lane, labelled «—», before the blank one
    blank = [""] if "" in counts else []
    if spec.order == "count":
        return sorted(named, key=lambda k: -counts[k]) + spaces + blank  # sorted is stable: a tie keeps alphabetical
    if spec.lane_order:
        listed = [k for k in dict.fromkeys(spec.lane_order) if k in counts and k.strip()]
        named = listed + [k for k in named if k not in listed]
    return named + spaces + blank


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
    items = make_items(table, drawn, marks, today, extras=BOARD_EXTRAS)
    per_lane: dict[str, list[Item]] = {}
    for key, item in zip(keys[:BOARD_CAP], items, strict=True):
        per_lane.setdefault(key, []).append(item)
    # the lane's figure adds up every row of the lane (the cap limits only the cards); the count value has no figure
    summed = _summed(spec.value)
    all_per_lane: dict[str, list[Any]] = {}
    for key, row in zip(keys, rows, strict=True):
        all_per_lane.setdefault(key, []).append(row)
    order = _lane_keys(counts, spec)
    lanes = [
        Lane(
            label=k if k.strip() else EMPTY_GROUP,
            count=counts[k],
            items=per_lane.get(k, []),
            key=k,
            figure=_figure(all_per_lane[k], spec.value)[0] if summed else None,
            money=summed and _is_money(spec.value),
        )
        for k in order
    ]
    return Board(lanes=lanes, total=len(rows), shown=len(drawn), cap=BOARD_CAP)


CALENDAR_PER_DAY = 3  # entries drawn on one day; the rest is the «+N» count
WEEK_PER_DAY = 12  # entries drawn on one day of the week view; the rest is its «+N» count
ENTRY_MAX_DAYS = 62  # a multi-day entry is drawn on at most this many days
TIMELINE_CAP = 100  # bars drawn; the counts still cover every row
TIMELINE_YEARS = 5  # the axis reaches at most this many years from the first start (no window and not all_years)
TICK_LABELS_MAX = 24  # a wider axis keeps every k-th year label, so a 200-year axis shows at most this many ticks
MIN_BAR_PCT = 0.5  # the narrowest bar, so a one-day marker stays visible


@dataclass(frozen=True)
class Day:
    """One cell of the calendar grid: its day, whether it is in the shown month, its entries (at most 3), the count of
    the entries not drawn, and whether it is today (only in the shown month: another month marks nothing)."""

    day: date
    in_month: bool
    items: list[Item]
    more: int
    is_today: bool = False


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
class BarGroup:
    """One group of a grouped timeline: its label and raw key, the count of every filtered row in it (drawn or not),
    and the bars drawn for it, sorted by start then end."""

    label: str
    key: str
    count: int
    bars: list[Bar]


TICK_MONTHS_MAX_DAYS = 400  # an axis up to this many days gets a tick at each month
TICK_QUARTERS_MAX_DAYS = 1500  # up to this many days a tick at each quarter, beyond it at each year


@dataclass(frozen=True)
class Tick:
    """One axis label («2026-03», «2026 Q1» or «2026») and its place on the axis in percent."""

    label: str
    left_pct: float


def _add_months(day: date, months: int) -> date:
    """The 1st of the month that is `months` after the month of day."""
    total = day.year * 12 + (day.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def _tick_label(day: date, step: int) -> str:
    """The label of a tick at the 1st of day's month: month, quarter or year by the step (1, 3 or 12 months)."""
    if step == 1:
        return f"{day.year:04d}-{day.month:02d}"
    if step == 3:
        return f"{day.year} Q{(day.month - 1) // 3 + 1}"
    return f"{day.year}"


def _axis_ticks(first: date, last: date) -> list[Tick]:
    """The ticks of an axis from first to last: the 1st of each month, quarter or January (by the axis length) that
    lies inside the axis, each at its place in percent of the axis."""
    span = (last - first).days + 1
    if span <= TICK_MONTHS_MAX_DAYS:
        step = 1
    elif span <= TICK_QUARTERS_MAX_DAYS:
        step = 3
    else:
        step = 12
    ticks: list[Tick] = []
    day = date(first.year, first.month, 1)
    while (day.month - 1) % step:
        day = _add_months(day, 1)
    while day <= last:
        if day >= first:
            ticks.append(Tick(label=_tick_label(day, step), left_pct=(day - first).days / span * 100))
        day = _add_months(day, step)
    if len(ticks) > TICK_LABELS_MAX:  # keep every k-th tick, the first one always among them
        every = -(-len(ticks) // TICK_LABELS_MAX)  # ceiling division
        ticks = ticks[::every]
    return ticks


@dataclass(frozen=True)
class Timeline:
    """The timeline: bars in row order, the axis first and last day (None when no drawn row has a start), the
    blank-start count, whether the axis was clipped to TIMELINE_YEARS, the row count, the drawn rows that start after
    a clipped axis (off_axis, not drawn), the bars drawn (shown), the cap (TIMELINE_CAP), the axis ticks and the place
    of today in percent (None when today is not inside the axis)."""

    bars: list[Bar]
    first: date | None
    last: date | None
    undated: int
    clipped: bool
    total: int
    off_axis: int
    shown: int
    cap: int
    ticks: list[Tick] = field(default_factory=list)
    today_pct: float | None = None
    groups: list[BarGroup] = field(default_factory=list)  # the bars by group (spec.group); [] without a grouping

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


def _anniversary(day: date, year: int) -> date:
    """The same day in another year; 29 February becomes 28 February in a year with no 29th."""
    try:
        return day.replace(year=year)
    except ValueError:
        return day.replace(year=year, day=28)


def _place(
    table: TableLike, spec: LayoutSpec, items: Sequence[Item], first: date, last: date
) -> tuple[dict[int, list[Item]], int]:
    """The entries of the rows per day, keyed by day ordinal, for the days from first to last inclusive, and the
    count of rows with no start date (`undated`). A row with a start is placed on that day, and on each day up to its
    end when spec.by2 is set (see entry_days). A yearly row (spec.rep, no end) is placed on its day in each year shown,
    from its own year on, with its years since the start as its note. `items` are the rows' items, in row order."""
    per_day: dict[int, list[Item]] = {}
    undated = 0
    grid_first = first.toordinal()
    grid_last = last.toordinal()
    # the range can show two years (a December grid has early January, a January grid late December)
    shown_years = sorted({first.year, last.year})
    for row, item in zip(table.rows, items, strict=True):
        start = _as_date(spec.by.value(row)) if spec.by is not None else None
        if start is None:
            undated += 1
            continue
        end = _as_date(spec.by2.value(row)) if spec.by2 is not None else None
        if spec.rep and end is None:  # a yearly entry: its day in each shown year from its own year on, with its years
            for year in shown_years:
                day = _anniversary(start, year)
                if year >= start.year and grid_first <= day.toordinal() <= grid_last:
                    noted = replace(item, note=f"{year - start.year} жил")
                    per_day.setdefault(day.toordinal(), []).append(noted)
            continue
        days = entry_days(start, end) if end is not None else [start]
        for day in days:
            if grid_first <= day.toordinal() <= grid_last:
                per_day.setdefault(day.toordinal(), []).append(item)
    return per_day, undated


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
    per_day, undated = _place(table, spec, items, first_day, date.fromordinal(grid_last))
    cells = []
    for ordinal in range(grid_first, grid_last + 1):
        day = date.fromordinal(ordinal)
        entries = per_day.get(ordinal, [])
        in_month = day.year == month.year and day.month == month.month
        cells.append(
            Day(
                day=day,
                in_month=in_month,
                items=entries[:CALENDAR_PER_DAY],
                more=max(len(entries) - CALENDAR_PER_DAY, 0),
                is_today=in_month and day == today,
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


@dataclass(frozen=True)
class Week:
    """The week view: the Monday it starts on, its seven days (Monday first, each with at most WEEK_PER_DAY
    entries and the count of the rest), the blank-date count, and the Mondays of the weeks before and after as
    «YYYY-MM-DD» (the same Monday at a year bound)."""

    start: date
    days: list[Day]
    undated: int
    prev: str
    next: str

    @property
    def end(self) -> date:
        """The Sunday that ends the week."""
        return self.start + timedelta(days=6)

    @property
    def busy_days(self) -> list[Day]:
        """The days of the week that have entries, in order (the phone's day list)."""
        return [day for day in self.days if day.items]


def week_start(day: date) -> date:
    """The Monday of the week of `day`, kept within MIN_MONTH_YEAR..MAX_YEAR (a spill-over day of a grid at a year bound
    gives the first or last Monday of the range)."""
    monday = day - timedelta(days=day.weekday())
    first = date(MIN_MONTH_YEAR, 1, 1)
    last = date(MAX_YEAR, 12, 31)
    last -= timedelta(days=last.weekday())
    return min(max(monday, first), last)


def _shift_week(monday: date, weeks: int) -> date:
    """The Monday `weeks` weeks away. A result outside the year bounds gives the Monday itself."""
    moved = monday + timedelta(weeks=weeks)
    if not MIN_MONTH_YEAR <= moved.year <= MAX_YEAR:
        return monday
    return moved


def build_week(table: TableLike, spec: LayoutSpec, marks: Sequence[Mark], today: date) -> Week:
    """The week of spec.week (today's week when none is set). Each day lists its entries as the month grid does (see
    _place), at most WEEK_PER_DAY of them; a row with no start is counted in `undated`."""
    start = week_start(spec.week if spec.week is not None else today)
    items = make_items(table, table.rows, marks, today)
    per_day, undated = _place(table, spec, items, start, start + timedelta(days=6))
    days = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        entries = per_day.get(day.toordinal(), [])
        days.append(
            Day(
                day=day,
                in_month=True,
                items=entries[:WEEK_PER_DAY],
                more=max(len(entries) - WEEK_PER_DAY, 0),
                is_today=day == today,
            )
        )
    return Week(
        start=start,
        days=days,
        undated=undated,
        prev=_shift_week(start, -1).isoformat(),
        next=_shift_week(start, 1).isoformat(),
    )


def _window_year(text: str) -> int | None:
    """The timeline window's year from lyear: None for «all» (no window). Otherwise the year of the digits, or this year
    when lyear is empty (the default) or not a number, kept within MIN_MONTH_YEAR..MAX_YEAR."""
    if text == "all":
        return None
    year = timezone.localdate().year
    try:
        year = int(text) if text else year
    except ValueError:
        pass
    return min(max(year, MIN_MONTH_YEAR), MAX_YEAR)


def _group_key(column: Column, row: Any) -> str:
    """The group text of a row: a blank or spaces-only value is "", the «—» group (one group for both)."""
    key = _key(column, row)
    return key if key.strip() != "" else ""


def _groups(rows: Sequence[Any], column: Column, keyed: Sequence[tuple[Bar, str]]) -> list[BarGroup]:
    """The groups of a grouped timeline in the board's lane order (_order, the blank «—» last). count covers every
    filtered row of the group, drawn or not; the drawn bars (bar, group text) are placed in their group, sorted by
    start then end (a tie keeps the row order). A group whose rows are all undrawn is listed with no bars."""
    counts: dict[str, int] = {}
    for row in rows:
        key = _group_key(column, row)
        counts[key] = counts.get(key, 0) + 1
    placed: dict[str, list[Bar]] = {key: [] for key in counts}
    for bar, key in keyed:
        placed[key].append(bar)
    return [
        BarGroup(
            label=_label(key),
            key=key,
            count=counts[key],
            bars=sorted(placed[key], key=lambda bar: (bar.start, bar.end)),
        )
        for key in _order(list(counts))
    ]


def build_timeline(table: TableLike, spec: LayoutSpec, marks: Sequence[Mark], today: date) -> Timeline:
    """The bars of the rows with a start date, in row order, for the first TIMELINE_CAP such rows (the drawn rows). A
    missing or earlier end is the start. The axis runs from the first drawn start to the latest drawn end, at most
    TIMELINE_YEARS years (clipped=True when longer); undrawn rows never stretch it. A drawn row that starts after a
    clipped axis end is not drawn and is counted in off_axis. With spec.all_years («Бүгд») the axis is never clipped:
    it runs to the latest drawn end, and off_axis stays 0. Every bar is placed inside the axis, with left and width
    in percent and the width at least MIN_BAR_PCT. With spec.year the axis is that calendar year and nothing is clipped:
    the rows overlapping it take the cap, and every row entirely before or after it counts in off_axis."""
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
    if spec.year is not None:  # a year window: rows outside it are not drawn and take no cap
        first = date(spec.year, 1, 1)
        last = date(spec.year, 12, 31)
        clipped = False
        inside = [(row, start, end) for row, start, end in dated if end >= first and start <= last]
        off_axis = len(dated) - len(inside)  # every row outside the window, drawn or not
        on_axis = inside[:TIMELINE_CAP]
    else:
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
                groups=_groups(rows, spec.group, []) if spec.group is not None else [],
            )
        first = min(start for _, start, _ in drawn)
        latest = max(end for _, _, end in drawn)
        if spec.all_years:  # «Бүгд»: every drawn date is on the axis
            clipped = False
            last = latest
            on_axis = drawn
            off_axis = 0
        else:
            limit = _years_later(first, TIMELINE_YEARS)
            clipped = latest > limit
            last = limit if clipped else latest
            on_axis = [(row, start, end) for row, start, end in drawn if start <= last]
            off_axis = len(drawn) - len(on_axis)
    span = (last - first).days + 1
    items = make_items(table, [row for row, _, _ in on_axis], marks, today)
    bars: list[Bar] = []
    keyed: list[tuple[Bar, str]] = []  # each drawn bar with the text of its group
    for item, (row, start, end) in zip(items, on_axis, strict=True):
        start_c = min(max(start, first), last)
        end_c = min(max(end, start_c), last)
        left = (start_c - first).days / span * 100
        width = ((end_c - start_c).days + 1) / span * 100
        left = min(max(left, 0.0), 100.0 - MIN_BAR_PCT)
        width = min(max(width, MIN_BAR_PCT), 100.0 - left)
        bar = Bar(item=item, start=start, end=end, left_pct=left, width_pct=width)
        bars.append(bar)
        keyed.append((bar, _group_key(spec.group, row) if spec.group is not None else ""))
    groups: list[BarGroup] = []
    if spec.group is not None:
        groups = _groups(rows, spec.group, keyed)
        bars = [bar for group in groups for bar in group.bars]
    today_pct = (today - first).days / span * 100 if first <= today <= last else None
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
        ticks=_axis_ticks(first, last),
        today_pct=today_pct,
        groups=groups,
    )


CHART_CAP = 30  # categories drawn in the chart, the last one «Бусад» included
PIVOT_ROW_CAP = 30  # pivot rows drawn, the last one «Бусад» included
PIVOT_COL_CAP = 12  # pivot columns drawn, the last one «Бусад» included
STACK_CAP = 7  # stacks of a stacked bar, the last one «Бусад» included (the chart palette has 7 colours)
MAX_FILLED_BUCKETS = 120  # a date axis gets its empty buckets up to this many; wider, only buckets with rows
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
class Series:
    """One stack of a stacked bar: its label (a value of the second category) and its value in each category, in the
    order of Chart.points."""

    label: str
    values: list[object]


@dataclass(frozen=True)
class Chart:
    """The chart: its kind (a key of CHARTS), the points in category order, the value's label and whether categories
    were folded into FOLDED. A stacked bar also has its series; its points are the totals over all the rows of each
    category, aggregated from the rows and not added up from the series."""

    kind: str
    points: list[Point]
    value_label: str
    folded: bool
    series: list[Series] = field(default_factory=list)
    keys: list[str | None] = field(default_factory=list)  # the raw category key of each point, None for «Бусад»
    series_keys: list[str | None] = field(default_factory=list)  # the raw key of each series; empty when not stacked
    masked: bool = False  # True when a drawn money figure was hidden for a group under privacy.min_group()
    percent: bool = False  # True when the figures are percents of a total (lshow); money is then False

    @property
    def lines(self) -> list[tuple[Point, list[object]]]:
        """One line per category for the data table: the point and its value in each series (a template cannot index
        two lists by the loop counter)."""
        return [(point, [s.values[i] for s in self.series]) for i, point in enumerate(self.points)]


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
    row_keys: list[str | None] = field(default_factory=list)  # the raw key of each row label, None for «Бусад»
    col_keys: list[str | None] = field(default_factory=list)  # the raw key of each column label; [None] without by2
    masked: bool = False  # True when a drawn money figure was hidden for a group under privacy.min_group()
    percent: bool = False  # True when the figures are percents of a total (lshow); money is then False


def date_bucket(value: object, grain: str) -> str:
    """The bucket of a date for a grain: "month" gives 2026-03, "quarter" 2026-Q1, "year" 2026. A datetime uses its
    day. A blank or non-date value gives "". An unknown grain gives the day as YYYY-MM-DD."""
    day = _as_date(value)
    if day is None:
        return ""
    if grain == "month":
        return f"{day.year:04d}-{day.month:02d}"
    if grain == "quarter":
        return f"{day.year:04d}-Q{(day.month - 1) // 3 + 1}"
    if grain == "year":
        return f"{day.year:04d}"
    return day.isoformat()


def _key(column: Column | None, row: Any, grain: str = "") -> str:
    """The category text of a row, as the table groups it; no column gives the blank text for every row. With a grain
    and a date column the text is the date's bucket (date_bucket)."""
    if column is None:
        return ""
    if grain and column.kind == "date":
        return date_bucket(column.value(row), grain)
    return _text(column.value(row))


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


def _drawn_keys(keys: Sequence[str], cap: int) -> list[str | None]:
    """The raw key behind each label _plan draws, in the same order. The folded «Бусад» bucket has no one key: None."""
    order = _order(keys)
    if len(order) <= cap:
        return list(order)
    return [*order[: cap - 1], None]


_BUCKET_PATTERN = {
    "month": re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])"),
    "quarter": re.compile(r"([0-9]{4})-Q([1-4])"),
    "year": re.compile(r"([0-9]{4})"),
}  # the text of a bucket key for each grain (date_bucket)


def _bucket_number(key: str, grain: str) -> int | None:
    """The place of a bucket key on the time line (a count of months, quarters or years), or None when the key is not
    a bucket of the grain."""
    pattern = _BUCKET_PATTERN.get(grain)
    match = pattern.fullmatch(key) if pattern is not None else None
    if match is None:
        return None
    year = int(match.group(1))
    if grain == "year":
        return year
    return year * (12 if grain == "month" else 4) + int(match.group(2)) - 1


def _bucket_text(number: int, grain: str) -> str:
    """The bucket key of a place on the time line; the inverse of _bucket_number."""
    if grain == "year":
        return f"{number:04d}"
    if grain == "quarter":
        year, part = divmod(number, 4)
        return f"{year:04d}-Q{part + 1}"
    year, part = divmod(number, 12)
    return f"{year:04d}-{part + 1:02d}"


def _time_order(keys: Sequence[str], grain: str) -> list[str]:
    """The distinct keys of a date axis in time order, the blank key last. When every key is a bucket of the grain, the
    empty buckets between the first and last one are added, if they number at most MAX_FILLED_BUCKETS; a wider span
    keeps only the buckets with rows. A key that is not a bucket of the grain gives the plain text order (_order)."""
    numbers: dict[str, int] = {}
    for key in keys:
        if key == "":
            continue
        number = _bucket_number(key, grain)
        if number is None:
            return _order(keys)
        numbers[key] = number
    if not numbers:
        return _order(keys)
    first, last = min(numbers.values()), max(numbers.values())
    if last - first + 1 <= MAX_FILLED_BUCKETS:
        buckets = [_bucket_text(number, grain) for number in range(first, last + 1)]
    else:
        buckets = sorted(numbers, key=numbers.__getitem__)
    return buckets + ([""] if "" in keys else [])


def _time_plan(keys: Sequence[str], cap: int, grain: str) -> tuple[list[str], dict[str, int], bool]:
    """_plan for a date axis: the buckets in time order (_time_order), gaps filled. Beyond cap buckets the oldest fold
    into FOLDED, which is drawn first; the newest cap-1 buckets (the blank one last) are drawn after it."""
    order = _time_order(keys, grain)
    if len(order) <= cap:
        return [_label(k) for k in order], {k: i for i, k in enumerate(order)}, False
    split = len(order) - (cap - 1)
    index = {k: 0 for k in order[:split]}
    index.update({k: i + 1 for i, k in enumerate(order[split:])})
    return [FOLDED, *(_label(k) for k in order[split:])], index, True


def _time_drawn_keys(keys: Sequence[str], cap: int, grain: str) -> list[str | None]:
    """The raw key behind each label _time_plan draws, in the same order. The folded FOLDED bucket is None."""
    order = _time_order(keys, grain)
    if len(order) <= cap:
        return list(order)
    return [None, *order[len(order) - (cap - 1) :]]


def _is_timed(column: Column | None, grain: str) -> bool:
    """True when a category is a date column bucketed by a grain, so its axis runs in time order."""
    return bool(grain) and column is not None and column.kind == "date"


def _axis_plan(
    column: Column | None, keys: Sequence[str], cap: int, grain: str
) -> tuple[list[str], dict[str, int], bool]:
    """_time_plan for a date category with a grain, else _plan."""
    if _is_timed(column, grain):
        return _time_plan(keys, cap, grain)
    return _plan(keys, cap)


def _axis_drawn(column: Column | None, keys: Sequence[str], cap: int, grain: str) -> list[str | None]:
    """_time_drawn_keys for a date category with a grain, else _drawn_keys."""
    if _is_timed(column, grain):
        return _time_drawn_keys(keys, cap, grain)
    return _drawn_keys(keys, cap)


def _label(key: str) -> str:
    return key if key.strip() != "" else EMPTY_GROUP


def _measure(rows: Sequence[Any], value: tuple[Column | None, str]) -> object:
    """The value of one bucket: its row count for count (or no column), else the aggregate over the column's values.
    A money figure over too few rows is None (privacy.masked): one person's pay is not shown."""
    column, agg = value
    if column is None or agg == "count":
        return len(rows)
    if privacy.masked(value, rows):
        return None
    return totals_mod.aggregate([column.value(row) for row in rows], agg)


def _figure(rows: Sequence[Any], value: tuple[Column | None, str]) -> tuple[object, bool]:
    """_measure of one bucket and whether its figure was hidden, so a chart or pivot knows it dropped one."""
    return _measure(rows, value), privacy.masked(value, rows)


def _is_money(value: tuple[Column | None, str]) -> bool:
    column, agg = value
    return column is not None and column.money and agg != "count"


def _value_label(value: tuple[Column | None, str], percent: bool = False) -> str:
    column, agg = value
    if column is None or agg == "count":
        label = AGG_TEXT["count"]
    else:
        label = f"{column.label} ({AGG_TEXT.get(agg, agg)})"
    return f"{label} (%)" if percent else label


def _summed(value: tuple[Column | None, str]) -> bool:
    """True when the value adds up a column: a column with an aggregate other than the count (none is the count)."""
    return value[0] is not None and value[1] != "count"


def _board_column(spec: LayoutSpec) -> bool:
    """True when a board sums a column (lval names one); the board's plain count is not written to the address."""
    return spec.layout == "board" and _summed(spec.value)


def value_caption(value: tuple[Column | None, str]) -> str:
    """The name of the value in use (the board's «Утга: …» caption), or "" for the plain count (nothing is shown)."""
    if value[0] is None or value[1] == "count":
        return ""
    return _value_label(value)


def _percentable(value: tuple[Column | None, str]) -> bool:
    """A percent applies to a count or a sum only; an average, a minimum and a maximum keep their own figures."""
    column, agg = value
    return column is None or agg in ("count", "sum")


def _share(figure: object, total: object) -> object:
    """A figure as a percent of a total: 0 to 100, one decimal. None when either is None or the total is 0."""
    if figure is None or total is None or total == 0:
        return None
    return round(float(cast(SupportsFloat, figure)) * 100 / float(cast(SupportsFloat, total)), 1)


def _shown(figure: tuple[object, bool], percent: bool, total: object, hide: bool = False) -> tuple[object, bool]:
    """A bucket's figure as drawn: its share of total when percent (None when hide), else the figure itself."""
    if not percent:
        return figure
    return (None if hide else _share(figure[0], total), figure[1])


def _pivot_shares(
    show: str,
    cells: list[list[tuple[object, bool]]],
    row_totals: list[tuple[object, bool]],
    col_totals: list[tuple[object, bool]],
    grand: tuple[object, bool],
    hide: bool = False,
) -> tuple[list[list[tuple[object, bool]]], list[tuple[object, bool]], list[tuple[object, bool]], tuple[object, bool]]:
    """The figures of a percent pivot. A cell is its share of the grand total (pct), of its row total (rowpct) or of its
    column total (colpct). A total is its share of what it adds up to: a row total of the grand total, except in rowpct
    where it is 100 (its own row); a column total likewise, except in colpct. The grand total is 100, or None. With hide
    every figure is None (a money share would give back a hidden figure)."""
    total = grand[0]

    def cell_base(i: int, j: int) -> object:
        if show == "rowpct":
            return row_totals[i][0]
        if show == "colpct":
            return col_totals[j][0]
        return total

    new_cells = [[_shown(f, True, cell_base(i, j), hide) for j, f in enumerate(line)] for i, line in enumerate(cells)]
    new_rows = [_shown(f, True, f[0] if show == "rowpct" else total, hide) for f in row_totals]
    new_cols = [_shown(f, True, f[0] if show == "colpct" else total, hide) for f in col_totals]
    return new_cells, new_rows, new_cols, _shown(grand, True, total, hide)


def _sort_order(spec: LayoutSpec, keys: Sequence[str | None], values: Sequence[object]) -> list[int]:
    """The order of the chart's points for lsort: the figures high to low (value) or low to high (valueasc). A None
    figure comes after every number, then the blank «—» category, then the folded «Бусад» last. A line chart and a date
    category keep the category order. Ties keep the category order (a stable sort)."""
    count = len(values)
    if spec.sort not in ("value", "valueasc") or spec.chart == "line" or _is_timed(spec.by, spec.grain):
        return list(range(count))
    folded = [i for i in range(count) if keys[i] is None]
    blank = [i for i in range(count) if keys[i] is not None and (keys[i] or "").strip() == ""]
    named = [i for i in range(count) if keys[i] is not None and (keys[i] or "").strip() != ""]
    figured = sorted(
        (i for i in named if values[i] is not None),
        key=lambda i: cast("SupportsRichComparison", values[i]),
        reverse=spec.sort == "value",
    )
    unfigured = [i for i in named if values[i] is None]
    return figured + unfigured + blank + folded


def build_chart(table: TableLike, spec: LayoutSpec) -> Chart:
    """The chart of the filtered rows: one point per category (spec.by) in table order, the value from spec.value over
    every row of the category. Beyond CHART_CAP categories the rest fold into FOLDED, aggregated over their rows.
    A percent (lshow pct) is each figure's share of the grand total; a percent of a money sum is None everywhere
    once any figure is hidden (privacy), because the shares would give the hidden one back."""
    rows = table.rows
    keys = [_key(spec.by, row, spec.grain) for row in rows]
    labels, index, folded = _axis_plan(spec.by, keys, CHART_CAP, spec.grain)
    members: list[list[Any]] = [[] for _ in labels]
    for row, key in zip(rows, keys, strict=True):
        members[index[key]].append(row)
    money = _is_money(spec.value)
    percent = spec.show == "pct" and _percentable(spec.value)
    total = _figure(rows, spec.value)
    figures = [_figure(group, spec.value) for group in members]
    kind, series, series_keys = spec.chart, [], []
    stack_labels: list[str] = []
    cells: list[list[tuple[object, bool]]] = []
    if kind == "stacked":
        if spec.by2 is None:  # no second category to split by: a plain bar
            kind = "bar"
        else:
            stack_keys = [_key(spec.by2, row, spec.grain) for row in rows]
            series_keys = _axis_drawn(spec.by2, stack_keys, STACK_CAP, spec.grain)
            stack_labels, stack_index, stack_folded = _axis_plan(spec.by2, stack_keys, STACK_CAP, spec.grain)
            grid: list[list[list[Any]]] = [[[] for _ in labels] for _ in stack_labels]
            for row, key, stack_key in zip(rows, keys, stack_keys, strict=True):
                grid[stack_index[stack_key]][index[key]].append(row)
            cells = [[_figure(cell, spec.value) for cell in line] for line in grid]
            folded = folded or stack_folded
    hidden = any(was for _, was in [*figures, *(cell for line in cells for cell in line)])
    hide = percent and money and (hidden or total[1])
    shown = [_shown(f, percent, total[0], hide) for f in figures]
    points = [
        Point(label=label, value=value, money=money and not percent)
        for label, (value, _) in zip(labels, shown, strict=True)
    ]
    series = [
        Series(label=label, values=[_shown(f, percent, total[0], hide)[0] for f in line])
        for label, line in zip(stack_labels, cells, strict=True)
    ]
    point_keys = _axis_drawn(spec.by, keys, CHART_CAP, spec.grain)
    order = _sort_order(spec, point_keys, [p.value for p in points])
    points = [points[i] for i in order]
    series = [Series(label=s.label, values=[s.values[i] for i in order]) for s in series]
    return Chart(
        kind=kind,
        points=points,
        value_label=_value_label(spec.value, percent),
        folded=folded,
        series=series,
        keys=[point_keys[i] for i in order],
        series_keys=series_keys,
        masked=hidden,
        percent=percent,
    )


def build_pivot(table: TableLike, spec: LayoutSpec) -> Pivot:
    """The pivot of the filtered rows: rows by spec.by, columns by spec.by2 (one column «Нийт» without it), each cell
    the value over its rows. Rows fold past PIVOT_ROW_CAP, columns past PIVOT_COL_CAP; totals are aggregated over the
    rows, never added up from the cells."""
    rows = table.rows
    row_keys = [_key(spec.by, row, spec.grain) for row in rows]
    col_keys = [_key(spec.by2, row, spec.grain) for row in rows]
    row_labels, row_index, _ = _axis_plan(spec.by, row_keys, PIVOT_ROW_CAP, spec.grain)
    if spec.by2 is None:
        col_labels, col_index = [TOTAL_COLUMN], {"": 0}
    else:
        col_labels, col_index, _ = _axis_plan(spec.by2, col_keys, PIVOT_COL_CAP, spec.grain)
    grid: list[list[list[Any]]] = [[[] for _ in col_labels] for _ in row_labels]
    row_members: list[list[Any]] = [[] for _ in row_labels]
    col_members: list[list[Any]] = [[] for _ in col_labels]
    for row, rk, ck in zip(rows, row_keys, col_keys, strict=True):
        r, c = row_index[rk], col_index[ck]
        grid[r][c].append(row)
        row_members[r].append(row)
        col_members[c].append(row)
    cells = [[_figure(cell, spec.value) for cell in line] for line in grid]
    row_totals = [_figure(group, spec.value) for group in row_members]
    col_totals = [_figure(group, spec.value) for group in col_members]
    grand = _figure(rows, spec.value)
    every = [*(f for line in cells for f in line), *row_totals, *col_totals, grand]
    percent = spec.show in SHOWS and _percentable(spec.value)
    hide = percent and _is_money(spec.value) and any(was for _, was in every)  # see build_chart
    if percent:
        cells, row_totals, col_totals, grand = _pivot_shares(spec.show, cells, row_totals, col_totals, grand, hide)
    return Pivot(
        row_labels=row_labels,
        col_labels=col_labels,
        cells=[[value for value, _ in line] for line in cells],
        row_totals=[value for value, _ in row_totals],
        col_totals=[value for value, _ in col_totals],
        grand=grand[0],
        money=_is_money(spec.value) and not percent,
        value_label=_value_label(spec.value, percent),
        row_keys=_axis_drawn(spec.by, row_keys, PIVOT_ROW_CAP, spec.grain),
        col_keys=_axis_drawn(spec.by2, col_keys, PIVOT_COL_CAP, spec.grain) if spec.by2 is not None else [None],
        masked=any(was for _, was in every),
        percent=percent,
    )
