"""The report catalogue and the report page's read side, as the React pages read them.

- GET /api/v1/reports/catalogue: the report catalogue's sections. The cards, their order and their rights come from
  reports.services.catalogue_page; the route needs reports.view_reports (403 "forbidden" without it). The catalogue
  holds no personal data, so the answer is not marked no-store.
- GET /api/v1/reports/{key}: the report's head, filter bar and table layout (the first batch of the table). The query
  string IS the filters: the raw query goes to the same services the Django report page calls, so the API parses
  nothing itself. A bare address with a default saved view answers `redirect` and nothing else.
- GET /api/v1/reports/{key}/rows?offset=: one batch of the same table, with the same query.

The page and rows answers need a signed-in session (401 without one), reports.view_reports and the report's own rights
(403 "forbidden"), and an unknown key is 404. Every page and rows answer is marked Cache-Control: no-store: the rows
carry people's data (and salaries, where the viewer may see them).
"""

from typing import Any

from accounts.models import User
from django.http import HttpRequest, HttpResponse, QueryDict
from django.urls import reverse
from ninja import Router, Schema
from ninja.security import django_auth
from reports import registry
from reports.services.catalogue_page import Row, card_path, search_text, sections_for
from reports.services.filter_bar import FilterBar, FilterOptions
from reports.services.page_head import PageHead, default_view_redirect, page_head
from reports.services.table_page import CellOut, RowGroup, TablePage, parse_offset, table_page
from reports.types import Report

from api.errors import ApiError
from api.popups import FORBIDDEN, NOT_FOUND, request_user

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
    save_url: str  # the Django address of the «Хадгалах» pop-up (5b replaces it)


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


class ReportPageOut(Schema):
    redirect: str  # the default saved view's address for a bare address; "" when there is nothing to follow
    title: str
    layout: str  # the layout on screen: "table", "cards", ...
    head: ReportHeadOut | None  # None when redirect is set
    bar: ReportBarOut | None  # None when redirect is set
    table: ReportTableOut | None  # None when redirect is set or the layout is not "table"


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
            save_url=head.saved.save_url,
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
    built, as the Django page does. A layout other than the table answers the head and the bar with no table."""
    user = request_user(request)
    report = _report_for(key, user)
    response["Cache-Control"] = "no-store"
    params = _filters_query(request)
    path = reverse("reports:report", args=[key])
    target = default_view_redirect(params, False, request.method or "GET", user, report)
    if target:
        return ReportPageOut(redirect=target, title="", layout="", head=None, bar=None, table=None)
    page = table_page(params, path, user, report, parse_offset(offset))
    head = page_head(params, False, path, user, report, page.table, bool(report.saved_views))
    return ReportPageOut(
        redirect="",
        title=head.title,
        layout=page.layout,
        head=_head(head),
        bar=_bar(page.bar) if page.bar is not None else None,
        table=_table(page) if page.layout == "table" else None,
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
