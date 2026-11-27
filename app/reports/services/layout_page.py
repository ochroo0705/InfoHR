"""The report's layout parts, request-free: the click-through address of a category («drill_url»), the layout bar's
hidden inputs and its selects («layout_bar»): which selects the bar draws for a layout, in the template's order, with
their labels, options and the value each one shows now. The Django report page draws the bar from the template
(_layout_bar.html) and the React API reads the model; a test keeps the two equal, so a rule has one home. Nothing here
reads a request: the caller passes the path, the filters, the layout spec and the viewer."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from accounts.models import User
from config import batching
from django.http import QueryDict
from django.template.defaultfilters import floatformat
from django.utils import timezone
from employees.images import attach_photo_digests
from employees.templatetags.hr import mnt, thumb

from reports import drill, privacy
from reports import layouts as layouts_mod
from reports import marks as marks_mod
from reports import rules as rules_mod
from reports.drill import collisions as drill_collisions
from reports.filters import MAX_YEAR, MIN_MONTH_YEAR, Filters, to_query
from reports.kinds import column_kind
from reports.layouts import LayoutSpec
from reports.page_rules import address, month_param
from reports.services.page_head import NEW_LAYOUT_BLANKS
from reports.table import Table
from reports.types import Column, Report

CHART_LABELS = {  # the chart kinds of the layout bar
    "bar": "Баганан",
    "stacked": "Давхарласан баганан",
    "line": "Шугаман",
    "donut": "Дугуй",
}
LAYOUT_BAR_OWN_BLANKS: dict[str, Any] = {
    name: value for name, value in NEW_LAYOUT_BLANKS.items() if name not in ("lweek", "lyear")
}


@dataclass(frozen=True)
class BarSelect:
    """One select of the layout bar: its parameter name, its label, the value it shows now ("" = none chosen) and
    its options as (value, text) pairs, in the order the bar draws them."""

    name: str
    label: str
    selected: str
    options: list[tuple[str, str]]


@dataclass(frozen=True)
class LayoutBar:
    """The layout bar: the hidden inputs (every parameter the bar has no select for, and the column filters added by
    «add») and the selects drawn for this layout."""

    layout: str
    keep: list[tuple[str, str]]
    selects: list[BarSelect]


def drill_url(
    path: str,
    f: Filters,
    adds: Sequence[str],
    plain: bool,
    pairs: Sequence[tuple[Column | None, str | None]],
    kinds: dict[str, str],
    grains: dict[str, str],
) -> str:
    """The table's address for the rows of these (column, category key) pairs: the layout is dropped and one rule per
    pair is added to the rules. "" when a pair has no key (the folded «Бусад»), no column, or the rules would not fit:
    the caller then draws plain text. A date column with a grain (in grains) keeps its bucket's «between» rule."""
    conditions: list[rules_mod.Rule] = []
    for column, key in pairs:
        if column is None or key is None:
            return ""
        grain = grains.get(column.key, "")
        if grain:
            condition = drill.bucket_condition(column.key, grain, key)
        else:
            condition = drill.condition(column.key, kinds[column.key], key)
        if condition is None:
            return ""
        conditions.append(condition)
    rules = drill.drill_rules(f.rules, conditions)
    if rules == "":
        return ""
    cleared = replace(f, rules=rules, layout="", lby="", lby2="", lval="", lchart="", lmonth="", **NEW_LAYOUT_BLANKS)
    return address(path, cleared, adds, plain=plain)


@dataclass(frozen=True)
class LinkBase:
    """What a drill address needs besides the category pairs: the report's path, its filters, the column filters added
    with «add», and whether the page is plain (the no-script address form). The caller builds it from the request."""

    path: str
    f: Filters
    adds: tuple[str, ...]
    plain: bool


@dataclass(frozen=True)
class Drill:
    """The click-through of a category layout (chart, pivot, board). Calling it with (column, key) pairs gives the
    table address of those rows (drill_url; «» for none). `unless` drops the link of a key that must not get one: a
    colliding key, or the blank bucket of a grained date category. `by_bad` and `by2_bad` are the colliding keys of the
    first and second category, `by_grained` and `by2_grained` say whether that category is a grained date. A pivot
    reads the second category's fields for its columns and the first's for its rows."""

    link: LinkBase
    kinds: dict[str, str]
    grains: dict[str, str]
    by_bad: frozenset[str]
    by2_bad: frozenset[str]
    by_grained: bool
    by2_grained: bool

    def __call__(self, pairs: Sequence[tuple[Column | None, str | None]]) -> str:
        return drill_url(self.link.path, self.link.f, self.link.adds, self.link.plain, pairs, self.kinds, self.grains)

    def unless(self, key: str | None, colliding: frozenset[str] | set[str], grained: bool = False) -> str | None:
        """The key to link by, or None when it gets no link: a colliding key, or the blank «—» bucket of a grained date
        category (its rows are the blank dates, not one value)."""
        return None if key in colliding or (grained and key == "") else key


def drill_for(table: layouts_mod.TableLike, spec: LayoutSpec, link_base: LinkBase) -> Drill:
    """The drill of this table's layout: the column kinds and grains of the categories, and the colliding keys over
    EVERY filtered row (folded «Бусад» rows included: their rows match a colliding rule too). Collisions are only
    worked out for the category layouts (layouts.CATEGORY_LAYOUTS); other layouts get empty sets."""
    kinds = {c.key: column_kind(c, table.rows) for c in (spec.by, spec.by2) if c is not None}
    grains = {c.key: spec.grain for c in (spec.by, spec.by2) if c is not None and c.kind == "date" and spec.grain}
    by_bad: frozenset[str] = frozenset()
    by2_bad: frozenset[str] = frozenset()
    if spec.layout in layouts_mod.CATEGORY_LAYOUTS:
        by_bad = frozenset(drill_collisions(layouts_mod._key(spec.by, row, spec.grain) for row in table.rows))
        by2_bad = frozenset(drill_collisions(layouts_mod._key(spec.by2, row, spec.grain) for row in table.rows))
    return Drill(
        link=link_base,
        kinds=kinds,
        grains=grains,
        by_bad=by_bad,
        by2_bad=by2_bad,
        by_grained=spec.grain != "" and spec.by is not None and spec.by.kind == "date",
        by2_grained=spec.grain != "" and spec.by2 is not None and spec.by2.kind == "date",
    )


def layout_bar(
    report: Report,
    user: User,
    spec: LayoutSpec,
    f: Filters,
    adds: list[str],
    dated: bool,
    sort_ok: bool,
) -> LayoutBar:
    """The layout bar for this layout. `dated`: a chart or pivot groups by a date column (the «Хуваалт» select);
    `sort_ok`: the chart's «Эрэмбэ» select applies (not a dated category with a grain)."""
    layout = spec.layout
    by_key = spec.by.key if spec.by else ""
    by2_key = spec.by2.key if spec.by2 else ""
    choices = layouts_mod.layout_choices(report, user, layout, by_key)
    keep = parse_qsl(to_query(replace(f, layout="", lby="", lby2="", lval="", lchart="", **LAYOUT_BAR_OWN_BLANKS)))
    selects: list[BarSelect] = []

    if layout in ("board", "chart", "pivot"):
        selects.append(BarSelect("lby", "Мөр" if layout == "pivot" else "Ангилал", by_key, choices.by))
    if layout == "board":
        selects.append(BarSelect("lorder", "Эрэмбэ", spec.order, [("", "Анхны дараалал"), ("count", "Тоогоор")]))
    if layout == "pivot":
        selects.append(BarSelect("lby2", "Багана", by2_key, choices.by2))
    if layout in ("calendar", "timeline"):
        selects.append(BarSelect("lby", "Огноо" if layout == "calendar" else "Эхлэх", by_key, choices.by))
        end_options = choices.by2
        if layout == "calendar":  # a calendar entry has no end unless one is chosen
            end_options = [("", "—"), *choices.by2]
        selects.append(BarSelect("lby2", "Дуусах", by2_key, end_options))
    if layout == "timeline":
        group_key = spec.group.key if spec.group else ""
        selects.append(BarSelect("lgroup", "Бүлэглэх", group_key, [("", "—"), *choices.group]))
    if layout == "calendar":
        repeat_options = [("", "Автомат"), ("1", "Тийм"), ("0", "Үгүй")]
        selects.append(BarSelect("lrep", "Давтах", f.lrep, repeat_options))
    if layout in ("board", "chart", "pivot"):
        selects.append(BarSelect("lval", "Утга", layouts_mod.value_text(spec.value), choices.value))
    if layout == "pivot":
        value2 = layouts_mod.value_text(spec.value2) if spec.value2 is not None else ""
        selects.append(BarSelect("lval2", "Утга 2", value2, [("", "—"), *choices.value]))
    if layout == "chart" and spec.chart == "stacked" and spec.by2 is not None:
        selects.append(BarSelect("lby2", "Хуваах", by2_key, choices.by2))
    if layout in ("chart", "pivot"):
        show_options = [("", "Тоо / үнэ"), ("pct", "Нийтийн %")]
        if layout == "pivot":
            show_options += [("rowpct", "Мөрийн %"), ("colpct", "Баганын %")]
        selects.append(BarSelect("lshow", "Харуулах", spec.show, show_options))
        if dated:
            grain_options = [("month", "Сар"), ("quarter", "Улирал"), ("year", "Жил")]
            selects.append(BarSelect("lgrain", "Хуваалт", spec.grain, grain_options))
    if layout == "chart" and sort_ok:
        sort_options = [("", "Ангилалаар"), ("value", "Утгаар буурах"), ("valueasc", "Утгаар өсөх")]
        selects.append(BarSelect("lsort", "Эрэмбэ", spec.sort, sort_options))
    if layout == "chart":
        selects.append(BarSelect("lchart", "Диаграм", spec.chart, list(CHART_LABELS.items())))

    return LayoutBar(layout=layout, keep=keep + [("add", name) for name in adds], selects=selects)


CARD_EXTRAS = (
    4  # the shown columns after the title and subtitle, drawn as label: value lines on a card (views.CARD_EXTRAS)
)
CARD_PHOTO_SIDE = 72  # the card's photo square in px (the template's thumb:72)
OFFSET_DIGITS = 18  # a longer offset is not a batch number: it starts at 0 (as config.batching reads it)


@dataclass(frozen=True)
class ExtraOut:
    """One label: value line of a card or a board card, finished as the page prints it. `text` is money by mnt
    («2,500,000₮», «—» when none), a date as ISO, else the value's text ("" for none). `href` is the mailto: or tel:
    link of a contact column, "" when there is none (money and dates are never links)."""

    label: str
    text: str
    href: str


@dataclass(frozen=True)
class CardOut:
    """One card of a board or the cards layout. `photo_url` is the photo's 72 px thumbnail ("" without a photo);
    `photo_initial` is the first letter of the given name for the soft tile shown when there is a photo slot but no
    image, else ""."""

    title: str
    subtitle: str
    href: str
    mark: str
    extras: list[ExtraOut]
    photo_url: str
    photo_initial: str
    photo_srcset: str  # the 2x and 3x thumbnails of the photo («url 2x, url 3x»), "" without an image


@dataclass(frozen=True)
class LaneOut:
    """One board lane: its label, its filtered row count, its figure text ("" when the value is the count), its
    category link ("" for none) and its drawn cards."""

    label: str
    count: int
    figure: str
    href: str
    cards: list[CardOut]


@dataclass(frozen=True)
class BoardOut:
    """The board: its lanes, the filtered row count, the cards drawn, the cap and the value caption ("" = the count)."""

    lanes: list[LaneOut]
    total: int
    shown: int
    cap: int
    value_label: str


@dataclass(frozen=True)
class CardsOut:
    """The cards layout's batch: its cards, the offset of the next batch (None when it is the last) and every row."""

    items: list[CardOut]
    next_offset: int | None
    total: int


def _extra_text(value: Any, money: bool) -> str:
    """The text a card's extra prints: money by mnt, a date as ISO (a datetime in local time), else the value's text."""
    if money:
        return mnt(value)
    if isinstance(value, datetime):
        value = timezone.localtime(value) if timezone.is_aware(value) else value
    if isinstance(value, date):
        return f"{value:%Y-%m-%d}"
    return "" if value is None else str(value)


def _card(item: layouts_mod.Item) -> CardOut:
    """The request-free card of one item: its extras finished as text, its photo thumbnail and initial."""
    extras = [
        ExtraOut(
            label=label,
            text=_extra_text(value, money),
            href="" if money or isinstance(value, date) else href,
        )
        for label, value, money, href in item.extras_linked
    ]
    photo_url = thumb(item.photo, CARD_PHOTO_SIDE) if item.photo is not None else ""
    photo_initial = str(item.photo.given_name or "")[:1] if item.photo is not None and not photo_url else ""
    photo_srcset = f"{thumb(item.photo, 144)} 2x, {thumb(item.photo, 216)} 3x" if photo_url else ""
    return CardOut(
        title=item.title,
        subtitle=item.subtitle,
        href=item.href,
        mark=item.mark,
        extras=extras,
        photo_url=photo_url,
        photo_initial=photo_initial,
        photo_srcset=photo_srcset,
    )


def _figure_text(value: Any, money: bool) -> str:
    """A lane's figure as the board prints it: money by mnt (None gives «—»), else the figure's text, «—» for none."""
    if money:
        return mnt(value)
    return "—" if value is None else str(value)


def board_page(
    table: layouts_mod.TableLike,
    spec: LayoutSpec,
    marks: Sequence[Any],
    today: date,
    drill: Callable[[list[tuple[Column | None, str | None]]], str],
) -> BoardOut:
    """The board of the filtered rows, as the page draws it. `drill(pairs)` gives the table address of the rows of
    these (column, category key) pairs («»=no link); a lane's key colliding with another key, or the blank bucket of a
    grained date category, gets no link (as the Django view does). The figure text is set only when the value adds up
    a column."""
    board = layouts_mod.build_board(table, spec, marks, today)
    grained = spec.grain != "" and spec.by is not None and spec.by.kind == "date"
    colliding = drill_collisions(layouts_mod._key(spec.by, row, spec.grain) for row in table.rows)
    summed = layouts_mod._summed(spec.value)
    lanes: list[LaneOut] = []
    for lane in board.lanes:
        key = None if lane.key in colliding or (grained and lane.key == "") else lane.key
        lanes.append(
            LaneOut(
                label=lane.label,
                count=lane.count,
                figure=_figure_text(lane.figure, lane.money) if summed else "",
                href=drill([(spec.by, key)]),
                cards=[_card(item) for item in lane.items],
            )
        )
    return BoardOut(
        lanes=lanes,
        total=board.total,
        shown=board.shown,
        cap=board.cap,
        value_label=layouts_mod.value_caption(spec.value),
    )


def cards_page(
    table: layouts_mod.TableLike,
    report: Report,
    marks: Sequence[Any],
    today: date,
    offset: int,
) -> CardsOut:
    """The cards of one batch: the rows as cards, from `offset` (a negative or huge one starts at 0), with the offset
    of the next batch. The photos of the batch's people get their thumbnails in one query (attach_photo_digests)."""
    items = layouts_mod.make_items(table, table.rows, marks, today, extras=CARD_EXTRAS, photo_of=report.photo)
    start = offset if 0 <= offset < 10**OFFSET_DIGITS else 0
    batch = batching.batch_at(items, start)
    if report.photo is not None:
        attach_photo_digests(i.photo for i in batch.shown if i.photo is not None)
    next_offset = start + batching.LIST_BATCH if batch.next_query else None
    return CardsOut(items=[_card(item) for item in batch.shown], next_offset=next_offset, total=len(items))


@dataclass(frozen=True)
class EntryOut:
    """One calendar entry as the page prints it: its title, the title's link ("" for none), the CSS classes of its
    first passing mark ("" for none) and its note («36 жил» for a repeated yearly entry, else "")."""

    title: str
    href: str
    mark: str
    note: str


@dataclass(frozen=True)
class DayOut:
    """One day of the grid or the week: its ISO date and day of the month, whether it is in the shown month, whether it
    is today, its entries (at most the cap), the count of the rest and the link of that count ("" = plain text)."""

    iso: str
    number: int
    in_month: bool
    is_today: bool
    entries: list[EntryOut]
    more: int
    more_href: str


@dataclass(frozen=True)
class CalendarOut:
    """The calendar page: the month grid (`weeks`, mode "month") or the week (`days`, mode "week"). `prev_href` and
    `next_href` are "" when the arrow is disabled at the year bound. `month_value` is «YYYY-MM» in month mode, else "".
    `keep` are the hidden inputs of the month picker (every parameter but lmonth, and the column filters added)."""

    mode: Literal["month", "week"]
    heading: str
    weeks: list[list[DayOut]]
    days: list[DayOut]
    undated: int
    prev_href: str
    next_href: str
    today_href: str
    switch_href: str
    month_value: str
    keep: list[tuple[str, str]]
    total: int


def _entry_out(item: layouts_mod.Item) -> EntryOut:
    return EntryOut(title=item.title, href=item.href, mark=item.mark, note=item.note)


def _day_out(day: layouts_mod.Day, more_href: str) -> DayOut:
    """One day as the page prints it; a «+N» count has its link only when the caller gives one."""
    return DayOut(
        iso=day.day.isoformat(),
        number=day.day.day,
        in_month=day.in_month,
        is_today=day.is_today,
        entries=[_entry_out(item) for item in day.items],
        more=day.more,
        more_href=more_href if day.more else "",
    )


def calendar_page(
    table: layouts_mod.TableLike,
    spec: LayoutSpec,
    marks: Sequence[Any],
    today: date,
    link: Callable[..., str],
) -> CalendarOut:
    """The calendar of the filtered rows: the week of spec.week when set, else the month of spec.month. `link(**over)`
    gives the report address with the filters replaced by `over` (the view's `_address(path, replace(f, …), adds)`).
    The «+N» link of a month cell is the week of that day; a week view's «+N» is plain text, as the template has it."""
    keep = parse_qsl(urlsplit(link(lmonth="")).query)  # the month picker's hidden inputs: every filter but lmonth
    total = len(table.rows)
    if spec.week is not None:
        week = layouts_mod.build_week(table, spec, marks, today)
        start = week.start.isoformat()
        return CalendarOut(
            mode="week",
            heading=f"{start} – {week.end.isoformat()}",
            weeks=[],
            days=[_day_out(day, "") for day in week.days],
            undated=week.undated,
            prev_href="" if week.prev == start else link(lweek=week.prev, lmonth=""),
            next_href="" if week.next == start else link(lweek=week.next, lmonth=""),
            today_href=link(lweek=layouts_mod.week_start(today).isoformat(), lmonth=""),
            switch_href=link(lweek="", lmonth=month_param(week.start, today)),
            month_value="",
            keep=keep,
            total=total,
        )

    def week_href(day: date) -> str:
        """The address of the week that holds this day."""
        return link(lweek=layouts_mod.week_start(day).isoformat(), lmonth="")

    cal = layouts_mod.build_calendar(table, spec, marks, today)
    month_value = f"{cal.month.year:04d}-{cal.month.month:02d}"
    # the «7 хоног» link: the week of today when this month is the current one, else the week of the month's 1st
    anchor = today if (cal.month.year, cal.month.month) == (today.year, today.month) else cal.month
    return CalendarOut(
        mode="month",
        heading=f"{cal.month.year} оны {cal.month.month}-р сар",
        weeks=[[_day_out(day, week_href(day.day) if day.more else "") for day in week] for week in cal.weeks],
        days=[],
        undated=cal.undated,
        prev_href="" if cal.prev == month_value else link(lmonth=cal.prev),
        next_href="" if cal.next == month_value else link(lmonth=cal.next),
        today_href=link(lmonth=""),
        switch_href=week_href(anchor),
        month_value=month_value,
        keep=keep,
        total=total,
    )


@dataclass(frozen=True)
class TickOut:
    """One axis label and its place on the axis in percent."""

    label: str
    left_pct: float


@dataclass(frozen=True)
class BarOut:
    """One timeline bar as the page prints it: the title and its link ("" for none), the CSS classes of its first
    passing mark, its place on the axis and width in percent (plain floats), the aria text «title: from – to», and the
    hover text (tip_title, tip)."""

    title: str
    href: str
    mark: str
    left_pct: float
    width_pct: float
    label: str
    tip_title: str
    tip: str


@dataclass(frozen=True)
class BarGroupOut:
    """One timeline group: its label («—» for the blank group, "" when ungrouped), its row count and its bars."""

    label: str
    count: int
    bars: list[BarOut]


@dataclass(frozen=True)
class TimelineOut:
    """The timeline page. `first` and `last` are the axis dates as ISO ("" when no drawn row has a start). `year` is the
    year window (None for «Бүгд»); `year_prev_href` and `year_next_href` are None at the year bounds. `over_cap` counts
    the rows past the cap, `off_axis` the drawn rows outside a clipped or year-window axis, `undated` the blank starts,
    `clipped` whether the axis was cut to TIMELINE_YEARS years."""

    groups: list[BarGroupOut]
    ticks: list[TickOut]
    today_pct: float | None
    first: str
    last: str
    undated: int
    off_axis: int
    clipped: bool
    over_cap: int
    cap: int
    years: int
    total: int
    year: int | None
    year_prev_href: str | None
    year_next_href: str | None
    all_href: str
    enter_href: str


def _bar_out(bar: layouts_mod.Bar) -> BarOut:
    title = bar.item.title
    return BarOut(
        title=title,
        href=bar.item.href,
        mark=bar.item.mark,
        left_pct=bar.left_pct,
        width_pct=bar.width_pct,
        label=f"{title}: {bar.start:%Y-%m-%d} – {bar.end:%Y-%m-%d}",
        tip_title=title,
        tip=bar.tip,
    )


def timeline_page(
    table: layouts_mod.TableLike,
    spec: LayoutSpec,
    marks: Sequence[Any],
    today: date,
    link: Callable[..., str],
) -> TimelineOut:
    """The timeline of the filtered rows, as the page draws it. `link(**over)` gives the report address with the filters
    replaced by `over`. The year arrows step spec.year by one and stop at MIN_MONTH_YEAR and MAX_YEAR (None there);
    «Бүгд» sets lyear=all; «Он» opens the year of today, clamped to the allowed years."""
    timeline = layouts_mod.build_timeline(table, spec, marks, today)
    if spec.group is not None:
        groups = [
            BarGroupOut(label=group.label, count=group.count, bars=[_bar_out(bar) for bar in group.bars])
            for group in timeline.groups
        ]
    else:
        groups = [BarGroupOut(label="", count=timeline.total, bars=[_bar_out(bar) for bar in timeline.bars])]
    window = spec.year
    enter_year = min(max(today.year, MIN_MONTH_YEAR), MAX_YEAR)
    return TimelineOut(
        groups=groups,
        ticks=[TickOut(label=tick.label, left_pct=tick.left_pct) for tick in timeline.ticks],
        today_pct=timeline.today_pct,
        first=timeline.first.isoformat() if timeline.first is not None else "",
        last=timeline.last.isoformat() if timeline.last is not None else "",
        undated=timeline.undated,
        off_axis=timeline.off_axis,
        clipped=timeline.clipped,
        over_cap=timeline.over_cap,
        cap=timeline.cap,
        years=layouts_mod.TIMELINE_YEARS,
        total=timeline.total,
        year=window,
        year_prev_href=(link(lyear=str(window - 1)) if window is not None and window > MIN_MONTH_YEAR else None),
        year_next_href=(link(lyear=str(window + 1)) if window is not None and window < MAX_YEAR else None),
        all_href=link(lyear="all"),
        enter_href=link(lyear=str(enter_year)),
    )


def _number_or_none(value: object) -> float | None:
    """A chart value as a float for the drawing (views._number_or_none, kept here so the service does not import the
    view); None when there is nothing to aggregate or the value is not a number. The table text is exact."""
    return float(value) if isinstance(value, int | float | Decimal) else None


@dataclass(frozen=True)
class ChartRowOut:
    """One category of the chart: its text, its link ("" = none), its figure in each stack, and its total (the
    category's figure over all its rows), all as finished text. `cells` has one text per stack of a stacked bar, in
    the order of ChartOut.series_labels; it is empty for a plain bar or a donut (no stacks)."""

    label: str
    href: str
    cells: list[str]
    total: str


@dataclass(frozen=True)
class ChartSeriesOut:
    """One stack of a stacked bar: its label and its values for the drawing (one per category, None = no figure)."""

    label: str
    values: list[float | None]


@dataclass(frozen=True)
class ChartOut:
    """The chart as the page draws it: the table rows as text, and the same numbers as floats for the drawing (values,
    series), the hrefs per category, and the note of a hidden money figure ("" when nothing was hidden)."""

    kind: str
    kind_label: str
    value_label: str
    category_label: str
    series_labels: list[str]
    rows: list[ChartRowOut]
    labels: list[str]
    values: list[float | None]
    series: list[ChartSeriesOut]
    money: bool
    percent: bool
    hrefs: list[str]
    masked: bool
    note: str


def _chart_text(value: object, money: bool, percent: bool) -> str:
    """A chart figure as text (chart.html and _figure.html): a percent with one decimal and a «%», money by mnt, any
    other figure as it is; a missing figure is «—»."""
    if percent:
        return "—" if value is None else f"{floatformat(value, '1u')}%"  # the template's rule: one decimal, half up
    return _figure_text(value, money)


def chart_page(table: layouts_mod.TableLike, spec: LayoutSpec, drill: Drill) -> ChartOut:
    """The chart of the filtered rows, as the page draws it. Each category links to its rows through `drill`; a folded
    «Бусад», a colliding key or the blank bucket of a grained date category gets no link (drill.unless). A stacked
    bar's totals are aggregated over all rows of a category (layouts.build_chart), not added up from its stacks."""
    chart = layouts_mod.build_chart(table, spec)
    rows: list[ChartRowOut] = []
    hrefs: list[str] = []
    for i, point in enumerate(chart.points):
        href = drill([(spec.by, drill.unless(chart.keys[i], drill.by_bad, drill.by_grained))])
        hrefs.append(href)
        rows.append(
            ChartRowOut(
                label=point.label,
                href=href,
                cells=[_chart_text(s.values[i], point.money, chart.percent) for s in chart.series],
                total=_chart_text(point.value, point.money, chart.percent),
            )
        )
    return ChartOut(
        kind=chart.kind,
        kind_label=CHART_LABELS[chart.kind],
        value_label=chart.value_label,
        category_label=spec.by.label if spec.by is not None else "Ангилал",
        series_labels=[s.label for s in chart.series],
        rows=rows,
        labels=[point.label for point in chart.points],
        values=[_number_or_none(point.value) for point in chart.points],
        series=[ChartSeriesOut(label=s.label, values=[_number_or_none(v) for v in s.values]) for s in chart.series],
        money=any(point.money for point in chart.points),
        percent=chart.percent,
        hrefs=hrefs,
        masked=chart.masked,
        note=privacy.masked_note(privacy.min_group()) if chart.masked else "",
    )


@dataclass(frozen=True)
class PivotRowOut:
    """One row of a pivot grid: its text, its link ("" = none), its cells as (text, link) pairs in the column order, and
    its total as text. Without a second category the one cell links to the row (the same address)."""

    label: str
    href: str
    cells: list[tuple[str, str]]
    total: str


@dataclass(frozen=True)
class PivotGridOut:
    """One grid of the pivot as the page draws it: the caption (the value's label), the corner text (the row and column
    categories), the column heads as (text, link), the rows, the column totals and the grand total as text, and the
    note of a hidden money figure. `empty`: no rows, so the page shows the «Өгөгдөл олдсонгүй» line instead."""

    caption: str
    corner_label: str
    col_heads: list[tuple[str, str]]
    rows: list[PivotRowOut]
    col_totals: list[str]
    grand: str
    masked: bool
    note: str
    empty: bool


@dataclass(frozen=True)
class PivotOut:
    """The pivot: one grid, or two when the pivot has a second value (the same rows, columns and links)."""

    grids: list[PivotGridOut]


def _pivot_grid(spec: LayoutSpec, drill: Drill, pivot: layouts_mod.Pivot) -> PivotGridOut:
    """One pivot grid as text and links (pivot_parts in views): the column heads link by the second category, each row
    by the first, each cell by both (or by the row when there is no second category)."""
    col_heads = [
        (label, drill([(spec.by2, drill.unless(key, drill.by2_bad, drill.by2_grained))]))
        for label, key in zip(pivot.col_labels, pivot.col_keys, strict=True)
    ]
    rows: list[PivotRowOut] = []
    for i, (label, cells, total) in enumerate(zip(pivot.row_labels, pivot.cells, pivot.row_totals, strict=True)):
        row_key = drill.unless(pivot.row_keys[i], drill.by_bad, drill.by_grained)
        row_href = drill([(spec.by, row_key)])
        cell_out: list[tuple[str, str]] = []
        for j, value in enumerate(cells):
            col_key = drill.unless(pivot.col_keys[j], drill.by2_bad, drill.by2_grained)
            href = row_href if spec.by2 is None else drill([(spec.by, row_key), (spec.by2, col_key)])
            cell_out.append((_chart_text(value, pivot.money, pivot.percent), href))
        rows.append(
            PivotRowOut(
                label=label,
                href=row_href,
                cells=cell_out,
                total=_chart_text(total, pivot.money, pivot.percent),
            )
        )
    corner = spec.by.label if spec.by is not None else ""
    if spec.by2 is not None:
        corner += f" / {spec.by2.label}"
    return PivotGridOut(
        caption=pivot.value_label,
        corner_label=corner,
        col_heads=col_heads,
        rows=rows,
        col_totals=[_chart_text(total, pivot.money, pivot.percent) for total in pivot.col_totals],
        grand=_chart_text(pivot.grand, pivot.money, pivot.percent),
        masked=pivot.masked,
        note=privacy.masked_note(privacy.min_group()) if pivot.masked else "",
        empty=not pivot.row_labels,
    )


def pivot_page(table: layouts_mod.TableLike, spec: LayoutSpec, drill: Drill) -> PivotOut:
    """The pivot of the filtered rows, as the page draws it. With a second value (spec.value2) a second grid follows
    the first, built from the same rows and columns with the second value and no percent (lshow applies to the first
    only), so both grids share their links."""
    grids = [_pivot_grid(spec, drill, layouts_mod.build_pivot(table, spec))]
    if spec.value2 is not None:
        grids.append(
            _pivot_grid(spec, drill, layouts_mod.build_pivot(table, replace(spec, value=spec.value2, show="")))
        )
    return PivotOut(grids=grids)


@dataclass(frozen=True)
class LayoutPage:
    """A report page's layout other than the table: its kind, its layout bar, the filtered row count and the one
    payload of its kind (the other five are None). `count` is every filtered row, as the table counts them."""

    kind: Literal["cards", "board", "calendar", "timeline", "chart", "pivot"]
    bar: LayoutBar
    count: int
    board: BoardOut | None = None
    cards: CardsOut | None = None
    calendar: CalendarOut | None = None
    timeline: TimelineOut | None = None
    chart: ChartOut | None = None
    pivot: PivotOut | None = None


def layout_page(
    params: QueryDict,
    path: str,
    user: User,
    report: Report,
    table: Table,
    adds: list[str],
    plain: bool,
    offset: int = 0,
) -> LayoutPage | None:
    """The layout of the filtered table as the page draws it, or None for the table layout. `table` comes from
    table_page (build_table), which has already cleaned every layout parameter for this viewer (clean_params and
    resolve), so `params` is not read again here: it is kept only so the signature matches the page's other entry
    points. `offset` is the cards batch asked for (0 for the first). `link(**over)` is the report address with the
    filters replaced by `over`; the drill of the category layouts is built once from the same address."""
    spec = table.spec
    if spec.layout == "table":
        return None
    f = table.filters
    marks = marks_mod.parse_marks(f.marks)
    today = timezone.localdate()

    def link(**overrides: Any) -> str:
        return address(path, replace(f, **overrides), adds, plain=plain)

    # the layout bar's flags: a chart or pivot groups by a date column, and the sort applies unless a date has a grain
    dated = any(c is not None and c.kind == "date" for c in (spec.by, spec.by2))
    sort_ok = not (spec.by is not None and spec.by.kind == "date" and spec.grain)
    bar = layout_bar(report, user, spec, f, adds, dated, sort_ok)
    drill = drill_for(table, spec, LinkBase(path=path, f=f, adds=tuple(adds), plain=plain))
    count = table.count
    layout = spec.layout
    if layout == "board":
        return LayoutPage(kind="board", bar=bar, count=count, board=board_page(table, spec, marks, today, drill))
    if layout == "cards":
        return LayoutPage(kind="cards", bar=bar, count=count, cards=cards_page(table, report, marks, today, offset))
    if layout == "calendar":
        return LayoutPage(
            kind="calendar", bar=bar, count=count, calendar=calendar_page(table, spec, marks, today, link)
        )
    if layout == "timeline":
        return LayoutPage(
            kind="timeline", bar=bar, count=count, timeline=timeline_page(table, spec, marks, today, link)
        )
    if layout == "chart":
        return LayoutPage(kind="chart", bar=bar, count=count, chart=chart_page(table, spec, drill))
    if layout == "pivot":
        return LayoutPage(kind="pivot", bar=bar, count=count, pivot=pivot_page(table, spec, drill))
    return None
