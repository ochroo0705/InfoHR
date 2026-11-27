"""The report catalogue and the report page's read side, as the React pages read them.

- GET /api/v1/reports/catalogue: the report catalogue's sections. The cards, their order and their rights come from
  reports.services.catalogue_page; the route needs reports.view_reports (403 "forbidden" without it). The catalogue
  holds no personal data, so the answer is not marked no-store.
- GET /api/v1/reports/{key}: the report's head, filter bar and table layout (the first batch of the table). The query
  string IS the filters: the raw query goes to the same services the Django report page calls, so the API parses
  nothing itself. A bare address with a default saved view answers `redirect` and nothing else.
- GET /api/v1/reports/{key}/rows?offset=: one batch of the same table, with the same query.
- GET /api/v1/reports/{key}/cards?offset=: one batch of the cards layout (404 "not_found" if it is not cards).
- GET /api/v1/reports/{key}/print?<address>&sel=<ticket?>: the print page (reports.services.print_page). With `sel`
  the address is the ticket's and the query string is ignored.
- GET /api/v1/reports/{key}/excel?<address>: the report's Excel file.
- POST /api/v1/reports/{key}/selected/excel and /selected/csv: the picked people's files. POST /selected/print answers
  a print ticket; POST /selected/copy answers the names as text. The body is the address plus the ticked ids or `all`.
- POST /api/v1/reports/{key}/selected/checklist/form and /selected/checklist: the offboarding checklist for the picked
  people (the form, then the start). They also need the right to start a checklist (403 "forbidden" without it).

The page and rows answers need a signed-in session (401 without one), reports.view_reports and the report's own rights
(403 "forbidden"), and an unknown key is 404. Every page and rows answer is marked Cache-Control: no-store: the rows
carry people's data (and salaries, where the viewer may see them). The print and copy need can_open; the files also
need accounts.export_lists. The selection routes are 404 for a report with no person.
"""

from decimal import Decimal
from typing import Any, Literal

from accounts.audit import record_export
from accounts.models import User
from checklists import access as checklist_access
from django.http import HttpRequest, HttpResponse, QueryDict
from django.urls import reverse
from django.utils import timezone
from employees.templatetags.hr import mnt
from ninja import Router, Schema
from ninja.security import django_auth
from reports import registry
from reports.filters import parse_filters
from reports.selection import Picked, SelectionError, pick_from
from reports.services import exports, saved_views
from reports.services import popups as report_popups
from reports.services import selection_checklist as checklist_service
from reports.services.catalogue_page import Row, card_path, search_text, sections_for
from reports.services.filter_bar import FilterBar, FilterOptions
from reports.services.layout_page import (
    BarGroupOut,
    BarOut,
    BarSelect,
    BoardOut,
    CalendarOut,
    CardOut,
    CardsOut,
    ChartOut,
    ChartRowOut,
    DayOut,
    EntryOut,
    ExtraOut,
    LaneOut,
    LayoutBar,
    LayoutPage,
    PivotGridOut,
    PivotOut,
    PivotRowOut,
    TickOut,
    TimelineOut,
    layout_page,
)
from reports.services.page_head import EXPORT_PERM, SHARED, PageHead, _view_url, default_view_redirect, page_head
from reports.services.popups import ColourOut, ColumnKind, MarkOut, OpOut, Pick, check_popup
from reports.services.print_page import PrintPage, build_print
from reports.services.saved_views import SaveResult
from reports.services.table_page import CellOut, RowGroup, TablePage, parse_offset, table_page
from reports.types import Report

from api.errors import ApiError
from api.popups import FORBIDDEN, NOT_FOUND, request_user, service_errors

report_router = Router(tags=["reports"], auth=django_auth)


class ReportCardOut(Schema):
    key: str  # the address /reports/<key>/ once built
    title: str
    description: str
    search: str  # the card's search text (the template's data-search), matched in the browser
    link: bool  # the report is built and the user may open it; false draws the card greyed «удахгүй»
    empty: bool  # the built report's main table has no rows yet («бүртгэл алга»)
    path: str  # /reports/<key>/ when link, "" otherwise


class ReportSectionOut(Schema):
    title: str  # the group's title, e.g. «Ажилтны жагсаалт, судалгаа»
    rows: list[ReportCardOut]


class ReportCatalogueOut(Schema):
    sections: list[ReportSectionOut]


def _card(row: Row) -> dict[str, Any]:
    return {
        "key": row.entry.key,
        "title": row.entry.title,
        "description": row.entry.description,
        "search": search_text(row.entry),
        "link": row.link,
        "empty": row.empty,
        "path": card_path(row),
    }


@report_router.get("/catalogue", response=ReportCatalogueOut)
def catalogue(request: HttpRequest) -> dict[str, Any]:
    user = request_user(request)
    if not user.has_perm("reports.view_reports"):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return {"sections": [{"title": s.title, "rows": [_card(row) for row in s.rows]} for s in sections_for(user)]}


# --- the report page: head, filter bar and table (read only) ---------------------------------------------------------
# The schemas are listed bottom-up: a schema is defined before the one that uses it.


class ReportOptionOut(Schema):
    value: str
    label: str


class ReportCellOut(Schema):
    text: str  # what the template prints: an ISO date, "" for no value; HTML is text, not markup
    value: str | None  # the raw value as text; None when blank. A money cell's value is the raw number, unformatted
    money: bool
    href: str  # the link target, "" when the cell is not a link
    css: str  # the cell's classes: alignment, colour and pinning
    style: str  # the inline offset of a pinned cell, "" when not pinned
    person: int  # the employee id of the row; 0 when the report names no person


class ReportGroupOut(Schema):
    label: str  # "" when the rows are not grouped
    count: int  # the rows in this group as the answer carries them
    rows: list[list[ReportCellOut]]


class ReportRowsOut(Schema):
    groups: list[ReportGroupOut]
    next_offset: int | None  # the offset of the next batch; None when no batch follows


class ReportHeadCellOut(Schema):
    label: str
    href: str  # the address that sorts by this column
    append_href: str  # the address that adds this column to the sort (Shift+click)
    arrow: str  # "↑", "↓" on the sorted column, "↑1", "↓2" when several keys sort, else ""
    css: str  # alignment and pinning classes
    sticky_left: str  # the inline offset of a pinned column, "" when not pinned


class ReportTableOut(Schema):
    heads: list[ReportHeadCellOut]
    groups: list[ReportGroupOut]  # one group with label "" when not grouped
    next_offset: int | None
    count: int  # every filtered row, not only the batch
    shows_count: bool  # the «Нийт: N» line is drawn
    rules_text: str
    clear_rules_url: str
    note: str  # a grey line above the table, "" when none
    footer: list[ReportCellOut] | None  # the totals row, None when the report has none
    selectable: bool  # the checkbox column is drawn
    check_css: str
    check_style: str
    table_span: int  # the columns a full-width row spans
    pin: int  # the number of pinned columns
    address: str  # the report's address for these filters
    query: str  # the cleaned filters as a query string


class ReportFilterOptionsOut(Schema):
    states: list[ReportOptionOut]
    emptypes: list[ReportOptionOut]
    genders: list[ReportOptionOut]
    branches: list[ReportOptionOut]
    departments: list[ReportOptionOut]
    positions: list[ReportOptionOut]
    change_kinds: list[ReportOptionOut]
    order_types: list[ReportOptionOut]
    leave_states: list[ReportOptionOut]
    leave_types: list[ReportOptionOut]
    absence_types: list[ReportOptionOut]
    attributes: list[ReportOptionOut]
    contact_types: list[ReportOptionOut]
    training_types: list[ReportOptionOut]
    present_types: list[ReportOptionOut]
    reasons: list[ReportOptionOut]
    discipline_types: list[ReportOptionOut]
    people: list[ReportOptionOut]  # the people the viewer may see (value: employee id)
    no_working_state: list[ReportOptionOut]
    group_choices: list[ReportOptionOut]  # the «Бүлэглэх» choices (value: column key)
    period_from: str  # YYYY-MM-DD
    period_to: str  # YYYY-MM-DD
    year: int | None
    quarter: int | None
    group_text: str  # the grouping as the bar shows it


class ReportBarItemOut(Schema):
    name: str  # the filter's name, e.g. "branch"
    remove: str  # its ✕ address; "" when the filter is always drawn


class ReportPickerOut(Schema):
    label: str
    href: str
    heading: str  # «Шүүлтүүр» or «Баганаар» above the first line of its group, "" otherwise


class ReportColumnChipOut(Schema):
    name: str
    label: str
    kind: str  # "code", "choice", "date" or "number"
    params: list[str]  # the query parameters in order: the name, or "<name>_from" and "<name>_to" for a range
    options: list[ReportOptionOut]
    values: list[str]  # one per parameter; "" when unset
    remove_href: str


class ReportBarOut(Schema):
    items: list[ReportBarItemOut]
    picker: list[ReportPickerOut]
    column_chips: list[ReportColumnChipOut]
    adds: list[str]  # the picker's chips without a value yet; never stored
    clear_url: str
    columns_query: str  # the query the «Багана», «Шүүлтүүр» and «Хэлбэр» pop-ups carry
    options: ReportFilterOptionsOut


class ReportToolsOut(Schema):
    columns: bool  # the «Багана» pop-up (the report picks its columns)
    rules: bool  # the «Шүүлтүүр» pop-up (the report has a count line)
    format: bool  # the «Хэлбэр» pop-up: a count line and not a chart or pivot


class ReportSavedOptionOut(Schema):
    name: str
    url: str  # the report's address with this view's query
    selected: bool  # the address shows this view's setup now


class ReportSavedOut(Schema):
    plain_url: str  # the «—» option: the report with no saved setup
    options: list[ReportSavedOptionOut]  # the saved views this viewer may see
    templates: list[ReportSavedOptionOut]  # the starter templates («Загвар») this viewer may use
    current_view: int | None  # the id of the saved view the address matches; None when none does
    template_current: bool  # a template matches the address
    can_edit_view: bool  # the current view may be renamed or deleted by this viewer


class ReportLayoutOut(Schema):
    name: str
    label: str
    url: str
    current: bool  # the layout on screen


class ReportHeadOut(Schema):
    title: str
    saved: ReportSavedOut | None  # None when the report keeps no saved views
    tools: ReportToolsOut
    layouts: list[ReportLayoutOut]  # the switcher; drawn with two or more
    staff_actions: bool  # hire and import beside the title (the staff list, for managers)
    selectable: bool  # the «Сонгох» toggle
    selection_urls: dict[str, str]  # "" for an action the viewer may not use
    print_url: str
    excel_url: str  # "" without the export right
    selection_max: int  # the most people one bulk action covers (the selection bar's cap)


class ReportBarSelectOut(Schema):
    name: str  # the parameter name, e.g. "lby"
    label: str  # the select's label, e.g. «Ангилал»
    selected: str  # the value it shows now; "" = none chosen
    options: list[ReportOptionOut]  # the options in the order the bar draws them


class ReportLayoutBarOut(Schema):
    layout: str  # the layout the bar is for
    keep: list[list[str]]  # [name, value] pairs: the hidden inputs the bar carries
    selects: list[ReportBarSelectOut]


class ReportExtraOut(Schema):
    label: str
    text: str  # money by mnt («—» when none), a date as ISO, else the value's text ("" for none)
    href: str  # the mailto: or tel: link of a contact column; "" for none (money and dates are never links)


class ReportLayoutCardOut(Schema):
    title: str
    subtitle: str
    href: str
    mark: str  # the CSS classes of the first passing mark; "" for none
    extras: list[ReportExtraOut]
    photo_url: str  # the 72 px thumbnail; "" without a photo
    photo_initial: str  # the soft tile's letter when there is a photo slot but no image; else ""
    photo_srcset: str  # the 2x and 3x thumbnails («url 2x, url 3x»); "" without an image


class ReportLaneOut(Schema):
    label: str
    count: int  # the lane's filtered row count
    figure: str  # the figure's text; "" when the value is the count
    href: str  # the category link; "" for none
    cards: list[ReportLayoutCardOut]


class ReportBoardOut(Schema):
    lanes: list[ReportLaneOut]
    total: int  # the filtered row count
    shown: int  # the cards drawn
    cap: int  # the most cards drawn
    value_label: str  # the caption of the value; "" = the count


class ReportCardsOut(Schema):
    items: list[ReportLayoutCardOut]
    next_offset: int | None  # the offset of the next batch; None when it is the last
    total: int  # every row, not only the batch


class ReportEntryOut(Schema):
    title: str
    href: str  # "" for none
    mark: str  # the CSS classes of the first passing mark; "" for none
    note: str  # e.g. «36 жил» for a repeated yearly entry; "" otherwise


class ReportDayOut(Schema):
    iso: str  # YYYY-MM-DD
    number: int  # the day of the month
    in_month: bool
    is_today: bool
    entries: list[ReportEntryOut]
    more: int  # the entries past the cap
    more_href: str  # "" = the count is plain text


class ReportCalendarOut(Schema):
    mode: str  # "month" or "week"
    heading: str
    weeks: list[list[ReportDayOut]]  # the month grid; [] in week mode
    days: list[ReportDayOut]  # the week; [] in month mode
    undated: int
    prev_href: str  # "" when the arrow is disabled
    next_href: str  # "" when the arrow is disabled
    today_href: str
    switch_href: str
    month_value: str  # «YYYY-MM» in month mode, else ""
    keep: list[list[str]]  # [name, value] pairs of the month picker's hidden inputs
    total: int


class ReportTickOut(Schema):
    label: str
    left_pct: float  # the place on the axis in percent


class ReportTimelineBarOut(Schema):
    title: str
    href: str  # "" for none
    mark: str  # the CSS classes of the first passing mark; "" for none
    left_pct: float  # the place on the axis in percent
    width_pct: float  # the width in percent
    label: str  # the aria text «title: from – to»
    tip_title: str
    tip: str


class ReportTimelineGroupOut(Schema):
    label: str  # «—» for the blank group, "" when ungrouped
    count: int
    bars: list[ReportTimelineBarOut]


class ReportTimelineOut(Schema):
    groups: list[ReportTimelineGroupOut]
    ticks: list[ReportTickOut]
    today_pct: float | None  # None when today is off the axis
    first: str  # the axis start as ISO; "" when no drawn row has a start
    last: str  # the axis end as ISO; "" when no drawn row has a start
    undated: int
    off_axis: int
    clipped: bool
    over_cap: int
    cap: int
    years: int
    total: int
    year: int | None  # the year window; None for «Бүгд»
    year_prev_href: str | None  # None at the year bound
    year_next_href: str | None  # None at the year bound
    all_href: str
    enter_href: str


class ReportChartRowOut(Schema):
    label: str
    href: str  # "" = none
    cells: list[str]  # one text per stack of a stacked bar; [] for a plain bar or a donut
    total: str  # the category's total as finished text


class ReportChartSeriesOut(Schema):
    label: str
    values: list[float | None]  # one per category; None = no figure (a hidden money figure too)


class ReportChartOut(Schema):
    kind: str  # "bar", "stacked", "line" or "donut"
    kind_label: str
    value_label: str
    category_label: str
    series_labels: list[str]
    rows: list[ReportChartRowOut]
    labels: list[str]  # the drawing's category labels
    values: list[float | None]  # the drawing's figures; None = no figure (a hidden money figure too)
    series: list[ReportChartSeriesOut]
    money: bool
    percent: bool
    hrefs: list[str]  # one per category, "" = none
    masked: bool  # a money figure was hidden
    note: str  # the note of the hidden money figure; "" when nothing was hidden


class ReportPivotCellOut(Schema):
    text: str
    href: str  # "" = none


class ReportPivotHeadOut(Schema):
    label: str  # the column head's text
    href: str  # "" = none


class ReportPivotRowOut(Schema):
    label: str
    href: str  # "" = none
    cells: list[ReportPivotCellOut]  # in the column order
    total: str


class ReportPivotGridOut(Schema):
    caption: str  # the value's label
    corner_label: str  # the row and column categories
    col_heads: list[ReportPivotHeadOut]
    rows: list[ReportPivotRowOut]
    col_totals: list[str]
    grand: str
    masked: bool  # a money figure was hidden
    note: str
    empty: bool  # no rows: the page shows «Өгөгдөл олдсонгүй»


class ReportPivotOut(Schema):
    grids: list[ReportPivotGridOut]  # one grid, or two when the pivot has a second value


class ReportLayoutPageOut(Schema):
    kind: str  # "cards", "board", "calendar", "timeline", "chart" or "pivot"
    bar: ReportLayoutBarOut
    count: int  # every filtered row
    board: ReportBoardOut | None  # exactly one payload is set: the one of `kind`
    cards: ReportCardsOut | None
    calendar: ReportCalendarOut | None
    timeline: ReportTimelineOut | None
    chart: ReportChartOut | None
    pivot: ReportPivotOut | None
    rules_text: str  # the rules line of the page (the filter bar's «Шүүлтүүр» text)
    shows_count: bool  # the «Нийт: N» line is drawn
    note: str  # a grey line above the layout, "" when none
    clear_rules_url: str
    query: str  # the cleaned filters as a query string


class ReportPageOut(Schema):
    redirect: str  # the default saved view's address for a bare address; "" when there is nothing to follow
    title: str
    layout: str  # the layout on screen: "table", "cards", ...
    head: ReportHeadOut | None  # None when redirect is set
    bar: ReportBarOut | None  # None when redirect is set
    table: ReportTableOut | None  # None when redirect is set or the layout is not "table"
    layout_page: ReportLayoutPageOut | None  # None when redirect is set or the layout is "table"


def _options(rows: list[tuple[str, str]]) -> list[ReportOptionOut]:
    return [ReportOptionOut(value=value, label=label) for value, label in rows]


def _cell(cell: CellOut) -> ReportCellOut:
    return ReportCellOut(
        text=cell.text,
        value=cell.value,
        money=cell.money,
        href=cell.href,
        css=cell.css,
        style=cell.style,
        person=cell.person,
    )


def _group(group: RowGroup) -> ReportGroupOut:
    return ReportGroupOut(
        label=group.label,
        count=group.count,
        rows=[[_cell(cell) for cell in row] for row in group.rows],
    )


def _filter_options(options: FilterOptions) -> ReportFilterOptionsOut:
    return ReportFilterOptionsOut(
        states=_options(options.states),
        emptypes=_options(options.emptypes),
        genders=_options(options.genders),
        branches=_options(options.branches),
        departments=_options(options.departments),
        positions=_options(options.positions),
        change_kinds=_options(options.change_kinds),
        order_types=_options(options.order_types),
        leave_states=_options(options.leave_states),
        leave_types=_options(options.leave_types),
        absence_types=_options(options.absence_types),
        attributes=_options(options.attributes),
        contact_types=_options(options.contact_types),
        training_types=_options(options.training_types),
        present_types=_options(options.present_types),
        reasons=_options(options.reasons),
        discipline_types=_options(options.discipline_types),
        people=_options(options.people),
        no_working_state=_options(options.no_working_state),
        group_choices=_options(options.group_choices),
        period_from=options.period_from.isoformat(),
        period_to=options.period_to.isoformat(),
        year=options.year,
        quarter=options.quarter,
        group_text=options.group_text,
    )


def _bar(bar: FilterBar) -> ReportBarOut:
    return ReportBarOut(
        items=[ReportBarItemOut(name=item.name, remove=item.remove) for item in bar.items],
        picker=[ReportPickerOut(label=e.label, href=e.href, heading=e.heading) for e in bar.picker],
        column_chips=[
            ReportColumnChipOut(
                name=chip.name,
                label=chip.label,
                kind=chip.kind,
                params=chip.params,
                options=_options(chip.options),
                values=chip.values,
                remove_href=chip.remove_href,
            )
            for chip in bar.column_chips
        ],
        adds=bar.adds,
        clear_url=bar.clear_url,
        columns_query=bar.columns_query,
        options=_filter_options(bar.options),
    )


def _head(head: PageHead) -> ReportHeadOut:
    saved = None
    if head.saved is not None:
        current = head.saved.current_view
        saved = ReportSavedOut(
            plain_url=head.saved.plain_url,
            options=[ReportSavedOptionOut(name=o.name, url=o.url, selected=o.selected) for o in head.saved.options],
            templates=[ReportSavedOptionOut(name=o.name, url=o.url, selected=o.selected) for o in head.saved.templates],
            current_view=current.pk if current is not None else None,
            template_current=head.saved.template_current,
            can_edit_view=head.saved.can_edit_view,
        )
    tools = head.tools
    return ReportHeadOut(
        title=head.title,
        saved=saved,
        tools=ReportToolsOut(columns=tools.columns, rules=tools.rules, format=tools.format),
        layouts=[
            ReportLayoutOut(name=n.name, label=n.label, url=n.url, current=n.current) for n in head.layout_options
        ],
        staff_actions=tools.staff_actions,
        selectable=tools.selectable,
        selection_urls=dict(tools.selection_urls),
        print_url=tools.print_url,
        excel_url=tools.excel_url,
        selection_max=head.selection_max,
    )


def _table(page: TablePage) -> ReportTableOut:
    return ReportTableOut(
        heads=[
            ReportHeadCellOut(
                label=h.label,
                href=h.href,
                append_href=h.append_href,
                arrow=h.arrow,
                css=h.css,
                sticky_left=h.sticky_left,
            )
            for h in page.heads
        ],
        groups=[_group(group) for group in page.groups],
        next_offset=page.next_offset,
        count=page.count,
        shows_count=page.shows_count,
        rules_text=page.rules_text,
        clear_rules_url=page.clear_rules_url,
        note=page.note,
        footer=None if page.footer is None else [_cell(cell) for cell in page.footer],
        selectable=page.selectable,
        check_css=page.check_css,
        check_style=page.check_style,
        table_span=page.table_span,
        pin=page.pin,
        address=page.address,
        query=page.query,
    )


def _bar_select(select: BarSelect) -> ReportBarSelectOut:
    return ReportBarSelectOut(
        name=select.name,
        label=select.label,
        selected=select.selected,
        options=_options(select.options),
    )


def _layout_bar(bar: LayoutBar) -> ReportLayoutBarOut:
    return ReportLayoutBarOut(
        layout=bar.layout,
        keep=_pairs(bar.keep),
        selects=[_bar_select(select) for select in bar.selects],
    )


def _extra(extra: ExtraOut) -> ReportExtraOut:
    return ReportExtraOut(label=extra.label, text=extra.text, href=extra.href)


def _layout_card(card: CardOut) -> ReportLayoutCardOut:
    return ReportLayoutCardOut(
        title=card.title,
        subtitle=card.subtitle,
        href=card.href,
        mark=card.mark,
        extras=[_extra(extra) for extra in card.extras],
        photo_url=card.photo_url,
        photo_initial=card.photo_initial,
        photo_srcset=card.photo_srcset,
    )


def _lane(lane: LaneOut) -> ReportLaneOut:
    return ReportLaneOut(
        label=lane.label,
        count=lane.count,
        figure=lane.figure,
        href=lane.href,
        cards=[_layout_card(card) for card in lane.cards],
    )


def _board(board: BoardOut) -> ReportBoardOut:
    return ReportBoardOut(
        lanes=[_lane(lane) for lane in board.lanes],
        total=board.total,
        shown=board.shown,
        cap=board.cap,
        value_label=board.value_label,
    )


def _cards(cards: CardsOut) -> ReportCardsOut:
    return ReportCardsOut(
        items=[_layout_card(card) for card in cards.items],
        next_offset=cards.next_offset,
        total=cards.total,
    )


def _entry(entry: EntryOut) -> ReportEntryOut:
    return ReportEntryOut(title=entry.title, href=entry.href, mark=entry.mark, note=entry.note)


def _day(day: DayOut) -> ReportDayOut:
    return ReportDayOut(
        iso=day.iso,
        number=day.number,
        in_month=day.in_month,
        is_today=day.is_today,
        entries=[_entry(entry) for entry in day.entries],
        more=day.more,
        more_href=day.more_href,
    )


def _calendar(calendar: CalendarOut) -> ReportCalendarOut:
    return ReportCalendarOut(
        mode=calendar.mode,
        heading=calendar.heading,
        weeks=[[_day(day) for day in week] for week in calendar.weeks],
        days=[_day(day) for day in calendar.days],
        undated=calendar.undated,
        prev_href=calendar.prev_href,
        next_href=calendar.next_href,
        today_href=calendar.today_href,
        switch_href=calendar.switch_href,
        month_value=calendar.month_value,
        keep=_pairs(calendar.keep),
        total=calendar.total,
    )


def _tick(tick: TickOut) -> ReportTickOut:
    return ReportTickOut(label=tick.label, left_pct=tick.left_pct)


def _timeline_bar(bar: BarOut) -> ReportTimelineBarOut:
    return ReportTimelineBarOut(
        title=bar.title,
        href=bar.href,
        mark=bar.mark,
        left_pct=bar.left_pct,
        width_pct=bar.width_pct,
        label=bar.label,
        tip_title=bar.tip_title,
        tip=bar.tip,
    )


def _timeline_group(group: BarGroupOut) -> ReportTimelineGroupOut:
    return ReportTimelineGroupOut(
        label=group.label,
        count=group.count,
        bars=[_timeline_bar(bar) for bar in group.bars],
    )


def _timeline(timeline: TimelineOut) -> ReportTimelineOut:
    return ReportTimelineOut(
        groups=[_timeline_group(group) for group in timeline.groups],
        ticks=[_tick(tick) for tick in timeline.ticks],
        today_pct=timeline.today_pct,
        first=timeline.first,
        last=timeline.last,
        undated=timeline.undated,
        off_axis=timeline.off_axis,
        clipped=timeline.clipped,
        over_cap=timeline.over_cap,
        cap=timeline.cap,
        years=timeline.years,
        total=timeline.total,
        year=timeline.year,
        year_prev_href=timeline.year_prev_href,
        year_next_href=timeline.year_next_href,
        all_href=timeline.all_href,
        enter_href=timeline.enter_href,
    )


def _chart_row(row: ChartRowOut) -> ReportChartRowOut:
    return ReportChartRowOut(label=row.label, href=row.href, cells=row.cells, total=row.total)


def _chart(chart: ChartOut) -> ReportChartOut:
    return ReportChartOut(
        kind=chart.kind,
        kind_label=chart.kind_label,
        value_label=chart.value_label,
        category_label=chart.category_label,
        series_labels=chart.series_labels,
        rows=[_chart_row(row) for row in chart.rows],
        labels=chart.labels,
        values=chart.values,
        series=[ReportChartSeriesOut(label=s.label, values=s.values) for s in chart.series],
        money=chart.money,
        percent=chart.percent,
        hrefs=chart.hrefs,
        masked=chart.masked,
        note=chart.note,
    )


def _pivot_cell(text: str, href: str) -> ReportPivotCellOut:
    return ReportPivotCellOut(text=text, href=href)


def _pivot_row(row: PivotRowOut) -> ReportPivotRowOut:
    return ReportPivotRowOut(
        label=row.label,
        href=row.href,
        cells=[_pivot_cell(text, href) for text, href in row.cells],
        total=row.total,
    )


def _pivot_grid(grid: PivotGridOut) -> ReportPivotGridOut:
    return ReportPivotGridOut(
        caption=grid.caption,
        corner_label=grid.corner_label,
        col_heads=[ReportPivotHeadOut(label=label, href=href) for label, href in grid.col_heads],
        rows=[_pivot_row(row) for row in grid.rows],
        col_totals=grid.col_totals,
        grand=grid.grand,
        masked=grid.masked,
        note=grid.note,
        empty=grid.empty,
    )


def _pivot(pivot: PivotOut) -> ReportPivotOut:
    return ReportPivotOut(grids=[_pivot_grid(grid) for grid in pivot.grids])


def _layout_page(layout: LayoutPage, page: TablePage) -> ReportLayoutPageOut:
    """The layout page: the layout's own payload (exactly one set), with the page-level lines the table answer has."""
    return ReportLayoutPageOut(
        kind=layout.kind,
        bar=_layout_bar(layout.bar),
        count=layout.count,
        board=_board(layout.board) if layout.board is not None else None,
        cards=_cards(layout.cards) if layout.cards is not None else None,
        calendar=_calendar(layout.calendar) if layout.calendar is not None else None,
        timeline=_timeline(layout.timeline) if layout.timeline is not None else None,
        chart=_chart(layout.chart) if layout.chart is not None else None,
        pivot=_pivot(layout.pivot) if layout.pivot is not None else None,
        rules_text=page.rules_text,
        shows_count=page.shows_count,
        note=page.note,
        clear_rules_url=page.clear_rules_url,
        query=page.query,
    )


def _report_for(key: str, user: User) -> Report:
    report = registry.get(key)
    if report is None:
        raise ApiError(404, [NOT_FOUND])
    if not registry.can_open(user, report):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return report


def _filters_query(request: HttpRequest) -> QueryDict:
    """The address's query as the filters read it: the raw query without `offset` (the batch is passed on its own)."""
    params = request.GET.copy()
    params.pop("offset", None)
    return params


@report_router.get("/{key}", response=ReportPageOut)
def report_page(request: HttpRequest, response: HttpResponse, key: str, offset: str = "0") -> ReportPageOut:
    """The report's head, filter bar and table layout for the address. The redirect is answered before the table is
    built, as the Django page does. A layout other than the table answers the head, the bar and the layout page (its
    payload) with no table."""
    user = request_user(request)
    report = _report_for(key, user)
    response["Cache-Control"] = "no-store"
    params = _filters_query(request)
    path = reverse("reports:report", args=[key])
    target = default_view_redirect(params, False, request.method or "GET", user, report)
    if target:
        return ReportPageOut(redirect=target, title="", layout="", head=None, bar=None, table=None, layout_page=None)
    page = table_page(params, path, user, report, parse_offset(offset))
    head = page_head(params, False, path, user, report, page.table, bool(report.saved_views))
    layout = None
    if page.layout != "table":
        layout = layout_page(
            params, path, user, report, page.table, page.adds, bool(report.saved_views), parse_offset(offset)
        )
    return ReportPageOut(
        redirect="",
        title=head.title,
        layout=page.layout,
        head=_head(head),
        bar=_bar(page.bar) if page.bar is not None else None,
        table=_table(page) if page.layout == "table" else None,
        layout_page=_layout_page(layout, page) if layout is not None else None,
    )


@report_router.get("/{key}/rows", response=ReportRowsOut)
def report_rows(request: HttpRequest, response: HttpResponse, key: str, offset: str = "0") -> ReportRowsOut:
    """One batch of the table for the address (every row of a grouped table, with next_offset None)."""
    user = request_user(request)
    report = _report_for(key, user)
    response["Cache-Control"] = "no-store"
    # no filter bar: a batch draws only its rows, and the bar's option lists are queries it must not run
    page = table_page(
        _filters_query(request),
        reverse("reports:report", args=[key]),
        user,
        report,
        parse_offset(offset),
        with_bar=False,
    )
    return ReportRowsOut(groups=[_group(group) for group in page.groups], next_offset=page.next_offset)


@report_router.get("/{key}/cards", response=ReportCardsOut)
def report_cards(request: HttpRequest, response: HttpResponse, key: str, offset: str = "0") -> ReportCardsOut:
    """One batch of the cards layout for the address (the same cards the page draws). The address must name the
    cards layout, else 404 «not_found» (no cards to batch). The table is built without its filter bar, as rows is."""
    user = request_user(request)
    report = _report_for(key, user)
    response["Cache-Control"] = "no-store"
    params = _filters_query(request)
    path = reverse("reports:report", args=[key])
    page = table_page(params, path, user, report, parse_offset(offset), with_bar=False)
    if page.layout != "cards":
        raise ApiError(404, [NOT_FOUND], code="not_found")
    layout = layout_page(
        params, path, user, report, page.table, page.adds, bool(report.saved_views), parse_offset(offset)
    )
    assert layout is not None and layout.cards is not None  # the cards layout always has its payload
    return _cards(layout.cards)


# --- the print page, the Excel and CSV files, and the picked people's print ticket and copy -------------------------
# The rules are reports.services (print_page, exports) and reports.selection; these routes read the address or the
# posted selection and answer them. The print page, the copy and the files are no-store: they carry people's data.


class ReportPrintHeadOut(Schema):
    label: str  # the column's heading
    css: str  # the column's classes: alignment


class ReportPrintGroupOut(Schema):
    label: str  # "" when the rows are not grouped
    rows: list[list[ReportCellOut]]


class ReportPrintSummaryOut(Schema):
    title: str
    head: list[str]  # the header cells
    lines: list[list[str]]  # one line per category: its label, then the figures as the print shows them ("—" hidden)
    foot: list[str] | None  # the totals line of a pivot, as text; None for a chart
    money: bool
    masked: bool  # a money figure was hidden for a small group


class ReportPrintOut(Schema):
    title: str
    company: str
    today: str  # the print date, ISO (YYYY-MM-DD)
    printed_by: str
    lines: list[str]  # the filter lines, in the report's order
    note: str  # the report's grey note for these filters; "" when none
    landscape: bool  # more columns than fit portrait
    heads: list[ReportPrintHeadOut]
    groups: list[ReportPrintGroupOut]  # one group with label "" when not grouped
    footer: list[ReportCellOut] | None  # the totals row; None when there is none or the print is a subset
    count: int  # every filtered row, not only the rows printed
    shows_count: bool  # the «Нийт: N» line is drawn
    grouped: bool
    summary: ReportPrintSummaryOut | None  # a chart or pivot address's numbers; None otherwise
    min_group: int  # the smallest group whose money is shown


class ReportSelectionIn(Schema):
    query: str = ""  # the report's address (the layout keys are dropped by the server)
    ids: list[str] = []  # the ticked employee ids, as text
    all: bool = False  # every person the address matches; ids are then ignored


class ReportSelectionTicketOut(Schema):
    ticket: str  # pass it as ?sel= to the print route; it is valid for 10 minutes


class ReportSelectionCopyOut(Schema):
    text: str  # one line per person: the name, then the work email after a tab when it may be seen
    count: int
    dropped: int  # posted ids the user may not act on


def _figure(value: object, money: bool) -> str:
    """A summary figure as the print shows it (print.html and layouts/_figure.html): a money figure with the mnt filter
    (2500000 -> 2,500,000₮), any other figure as Django renders it, and "—" for a hidden or missing one."""
    if value is None:
        return "—"
    if not money:
        return str(value)
    return mnt(value if isinstance(value, str) else Decimal(str(value)))


def _summary_line(line: list[object], money: bool) -> list[str]:
    """One summary line as text: the label as it is (the print's first column is text), then each figure."""
    label, *figures = line
    return [str(label), *(_figure(value, money) for value in figures)]


def _print_out(page: PrintPage) -> ReportPrintOut:
    summary = page.summary
    summary_out = None
    if summary is not None:
        summary_out = ReportPrintSummaryOut(
            title=summary.title,
            head=summary.head,
            lines=[_summary_line(line, summary.money) for line in summary.lines],
            foot=_summary_line(summary.foot, summary.money) if summary.foot else None,
            money=summary.money,
            masked=summary.masked,
        )
    return ReportPrintOut(
        title=page.title,
        company=page.company,
        today=page.today,
        printed_by=page.printed_by,
        lines=page.lines,
        note=page.note,
        landscape=page.landscape,
        heads=[ReportPrintHeadOut(label=label, css=css) for label, css in page.heads],
        groups=[
            ReportPrintGroupOut(label=group.label, rows=[[_cell(cell) for cell in row] for row in group.rows])
            for group in page.groups
        ],
        footer=None if page.footer is None else [_cell(cell) for cell in page.footer],
        count=page.count,
        shows_count=page.shows_count,
        grouped=page.grouped,
        summary=summary_out,
        min_group=page.min_group,
    )


def _export_report(key: str, user: User) -> Report:
    """The report, for its whole Excel file: 404 when missing, 403 when the user may not open it or export."""
    report = _report_for(key, user)
    if not user.has_perm(EXPORT_PERM):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return report


def _picking_report(key: str, user: User, *, export: bool) -> Report:
    """The report, for a selection: 404 when missing or it has no person, 403 when the user may not open it (or, for a
    file, may not export)."""
    report = registry.get(key)
    if report is None or report.person is None:
        raise ApiError(404, [NOT_FOUND])
    if not registry.can_open(user, report) or (export and not user.has_perm(EXPORT_PERM)):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return report


def _picked(user: User, report: Report, query: str, ids: list[str], all_: bool) -> Picked:
    """The people the selection picks; a refusal (nobody picked, too many, not allowed) is 400 with its message."""
    try:
        return pick_from(user, report, query, ids, all_)
    except SelectionError as error:
        raise ApiError(400, [error.message]) from None


def _file(exported: exports.ExportFile) -> HttpResponse:
    response = HttpResponse(exported.body, content_type=exported.content_type)
    response["Content-Disposition"] = f'attachment; filename="{exported.filename}"'
    response["Cache-Control"] = "no-store"  # the file carries people's data
    return response


@report_router.get("/{key}/print", response=ReportPrintOut)
def report_print(request: HttpRequest, response: HttpResponse, key: str, sel: str = "") -> ReportPrintOut:
    """The print page of the report for the address. With `sel` (a print ticket from POST .../selected/print) it is the
    picked people's print for the ticket's address, and the query string is ignored. Writes one export line:
    print_page, or print_selected for a ticket."""
    user = request_user(request)
    response["Cache-Control"] = "no-store"
    if sel:
        report = _picking_report(key, user, export=False)
        try:
            query, ids, all_ = exports.ticket_read(user, key, sel)
        except SelectionError as error:
            raise ApiError(400, [error.message]) from None
        picked = _picked(user, report, query, ids, all_)
        page = build_print(user, report, picked.table.filters, only=picked.ids, table=picked.table)
        action = "print_selected"
    else:
        report = _report_for(key, user)
        page = build_print(user, report, parse_filters(request.GET))
        action = "print_page"
    record_export(request, action, report.title, filters=page.log_label, rows=page.count)
    return _print_out(page)


@report_router.get("/{key}/excel")
def report_excel(request: HttpRequest, key: str) -> HttpResponse:
    """The Excel file of the report for the address: the same visible columns, sort and groups as the screen."""
    user = request_user(request)
    report = _export_report(key, user)
    exported = exports.excel_file(user, report, parse_filters(request.GET))
    record_export(request, exported.log_action, report.title, filters=exported.log_label, rows=exported.rows)
    return _file(exported)


@report_router.post("/{key}/selected/excel")
def selected_excel(request: HttpRequest, key: str, payload: ReportSelectionIn) -> HttpResponse:
    """The picked people's rows as an Excel file: the screen's visible columns, no footer."""
    user = request_user(request)
    report = _picking_report(key, user, export=True)
    picked = _picked(user, report, payload.query, payload.ids, payload.all)
    exported = exports.selected_file(user, report, picked, "xlsx")
    record_export(request, exported.log_action, report.title, filters=exported.log_label, rows=exported.rows)
    return _file(exported)


@report_router.post("/{key}/selected/csv")
def selected_csv(request: HttpRequest, key: str, payload: ReportSelectionIn) -> HttpResponse:
    """The picked people's rows as a CSV file (UTF-8 with BOM)."""
    user = request_user(request)
    report = _picking_report(key, user, export=True)
    picked = _picked(user, report, payload.query, payload.ids, payload.all)
    exported = exports.selected_file(user, report, picked, "csv")
    record_export(request, exported.log_action, report.title, filters=exported.log_label, rows=exported.rows)
    return _file(exported)


@report_router.post("/{key}/selected/print", response=ReportSelectionTicketOut)
def selected_print(
    request: HttpRequest, response: HttpResponse, key: str, payload: ReportSelectionIn
) -> dict[str, str]:
    """A print ticket for the picked people: the selection is checked now (a refusal is 400), and GET .../print?sel=
    prints it. No line is written here; the print page writes the audit line when it is read."""
    user = request_user(request)
    report = _picking_report(key, user, export=False)
    _picked(user, report, payload.query, payload.ids, payload.all)
    ticket = exports.ticket_make(user, report.key, payload.query, payload.ids, payload.all)
    response["Cache-Control"] = "no-store"  # the ticket names the people picked
    return {"ticket": ticket}


@report_router.post("/{key}/selected/copy", response=ReportSelectionCopyOut)
def selected_copy(
    request: HttpRequest, response: HttpResponse, key: str, payload: ReportSelectionIn
) -> ReportSelectionCopyOut:
    """The picked people's names, one line each in report order, with the work email after a tab when the user may
    see the report's email column. Audited as copy_selected. Without a name column the copy is refused (400)."""
    user = request_user(request)
    report = _picking_report(key, user, export=False)
    try:
        exports.copy_columns(user, report)  # the name column is checked before anyone is picked
    except SelectionError as error:
        raise ApiError(400, [error.message]) from None
    picked = _picked(user, report, payload.query, payload.ids, payload.all)
    result = exports.selected_copy(user, report, picked)
    record_export(request, "copy_selected", report.title, filters=result.log_label, rows=result.count)
    response["Cache-Control"] = "no-store"
    return ReportSelectionCopyOut(text=result.text, count=result.count, dropped=result.dropped)


class ReportChecklistReasonOut(Schema):
    value: str  # the reason's text as a template stores it (posted back as `reason`)
    label: str  # the reason's name, as the pop-up shows it


class ReportChecklistFormOut(Schema):
    count: int  # the number of people picked
    all: bool  # every person the address matches is picked (the ids are not sent back)
    reasons: list[ReportChecklistReasonOut]  # the reasons some active offboarding template lists
    template_missing: bool  # no active offboarding template exists
    anchor_min: str  # the earliest anchor day, ISO (YYYY-MM-DD)
    anchor_max: str  # the latest anchor day, ISO
    today: str  # the anchor day the form starts on, ISO


class ReportChecklistStartIn(Schema):
    query: str = ""  # the report's address (the layout keys are dropped by the server)
    ids: list[str] = []  # the ticked employee ids, as text
    all: bool = False  # every person the address matches; ids are then ignored
    reason: str = ""  # the offboarding reason's text, "" for none
    anchor_day: str = ""  # the checklist's day, YYYY-MM-DD; "" (omitted) is refused with the date message (400)


class ReportChecklistRowOut(Schema):
    code: str  # the employee's code, or the id text when it has none
    name: str  # the person's full name, "" when the person could not be read back
    outcome: str  # what happened for this person, as text


class ReportChecklistResultOut(Schema):
    counts: dict[str, int]  # the number of people per outcome; every outcome is a key, zero or more
    rows: list[ReportChecklistRowOut]  # one row per picked person, in the order they were started
    dropped: int  # posted ids the user may not act on


def _checklist_report(key: str, user: User) -> Report:
    """The report, for the offboarding checklist: the selection's 404 and 403 first, then the right to start a
    checklist by hand (403 "forbidden")."""
    report = _picking_report(key, user, export=False)
    if not checklist_access.can_start(user):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return report


@report_router.post("/{key}/selected/checklist/form", response=ReportChecklistFormOut)
def selected_checklist_form(
    request: HttpRequest, response: HttpResponse, key: str, payload: ReportSelectionIn
) -> ReportChecklistFormOut:
    """The offboarding checklist's form for the picked people: the count, the reasons and whether a template is missing.
    The selection is checked first (a refusal is 400); nothing is started."""
    user = request_user(request)
    report = _checklist_report(key, user)
    picked = _picked(user, report, payload.query, payload.ids, payload.all)
    form = checklist_service.form_model(timezone.localdate())
    response["Cache-Control"] = "no-store"  # the count and the picked people are not for caches
    return ReportChecklistFormOut(
        count=len(picked.ids),
        all=payload.all,
        reasons=[ReportChecklistReasonOut(value=value, label=label) for value, label in form.reasons],
        template_missing=form.template_missing,
        anchor_min=form.anchor_min,
        anchor_max=form.anchor_max,
        today=form.today,
    )


@report_router.post("/{key}/selected/checklist", response=ReportChecklistResultOut)
def selected_checklist(
    request: HttpRequest, response: HttpResponse, key: str, payload: ReportChecklistStartIn
) -> ReportChecklistResultOut:
    """Starts an offboarding checklist for each picked person and answers the outcome per person. The selection is
    checked before the fields (both refusals are 400 with the messages in form_errors). Needs the right to start a
    checklist by hand."""
    user = request_user(request)
    report = _checklist_report(key, user)
    picked = _picked(user, report, payload.query, payload.ids, payload.all)
    values, anchor, errors = checklist_service.read_values(payload.reason, payload.anchor_day)
    if anchor is None or errors:
        raise ApiError(400, errors)
    outcomes = checklist_service.start_each(user, picked, values, anchor, timezone.localdate())
    result = checklist_service.result_of(outcomes, picked.dropped)
    response["Cache-Control"] = "no-store"  # the rows name people
    return ReportChecklistResultOut(
        counts=result.counts,
        rows=[ReportChecklistRowOut(code=code, name=name, outcome=outcome) for code, name, outcome in result.rows],
        dropped=result.dropped,
    )


# --- the pop-ups: «Багана сонгох», «Шүүлтүүр», «Хэлбэр» (read only: the model each pop-up draws) ---------------------
# The rules are reports.services.popups; these routes read the address (the raw query, as the Django pop-ups do) and
# answer the model. Apply in React navigates to the report path, so nothing here writes.


class ReportPickOut(Schema):
    key: str
    label: str
    checked: bool  # the column is shown now


class ReportPickGroupOut(Schema):
    title: str  # the picker group's title
    picks: list[ReportPickOut]


class ReportGroupChoiceOut(Schema):
    key: str  # the column key the report may group by
    label: str


class ReportColumnsModelOut(Schema):
    groups: list[ReportPickGroupOut]  # the columns the user may see, by group, in the order the columns come
    group_choices: list[ReportGroupChoiceOut]
    group: str  # the grouping now ("" for none)
    group_text: str  # the label of a grouping with several keys, "" otherwise
    keep: list[list[str]]  # [name, value] pairs: the cleaned address the pop-up does not own


class ReportColumnKindOut(Schema):
    key: str
    label: str
    kind: str  # "text", "number" or "date"


class ReportOpOut(Schema):
    code: str  # the operator code the rules use
    label: str


class ReportColourOut(Schema):
    key: str  # the colour name the colour rules use
    label: str
    classes: str  # the Tailwind classes a marked cell is painted with


class ReportMarkOut(Schema):
    c: str  # column key
    o: str  # operator code
    v: str  # value
    k: str  # colour key


class ReportRulesModelOut(Schema):
    columns: list[ReportColumnKindOut]  # the columns the user may use in a condition
    ops: dict[str, list[ReportOpOut]]  # by kind: "text", "number", "date"
    rules: str  # the current rules as compact JSON text, "" for none
    keep: list[list[str]]


class ReportFormatModelOut(Schema):
    columns: list[ReportColumnKindOut]
    shown: list[str]  # the column keys the table shows now
    ops: dict[str, list[ReportOpOut]]
    aggs: dict[str, list[str]]  # the aggregates a column of each kind offers, by kind
    agg_labels: dict[str, str]
    colours: list[ReportColourOut]
    totals: list[list[str]]  # [column key, aggregate] pairs
    marks: list[ReportMarkOut]
    pin: int  # the number of pinned columns, 0 to 3
    keep: list[list[str]]


def _pick(pick: Pick) -> ReportPickOut:
    return ReportPickOut(key=pick.key, label=pick.label, checked=pick.checked)


def _op(op: OpOut) -> ReportOpOut:
    return ReportOpOut(code=op.code, label=op.label)


def _ops(ops: dict[str, list[OpOut]]) -> dict[str, list[ReportOpOut]]:
    return {kind: [_op(op) for op in items] for kind, items in ops.items()}


def _column_kind(column: ColumnKind) -> ReportColumnKindOut:
    return ReportColumnKindOut(key=column.key, label=column.label, kind=column.kind)


def _pairs(pairs: list[tuple[str, str]]) -> list[list[str]]:
    return [[name, value] for name, value in pairs]


def _colour(colour: ColourOut) -> ReportColourOut:
    return ReportColourOut(key=colour.key, label=colour.label, classes=colour.classes)


def _mark(mark: MarkOut) -> ReportMarkOut:
    return ReportMarkOut(c=mark.c, o=mark.o, v=mark.v, k=mark.k)


def _popup_report(key: str, user: User, needs: Literal["picks_columns", "shows_count"]) -> Report:
    """The report of a pop-up: 404 when it is missing or lacks the feature, 403 when the user may not open it."""
    report = registry.get(key)
    with service_errors():
        check_popup(user, report, needs=needs)
    assert report is not None  # check_popup refuses a missing report
    return report


@report_router.get("/{key}/columns", response=ReportColumnsModelOut)
def columns_pop(request: HttpRequest, response: HttpResponse, key: str) -> ReportColumnsModelOut:
    """The «Багана сонгох» pop-up's model for the address."""
    user = request_user(request)
    report = _popup_report(key, user, "picks_columns")
    response["Cache-Control"] = "no-store"
    model = report_popups.columns_model(request.GET, user, report)
    return ReportColumnsModelOut(
        groups=[
            ReportPickGroupOut(title=title, picks=[_pick(pick) for pick in picks]) for title, picks in model.groups
        ],
        group_choices=[ReportGroupChoiceOut(key=c.key, label=c.label) for c in model.group_choices],
        group=model.group,
        group_text=model.group_text,
        keep=_pairs(model.keep),
    )


@report_router.get("/{key}/rules", response=ReportRulesModelOut)
def rules_pop(request: HttpRequest, response: HttpResponse, key: str) -> ReportRulesModelOut:
    """The «Шүүлтүүр» pop-up's model for the address."""
    user = request_user(request)
    report = _popup_report(key, user, "shows_count")
    response["Cache-Control"] = "no-store"
    model = report_popups.rules_model(request.GET, user, report)
    return ReportRulesModelOut(
        columns=[_column_kind(c) for c in model.columns],
        ops=_ops(model.ops),
        rules=model.rules,
        keep=_pairs(model.keep),
    )


@report_router.get("/{key}/format", response=ReportFormatModelOut)
def format_pop(request: HttpRequest, response: HttpResponse, key: str) -> ReportFormatModelOut:
    """The «Хэлбэр» pop-up's model for the address."""
    user = request_user(request)
    report = _popup_report(key, user, "shows_count")
    response["Cache-Control"] = "no-store"
    model = report_popups.format_model(request.GET, user, report)
    return ReportFormatModelOut(
        columns=[_column_kind(c) for c in model.columns],
        shown=model.shown,
        ops=_ops(model.ops),
        aggs={kind: list(aggs) for kind, aggs in model.aggs.items()},
        agg_labels=model.agg_labels,
        colours=[_colour(c) for c in model.colours],
        totals=_pairs(model.totals),
        marks=[_mark(m) for m in model.marks],
        pin=model.pin,
        keep=_pairs(model.keep),
    )


# --- the saved views: «Хадгалах», «Засах», «Устгах» -------------------------------------------------------------------
# The rules are reports.services.saved_views. A write answers 200: ok true (redirect is the view's address after a save,
# "" when the page should refetch), or ok false with the form's own errors (field_errors, form_errors). A refused write
# changes nothing. A view the viewer may not see is 404, one they may not change is 403 (service_errors).

NEW_VIEW_TITLE = "Харагдац хадгалах"
EDIT_VIEW_TITLE = "Харагдац засах"


class ReportViewFormOut(Schema):
    title: str  # the pop-up's title
    name: str
    visibility: str  # "shared" or "private"
    is_default: bool  # opens first
    query: str  # the address the view stores: the viewer's address for a new view; "" when editing
    can_delete: bool  # the «Устгах» button: true when editing
    view_id: int | None  # the view being edited; None for a new one


class ReportViewIn(Schema):
    name: str
    visibility: str = ""  # "" is shared; an edit that leaves it out keeps the view's own visibility
    is_default: bool = False
    query: str = ""  # the address to store (a new view); ignored on an edit


class ReportViewResultOut(Schema):
    ok: bool
    redirect: str  # the address to open after a save; "" when the page should refetch
    error: str  # the service's message for a refused write; "" for the saved views (their errors are the form's)
    form_errors: list[str]
    field_errors: dict[str, list[str]]


def _view_saved(redirect: str) -> dict[str, Any]:
    return {"ok": True, "redirect": redirect, "error": "", "form_errors": [], "field_errors": {}}


def _view_refused(result: SaveResult) -> dict[str, Any]:
    return {
        "ok": False,
        "redirect": "",
        "error": "",
        "form_errors": result.form_errors,
        "field_errors": result.field_errors,
    }


@report_router.get("/{key}/views/new", response=ReportViewFormOut)
def view_new_form(request: HttpRequest, response: HttpResponse, key: str) -> ReportViewFormOut:
    """The «Хадгалах» pop-up: the address the viewer is looking at, to be stored under a name."""
    user = request_user(request)
    with service_errors():
        saved_views.saveable_report(user, key)
    response["Cache-Control"] = "no-store"
    return ReportViewFormOut(
        title=NEW_VIEW_TITLE,
        name="",
        visibility=SHARED,
        is_default=False,
        query=saved_views.initial_query(request.GET),
        can_delete=False,
        view_id=None,
    )


@report_router.get("/views/{pk}", response=ReportViewFormOut)
def view_edit_form(request: HttpRequest, response: HttpResponse, pk: int) -> ReportViewFormOut:
    """The «Засах» pop-up with the view's own values."""
    user = request_user(request)
    with service_errors():
        view = saved_views.view_for(user, pk)
    response["Cache-Control"] = "no-store"
    return ReportViewFormOut(
        title=EDIT_VIEW_TITLE,
        name=view.name,
        visibility=view.visibility,
        is_default=view.is_default,
        query="",  # the stored query was cleaned for its author, not this viewer: a manager may lack its columns
        can_delete=True,
        view_id=view.pk,
    )


@report_router.post("/{key}/views", response=ReportViewResultOut)
def view_create(request: HttpRequest, key: str, payload: ReportViewIn) -> dict[str, Any]:
    """Stores the cleaned address under the posted name. The redirect is the saved view's address."""
    user = request_user(request)
    with service_errors():
        report = saved_views.saveable_report(user, key)
    result = saved_views.create_view(user, report, payload.model_dump())
    if result.view is None:
        return _view_refused(result)
    return _view_saved(_view_url(reverse("reports:report", args=[key]), result.view.query))


@report_router.post("/views/{pk}", response=ReportViewResultOut)
def view_update(request: HttpRequest, pk: int, payload: ReportViewIn) -> dict[str, Any]:
    """Renames the view and changes who sees it and whether it opens first. The query is not used on an edit."""
    user = request_user(request)
    with service_errors():
        view = saved_views.view_for(user, pk)
    data = payload.model_dump()
    if "visibility" not in payload.model_fields_set:
        del data["visibility"]  # a body that names no visibility keeps the view's own (update_view's default)
    if "is_default" not in payload.model_fields_set:
        data["is_default"] = view.is_default  # a body that names no is_default keeps the view's current default
    result = saved_views.update_view(user, view, data)
    if result.view is None:
        return _view_refused(result)  # the view object is unchanged; only the result says what was refused
    return _view_saved("")


@report_router.post("/views/{pk}/delete", response=ReportViewResultOut)
def view_delete(request: HttpRequest, pk: int) -> dict[str, Any]:
    """Deletes the view (its author or a manager). The redirect is the bare report."""
    user = request_user(request)
    with service_errors():
        view = saved_views.view_for(user, pk)
        key = saved_views.delete_view(user, view)
    return _view_saved(reverse("reports:report", args=[key]))
