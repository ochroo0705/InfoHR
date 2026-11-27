"""The «Тайлан» catalogue page (every MACS report, grouped, with a search box) and the shared report page."""

import json
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl

from accounts.audit import record_export
from accounts.models import User
from config import batching
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.vary import vary_on_headers
from employees import access, stale
from employees.images import attach_photo_digests
from employees.models import Employee

from reports import bulk_edit as bulk_edit_service
from reports import cell_edit as cell_edit_service
from reports import corrections, privacy, registry
from reports import layouts as layouts_mod
from reports import marks as marks_mod
from reports import row_edit as row_edit_service
from reports import selection as selection_mod
from reports.filters import (
    MAX_YEAR,
    MIN_MONTH_YEAR,
    parse_filters,
    to_query,
)
from reports.forms import SavedViewForm
from reports.models import SavedView
from reports.page_rules import (
    FOLDABLE,  # noqa: F401 (tests import it from views)
    PLAIN_VIEW,  # noqa: F401 (palette.py imports it from views)
    HeaderCell,  # noqa: F401 (tests import it from views)
)
from reports.page_rules import (
    address as _address,
)
from reports.page_rules import (
    builtin_panels as _builtin_panels,  # noqa: F401 (kept importable from views)
)
from reports.page_rules import (
    column_filter_panels as _column_filter_panels,  # noqa: F401 (kept importable from views)
)
from reports.page_rules import (
    month_param as _month_param,
)
from reports.page_rules import (
    next_sort as _next_sort,  # noqa: F401 (tests import it from views)
)
from reports.page_rules import (
    secondary_filters as _secondary_filters,  # noqa: F401 (tests import it from views)
)
from reports.page_rules import (
    sort_mark as _sort_mark,  # noqa: F401 (kept importable from views)
)
from reports.services import exports, layout_page, popups, saved_views
from reports.services.catalogue_page import sections_for
from reports.services.filter_bar import filter_bar
from reports.services.layout_page import CHART_LABELS
from reports.services.page_head import (
    EXPORT_PERM,
    LAYOUT_LABELS,
    SELECTION_KEYS,  # noqa: F401 (kept importable from views)
    LayoutOption,  # noqa: F401 (kept importable from views)
    SavedOption,  # noqa: F401 (kept importable from views)
    _cleaned_for,  # noqa: F401 (tests import it from views)
    _known_only,  # noqa: F401 (tests import it from views)
    _option_name,  # noqa: F401 (kept importable from views)
    _selection_urls,  # noqa: F401 (kept importable from views)
    _template_allowed,  # noqa: F401 (today_tiles uses it from views)
    _view_url,
    _viewer_query,  # noqa: F401 (today_tiles uses it from views)
    _visible_views,  # noqa: F401 (today_tiles uses it from views)
    default_view_redirect,
    layout_options,
    page_head,
    page_tools,
)
from reports.services.popups import (
    AGG_LABELS,  # noqa: F401 (kept importable from views)
    AGGS_BY_KIND,  # noqa: F401 (kept importable from views)
    FORMAT_COLOURS,  # noqa: F401 (kept importable from views)
    Pick,  # noqa: F401 (kept importable from views)
    _rule_kind,  # noqa: F401 (kept importable from views)
    check_popup,
)
from reports.services.print_page import MAX_PORTRAIT_COLUMNS, build_print  # noqa: F401 (tests import it from views)
from reports.services.saved_views import (
    DUPLICATE_NAME,  # noqa: F401 (kept importable from views)
    NAME_CONSTRAINT,  # noqa: F401 (kept importable from views)
    QUERY_LIMIT,  # noqa: F401 (tests import it from views)
    TOO_LONG,  # noqa: F401 (kept importable from views)
)
from reports.services.saved_views import (
    clear_defaults as _clear_defaults,  # noqa: F401 (kept importable from views)
)
from reports.services.saved_views import (
    default_allowed as _default_allowed,  # noqa: F401 (kept importable from views)
)
from reports.services.saved_views import (
    is_name_clash as _is_name_clash,  # noqa: F401 (kept importable from views)
)
from reports.services.saved_views import (
    saveable_report as _saveable_report,  # noqa: F401 (kept importable from views)
)
from reports.services.saved_views import (
    visibility_and_default as _visibility_and_default,  # noqa: F401 (kept importable from views)
)
from reports.services.table_page import parse_offset, table_page
from reports.table import (
    Table,
)
from reports.types import Report


@login_required
def catalogue(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("reports.view_reports"):
        raise PermissionDenied
    # Every card is drawn; ?q= only prefills the search box, and the page's own filter applies it on load.
    # Dropping cards here would leave them missing after the box is cleared.
    q = request.GET.get("q", "").strip()[:200]
    return render(request, "reports/catalogue.html", {"sections": sections_for(request.user), "q": q})


@login_required
def columns_modal(request: HttpRequest, key: str) -> HttpResponse:
    """The «Багана сонгох» pop-up: the columns the user may see (shown ones ticked) and the grouping."""
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    report = registry.get(key)
    check_popup(user, report, needs="picks_columns")
    assert report is not None  # check_popup refuses a missing report
    model = popups.columns_model(request.GET, user, report)
    context = {
        "report": report,
        "groups": model.groups,
        "group_choices": model.group_choices,
        "group": model.group,
        "group_text": model.group_text,
        "keep": model.keep,
    }
    return render(request, "reports/_columns_modal.html", context)


@login_required
def rules_modal(request: HttpRequest, key: str) -> HttpResponse:
    """The «Шүүлтүүр» pop-up: the conditions the user may use, the current ones, and the other filters kept as hidden
    inputs. Statistic reports (no count line) have no rules pop-up."""
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    report = registry.get(key)
    check_popup(user, report, needs="shows_count")
    assert report is not None  # check_popup refuses a missing report
    model = popups.rules_model(request.GET, user, report)
    context = {
        "report": report,
        "columns_json": [asdict(c) for c in model.columns],
        "ops_json": {kind: [asdict(op) for op in ops] for kind, ops in model.ops.items()},
        "rules_json": model.rules,
        "keep": model.keep,
    }
    return render(request, "reports/_rules_modal.html", context)


@login_required
def format_modal(request: HttpRequest, key: str) -> HttpResponse:
    """The «Хэлбэр» pop-up: the footer totals, the pinned columns and the colour rules the user may use, the current
    ones, and the other filters kept as hidden inputs. Statistic reports (no count line) have no format pop-up."""
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    report = registry.get(key)
    check_popup(user, report, needs="shows_count")
    assert report is not None  # check_popup refuses a missing report
    model = popups.format_model(request.GET, user, report)
    context = {
        "report": report,
        "columns_json": [asdict(c) for c in model.columns],
        "shown_json": model.shown,
        "ops_json": {kind: [asdict(op) for op in ops] for kind, ops in model.ops.items()},
        "aggs_json": model.aggs,
        "agg_labels_json": model.agg_labels,
        "colours_json": [asdict(c) for c in model.colours],
        "totals_json": [list(pair) for pair in model.totals],
        "marks_json": [asdict(m) for m in model.marks],
        "pin": model.pin,
        "keep": model.keep,
    }
    return render(request, "reports/_format_modal.html", context)


CARD_EXTRAS = 4  # the shown columns after the title and subtitle, drawn as label: value lines on a card


def _number_or_none(value: object) -> float | None:
    """A chart value as a float; None when there is nothing to aggregate or the value is not a number."""
    return float(value) if isinstance(value, int | float | Decimal) else None


def _chart_payload(chart: layouts_mod.Chart, hrefs: list[str]) -> dict[str, Any]:
    """The chart's numbers for charts.js (in #report-chart-data): labels, values as floats (None stays null),
    the kind, whether the values are money, and one click link per point (an empty text where there is none). The table
    under the chart is drawn from the same points."""
    return {
        "kind": chart.kind,
        "labels": [point.label for point in chart.points],
        "values": [_number_or_none(point.value) for point in chart.points],
        "money": any(point.money for point in chart.points),
        "percent": chart.percent,
        "value_label": chart.value_label,
        "series": [{"label": s.label, "values": [_number_or_none(v) for v in s.values]} for s in chart.series],
        "hrefs": hrefs,
    }


def _layout_context(
    request: HttpRequest, user: User, report: Report, table: Table, adds: list[str], plain: bool
) -> tuple[dict[str, Any], batching.Batch[layouts_mod.Item] | None]:
    """The switcher, the layout bar and the drawing of the layout the table chose (the table itself draws nothing here).
    Also returns the cards' batch when the layout is cards, so the view can answer a «Цааш харуулах» request with the
    cards alone."""
    f = table.filters
    spec = table.spec
    marks = marks_mod.parse_marks(f.marks)
    today = timezone.localdate()
    options = layout_options(request.path, user, report, f, spec.layout, adds, plain)  # the switcher's segments
    names = [option.name for option in options]
    urls = {option.name: option.url for option in options}
    # the layout bar's flags: a date category grouped by a grain («Хуваалт»), and whether the sort applies
    dated = any(c is not None and c.kind == "date" for c in (spec.by, spec.by2))
    sort_ok = not (spec.by is not None and spec.by.kind == "date" and spec.grain)
    bar = layout_page.layout_bar(report, user, spec, f, adds, dated, sort_ok)
    context: dict[str, Any] = {
        "layout": spec.layout,
        "layout_names": names,
        "layout_urls": urls,
        "layout_options": options,
        "layout_label": LAYOUT_LABELS,
        "layout_template": f"reports/layouts/{spec.layout}.html",
        "layout_choices": layouts_mod.layout_choices(report, user, spec.layout, spec.by.key if spec.by else ""),
        "layout_value": layouts_mod.value_text(spec.value),
        "layout_value2": layouts_mod.value_text(spec.value2) if spec.value2 is not None else "",  # the «Утга 2» select
        "layout_grain": spec.grain,  # the «Хуваалт» select: shown when a chart or pivot groups by a date column
        "layout_dated": dated,
        "layout_sort_ok": sort_ok,  # the «Эрэмбэ» select: a date category is in time order, so the sort does not apply
        "layout_keep": bar.keep,  # hidden inputs of the layout bar's form
        "chart_labels": CHART_LABELS,
        "spec": spec,
        "min_group": privacy.min_group(),  # the chart and pivot notes say how small a group is hidden
    }
    # the click-through of the category layouts (layout_page.drill_for): the column kinds and grains, and the colliding
    # keys of each category, so a key that collides with another (case, spaces) or a blank grained bucket gets no link
    drill = layout_page.drill_for(
        table, spec, layout_page.LinkBase(path=request.path, f=f, adds=tuple(adds), plain=plain)
    )

    def pivot_parts(grid: layouts_mod.Pivot) -> tuple[list[tuple[str, str]], list[Any]]:
        """A pivot grid's column heads as (label, link), and one line per row: its label and link, its cells with their
        links, and its total. Both grids of a pivot with a second value are drawn with it, so their links match."""
        col_heads = [
            (label, drill([(spec.by2, drill.unless(key, drill.by2_bad, drill.by2_grained))]))
            for label, key in zip(grid.col_labels, grid.col_keys, strict=True)
        ]
        # one line per row: its label and link, its cells with their links, and its total (a template cannot index
        # cells by row). Without a second category the single column is the row itself, so a cell links to the row.
        lines = []
        for i, (label, cells, total) in enumerate(zip(grid.row_labels, grid.cells, grid.row_totals, strict=True)):
            row_key = drill.unless(grid.row_keys[i], drill.by_bad, drill.by_grained)
            row_href = drill([(spec.by, row_key)])
            cell_links = []
            for j, value in enumerate(cells):
                col_key = drill.unless(grid.col_keys[j], drill.by2_bad, drill.by2_grained)
                href = row_href if spec.by2 is None else drill([(spec.by, row_key), (spec.by2, col_key)])
                cell_links.append((value, href))
            lines.append((label, row_href, cell_links, total))
        return col_heads, lines

    cards: batching.Batch[layouts_mod.Item] | None = None
    if spec.layout == "board":
        board = layouts_mod.build_board(table, spec, marks, today)
        context["board"] = board
        context["board_lanes"] = [
            (lane, drill([(spec.by, drill.unless(lane.key, drill.by_bad))])) for lane in board.lanes
        ]
        context["board_value_label"] = layouts_mod.value_caption(spec.value)  # «Утга: …»; "" = the count, nothing shown
    elif spec.layout == "calendar" and spec.week is not None:
        week = layouts_mod.build_week(table, spec, marks, today)
        context["week"] = week
        context["week_prev_url"] = _address(request.path, replace(f, lweek=week.prev, lmonth=""), adds, plain=plain)
        context["week_next_url"] = _address(request.path, replace(f, lweek=week.next, lmonth=""), adds, plain=plain)
        this_monday = layouts_mod.week_start(today).isoformat()
        context["week_today_url"] = _address(request.path, replace(f, lweek=this_monday, lmonth=""), adds, plain=plain)
        month_text = _month_param(week.start, today)
        context["week_month_url"] = _address(request.path, replace(f, lweek="", lmonth=month_text), adds, plain=plain)
    elif spec.layout == "calendar":
        calendar = layouts_mod.build_calendar(table, spec, marks, today)
        context["calendar"] = calendar
        context["calendar_prev_url"] = _address(request.path, replace(f, lmonth=calendar.prev), adds, plain=plain)
        context["calendar_next_url"] = _address(request.path, replace(f, lmonth=calendar.next), adds, plain=plain)
        context["calendar_today_url"] = _address(request.path, replace(f, lmonth=""), adds, plain=plain)
        # the month form's hidden inputs: every parameter but lmonth (the layout, its columns, the filters)
        context["calendar_keep"] = parse_qsl(to_query(replace(f, lmonth=""))) + [("add", name) for name in adds]

        def week_address(day: date) -> str:
            """The address of the week that holds this day: the month grid's «+N» link."""
            week_text = layouts_mod.week_start(day).isoformat()
            return _address(request.path, replace(f, lweek=week_text, lmonth=""), adds, plain=plain)

        # the «7 хоног» link: the week of today when this month is the current one, else the week of the month's 1st
        anchor = today if (calendar.month.year, calendar.month.month) == (today.year, today.month) else calendar.month
        context["calendar_week_url"] = week_address(anchor)
        # every day of the grid with the link of its week when it has a «+N» count (a template cannot index a dict)
        context["calendar_cells"] = [
            [(day, week_address(day.day) if day.more else "") for day in week] for week in calendar.weeks
        ]
    elif spec.layout == "timeline":
        timeline = layouts_mod.build_timeline(table, spec, marks, today)
        context["timeline"] = timeline
        context["timeline_years"] = layouts_mod.TIMELINE_YEARS
        # the year window (lyear): the default is this year; the arrows step one year and stop at the bounds; «Бүгд»
        # sets lyear=all (no window, the 5-year axis); without a window «Он» opens the year of today (clamped to the
        # allowed years), whatever the axis holds
        window = spec.year
        context["timeline_year_prev_url"] = (
            _address(request.path, replace(f, lyear=str(window - 1)), adds, plain=plain)
            if window is not None and window > MIN_MONTH_YEAR
            else None
        )
        context["timeline_year_next_url"] = (
            _address(request.path, replace(f, lyear=str(window + 1)), adds, plain=plain)
            if window is not None and window < MAX_YEAR
            else None
        )
        context["timeline_all_url"] = _address(request.path, replace(f, lyear="all"), adds, plain=plain)
        enter_year = min(max(today.year, MIN_MONTH_YEAR), MAX_YEAR)
        context["timeline_year_enter_url"] = _address(
            request.path, replace(f, lyear=str(enter_year)), adds, plain=plain
        )
    elif spec.layout == "chart":
        chart = layouts_mod.build_chart(table, spec)
        context["chart"] = chart
        chart_hrefs = [drill([(spec.by, drill.unless(key, drill.by_bad, drill.by_grained))]) for key in chart.keys]
        context["chart_lines"] = [
            (point, cells, href) for (point, cells), href in zip(chart.lines, chart_hrefs, strict=True)
        ]
        context["chart_json"] = _chart_payload(chart, chart_hrefs)
        context["chart_kind_label"] = CHART_LABELS[chart.kind]
    elif spec.layout == "pivot":
        pivot = layouts_mod.build_pivot(table, spec)
        context["pivot"] = pivot
        context["pivot_col_heads"], context["pivot_lines"] = pivot_parts(pivot)
        if spec.value2 is not None:  # a second value: the same rows, columns and links; lshow applies to the first only
            pivot2 = layouts_mod.build_pivot(table, replace(spec, value=spec.value2, show=""))
            context["pivot2"] = pivot2
            context["pivot2_col_heads"], context["pivot2_lines"] = pivot_parts(pivot2)
    elif spec.layout == "cards":
        items = layouts_mod.make_items(table, table.rows, marks, today, extras=CARD_EXTRAS, photo_of=report.photo)
        cards = batching.window(request, items)
        if report.photo is not None:  # one query for the photos on show, not one per card
            attach_photo_digests(i.photo for i in cards.shown if i.photo is not None)
        context["cards_items"] = cards.shown
        context["cards_next_query"] = cards.next_query
    return context, cards


@login_required
@vary_on_headers("HX-Request")
def report_page(request: HttpRequest, key: str) -> HttpResponse:
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    report = registry.get(key)
    if report is None:
        raise Http404
    if not registry.can_open(user, report):
        raise PermissionDenied
    # the bare address opens the report's default saved view; the target has a query, so it never loops. Answered
    # before the table is built (the API answers the same address as `redirect`, reports.services.page_head)
    target = default_view_redirect(
        request.GET, bool(request.headers.get("HX-Request")), request.method or "GET", user, report
    )
    if target:
        return redirect(target)
    # only an htmx request may ask for a later batch (config.batching.window reads the offset the same way)
    htmx = request.headers.get("HX-Request") and not request.headers.get("HX-History-Restore-Request")
    offset = parse_offset(request.GET.get("offset", "")) if htmx else 0
    # a batch answer (htmx with an offset) skips the filter bar: its option lists are queries the batch never draws
    page = table_page(request.GET, request.path, user, report, offset, with_bar=not offset)
    table = page.table
    f = table.filters
    plain = bool(report.saved_views)  # an empty address then says view=plain, not the bare default-view address
    tools = page_tools(user, report, table)  # cheap: the batch answers need these flags, not the saved views
    adds = page.adds  # the picker's chips without a value yet; never stored
    layout_context, cards = _layout_context(request, user, report, table, adds, plain)
    # the batch answers below draw no bar; any other answer needs it (a grouped or other-layout htmx request too)
    is_batch = (page.batched and bool(offset)) or (cards is not None and bool(cards.offset))
    bar = page.bar
    if bar is None and not is_batch:
        bar = filter_bar(request.GET, request.path, user, report, table, plain)
    table_layout = page.layout == "table"
    next_query = ""
    if page.next_offset is not None:
        # the «Цааш харуулах» pill asks for the next batch of this same address
        params = request.GET.copy()
        params["offset"] = str(page.next_offset)
        next_query = params.urlencode()
    context = {
        "report": report,
        "filters": f,
        "rules_text": page.rules_text,
        "clear_rules_url": page.clear_rules_url,
        "query": page.query,
        "print_url": tools.print_url,
        "excel_url": tools.excel_url,
        "table": table,
        "heads": page.heads,
        "shown_rows": table.groups[0][1] if page.batched else [],
        "next_query": next_query,
        "batch_url": request.path,
        "staff_actions": tools.staff_actions,  # hire and import beside the title
        "note": page.note,
        # row selection: a table of a report that names its people (Report.person); the checkbox column adds one cell
        "selectable": tools.selectable,
        # the cells that name an employee field open the inline editor: plain fields for managers, salary and insurance
        # fields for the salary right (reports.cell_edit.can_edit checks each row); _rows.html tells them apart
        "can_edit_cells": page.can_edit_cells,
        "plain_cells": access.can_manage(user),
        "salary_cells": access.can_manage_salary(user),
        "salary_fields": cell_edit_service.SALARY_EDITABLE,
        # the cells that correct a job field or the salary with a reason (reports.corrections, D-080 phase 4)
        "can_correct_cells": page.can_correct_cells,
        "can_correct_salary": (
            table_layout and corrections.enabled() and access.can_manage(user) and access.can_manage_salary(user)
        ),
        # the cells of a children or contacts row open the row editor (reports.row_edit); the server checks each row
        "can_edit_rows": page.can_edit_rows,
        "selection_urls": tools.selection_urls,
        "selection_total": table.count,
        "selection_over_cap": table.count > selection_mod.MAX_PEOPLE,
        # the checkbox column is sticky at the far left when columns are pinned (table.pin_base offsets the rest)
        "check_pinned": page.selectable and page.pin > 0,
        "check_css": page.check_css,
        "check_style": page.check_style,
        "selection_max": selection_mod.MAX_PEOPLE,
        "table_span": page.table_span,
    }
    if bar is not None:
        context.update(bar.context)  # the filter bar: its drawn filters, option lists, picker and column chips
    context.update(layout_context)
    if page.batched and offset:
        # the «Цааш харуулах» pill asked for the next batch: only its rows and the pill after them go back
        return render(request, "reports/_batch_rows.html", context)
    if cards is not None and cards.offset:
        return render(request, "reports/layouts/_cards_batch.html", context)
    # the saved views and the switcher's head cost queries: only the full page asks for them (not the batch answers)
    head = page_head(
        request.GET,
        bool(request.headers.get("HX-Request")),
        request.path,
        user,
        report,
        table,
        plain,
        method=request.method or "GET",
    )
    saved = head.saved
    if saved is not None:  # the title-row controls: the views, the templates and the one the address matches
        context.update(
            plain_url=saved.plain_url,
            saved_options=saved.options,
            current_view=saved.current_view,
            can_edit_view=saved.can_edit_view,
            template_options=saved.templates,
            template_current=saved.template_current,
        )
    response = render(request, "reports/report.html", context)
    if request.headers.get("HX-Request"):
        # the filter form pushes the raw address it sent; the address bar gets the cleaned one, so no old year is kept
        response["HX-Push-Url"] = page.address
    return response


@login_required
def report_print(request: HttpRequest, key: str) -> HttpResponse:
    """The print page: the same table as the screen, with the filters named at the top (orders_print style)."""
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    report = registry.get(key)
    if report is None:
        raise Http404
    if not registry.can_open(user, report):
        raise PermissionDenied
    page = build_print(user, report, parse_filters(request.GET))
    context = {
        "report": report,
        "table": page.table,
        "heads": page.heads,
        "lines": page.lines,
        "note": page.note,
        "summary": page.summary,  # a chart or pivot address adds its numbers above the row table
        "min_group": page.min_group,  # the note under the summary says how small a group is hidden
        "landscape": page.landscape,
        "company": page.company,
        "today": date.fromisoformat(page.today),
        "printed_by": page.printed_by,
    }
    response = render(request, "reports/print.html", context)
    record_export(request, "print_page", report.title, filters=page.log_label, rows=page.count)
    return response


@login_required
def report_excel(request: HttpRequest, key: str) -> HttpResponse:
    """The Excel file of the report as the address shows it: the same visible columns, sort and groups as the screen."""
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    report = registry.get(key)
    if report is None:
        raise Http404
    if not registry.can_open(user, report) or not user.has_perm(EXPORT_PERM):
        raise PermissionDenied
    exported = exports.excel_file(user, report, parse_filters(request.GET))
    response = HttpResponse(exported.body, content_type=exported.content_type)
    response["Content-Disposition"] = f'attachment; filename="{exported.filename}"'
    record_export(request, exported.log_action, report.title, filters=exported.log_label, rows=exported.rows)
    return response


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)  # login_required guarantees a real user
    return request.user


def _view_for(request: HttpRequest, pk: int) -> SavedView:
    """A saved view the user may rename or delete: 404 if missing, 403 if the user may not change it."""
    return saved_views.view_for(_user(request), pk)


def _view_modal(
    request: HttpRequest, title: str, form: SavedViewForm, action: str, view: SavedView | None
) -> HttpResponse:
    context = {"title": title, "form": form, "action": action, "view": view}
    return render(request, "reports/_view_modal.html", context)


def _modal_form(data: QueryDict | dict[str, Any], result: saved_views.SaveResult) -> SavedViewForm:
    """The «Хадгалах» / «Засах» form bound to what was posted, with the service's errors on it. The form has already
    shown its own errors when the service ran it, so an error it holds is not added twice."""
    form = SavedViewForm(data)
    form.is_valid()
    for name, messages in result.field_errors.items():
        shown = [str(m) for m in form.errors.get(name, [])]
        for message in messages:
            if message not in shown:
                form.add_error(name, message)
    shown_general = [str(m) for m in form.non_field_errors()]
    for message in result.form_errors:
        if message not in shown_general:
            form.add_error(None, message)
    return form


@login_required
def view_new(request: HttpRequest, key: str) -> HttpResponse:
    """The «Хадгалах» pop-up. Saves the cleaned address under a name; every user who can open the report sees it."""
    user = _user(request)
    report = saved_views.saveable_report(user, key)
    action = reverse("reports:view_new", args=[key])
    if request.method != "POST":
        initial = {"query": saved_views.initial_query(request.GET)}
        return _view_modal(request, "Харагдац хадгалах", SavedViewForm(initial=initial), action, None)
    result = saved_views.create_view(user, report, request.POST)
    if result.view is None:
        return _view_modal(request, "Харагдац хадгалах", _modal_form(request.POST, result), action, None)
    response = HttpResponse(status=204)
    response["HX-Redirect"] = _view_url(reverse("reports:report", args=[key]), result.view.query)
    return response


@login_required
def view_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """The «Засах» pop-up: rename the view, change who sees it and whether it opens first, or delete it after the
    «устгах уу?» question."""
    user = _user(request)
    view = _view_for(request, pk)
    action = reverse("reports:view_edit", args=[pk])
    title = "Харагдац засах"
    if request.method != "POST":
        initial = {"name": view.name, "visibility": view.visibility, "is_default": view.is_default}
        return _view_modal(request, title, SavedViewForm(initial=initial), action, view)
    data = request.POST.copy()
    data.setdefault("visibility", view.visibility)  # a POST that names no visibility keeps the view's own
    result = saved_views.update_view(user, view, data)
    if result.view is None:
        return _view_modal(request, title, _modal_form(data, result), action, view)
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"  # the address keeps the same setup, so the page reloads on the same view
    return response


@login_required
@require_POST
def view_delete(request: HttpRequest, pk: int) -> HttpResponse:
    view = _view_for(request, pk)
    key = saved_views.delete_view(_user(request), view)
    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse("reports:report", args=[key])
    return response


@login_required
@require_http_methods(["GET", "POST"])
def cell_edit(request: HttpRequest) -> HttpResponse:
    """The inline editor of one employee field in a report cell (reports.cell_edit). GET opens the editor; POST saves
    it: the new shown value when ok, else the editor again with the message. `person` and `field` come from the
    address on both methods. 404 for an unknown employee or field, 403 when the user may not change it."""
    user = request.user
    field = request.GET.get("field", "")
    try:
        person = int(request.GET.get("person", ""))
    except ValueError:
        raise Http404 from None
    if field not in cell_edit_service.EDITABLE and field not in cell_edit_service.SALARY_EDITABLE:
        raise Http404
    employee = get_object_or_404(access.visible_employees(user), pk=person)
    if not cell_edit_service.can_edit(user, employee, field):
        raise PermissionDenied
    if request.method == "POST":
        result = cell_edit_service.save(user, person, field, request.POST)
        if result.ok:
            return HttpResponse(format_html("<span data-cell-value>{}</span>", result.text))
        if result.error == cell_edit_service.CLASH:
            # someone else changed the value meanwhile: the editor shows the current value with a fresh snapshot, so
            # the user sees what is stored now and a retry can succeed (the old snapshot would clash again)
            current = cell_edit_service.editor_form(user, Employee.objects.get(pk=person), field)
            return render(
                request,
                "reports/_cell_editor.html",
                {
                    "form": current,
                    "field": current[field],
                    "field_name": field,
                    "loaded": stale.snapshot(current),
                    "error": result.error,
                },
            )
        # the editor again, with the user's text still in it and the snapshot they loaded (not a fresher one)
        bound = cell_edit_service.editor_form(
            user, employee, field, cell_edit_service.posted_data(user, employee, field, request.POST)
        )
        return render(
            request,
            "reports/_cell_editor.html",
            {
                "form": bound,
                "field": bound[field],
                "field_name": field,
                "loaded": request.POST.get("loaded", ""),
                "error": result.error,
            },
        )
    form = cell_edit_service.editor_form(user, employee, field)
    return render(
        request,
        "reports/_cell_editor.html",
        {"form": form, "field": form[field], "field_name": field, "loaded": "", "error": ""},
    )


def _row_editor(request: HttpRequest, form: Any, field: str, error: str) -> HttpResponse:
    """The editor of one row cell: the one visible field, and the other fields of the row form as hidden inputs (the
    row's values and the loaded_* values of the stale check travel back with the save)."""
    hidden = [form[name] for name in form.fields if name != field]
    context = {"form": form, "visible": form[field], "hidden": hidden, "error": error}
    return render(request, "reports/_row_cell_editor.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def row_cell(request: HttpRequest) -> HttpResponse:
    """The inline editor of one cell of a children or contacts row (reports.row_edit). Query: `person`, `kind`, `key`
    (the row's id) and `field`. GET opens the editor; POST saves it: the new shown text when ok, else the editor again
    with the message. 404 for an unknown kind, field, employee or row; 403 when the user may not change the row."""
    user = request.user
    kind = request.GET.get("kind", "")
    field = request.GET.get("field", "")
    try:
        person = int(request.GET.get("person", ""))
        key = int(request.GET.get("key", ""))
    except ValueError:
        raise Http404 from None
    if kind not in row_edit_service.KINDS or field not in row_edit_service.KINDS[kind]:
        raise Http404
    employee = get_object_or_404(access.visible_employees(user), pk=person)
    if request.method == "POST":
        result = row_edit_service.save(user, employee, kind, key, field, request.POST)
        if result.ok:
            return HttpResponse(format_html("<span data-cell-value>{}</span>", result.text))
        if result.conflict:
            # the row changed meanwhile: the editor shows its current values with a fresh snapshot, so the user sees
            # what is stored now and a retry can succeed (the posted snapshot would clash again)
            form, _ = row_edit_service.editor(user, employee, kind, key, field)
        else:
            form, _ = row_edit_service.editor(user, employee, kind, key, field, request.POST)
        return _row_editor(request, form, field, result.error)
    form, _ = row_edit_service.editor(user, employee, kind, key, field)
    return _row_editor(request, form, field, "")


def _correct_editor(
    request: HttpRequest,
    key: str,
    record: Any,
    *,
    old: str,
    reason: str = "",
    error: str = "",
    data: QueryDict | None = None,
    blocked: str = "",
) -> HttpResponse:
    """The correction editor of one cell: the field's own widget, the reason box and the grey note. When `blocked` is
    the reason the cell cannot be corrected now, the editor shows only that message (nothing to type, nothing saved)."""
    context: dict[str, Any] = {"key": key, "old": old, "reason": reason, "error": error, "blocked": blocked}
    if not blocked:
        form = corrections.form_for(request.user, record, key, data)
        context.update(form=form, field=form[corrections.field_of(key)])
    return render(request, "reports/_correct_editor.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def correct_cell(request: HttpRequest) -> HttpResponse:
    """The editor that corrects a job field (department, position, manager) or the base salary of one report cell
    (reports.corrections, D-080 phase 4). Query: `person`, `key`, and `record` (the job record, job keys only). GET
    opens the editor; POST saves it: the new shown text when ok, else the editor again with the message. A cell that
    is not the record in force today, or whose change is scheduled or awaits its signed order, gets the editor with
    only the message and no save. 404 for an unknown employee, key or record; 403 when the user may not correct this
    cell (or the setting is off), checked before the record is looked up."""
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    key = request.GET.get("key", "")
    if key not in corrections.KEYS:
        raise Http404
    try:
        person = int(request.GET.get("person", ""))
    except ValueError:
        raise Http404 from None
    record_id: int | None = None
    if corrections.KEYS[key] == "job":
        try:
            record_id = int(request.GET.get("record", ""))
        except ValueError:
            raise Http404 from None
    employee = get_object_or_404(access.visible_employees(user), pk=person)
    if not corrections.can_correct(user, employee, key):
        raise PermissionDenied
    record, blocked = corrections.lookup(employee, key, record_id)
    if record is None:
        raise Http404
    if request.method == "POST":
        if blocked:  # nothing is written: the same message again
            return _correct_editor(request, key, record, old=corrections.shown_text(record, key), blocked=blocked)
        result = corrections.save(user, employee, key, record, request.POST)
        if result.ok:
            return HttpResponse(format_html("<span data-cell-value>{}</span>", result.text))
        if result.error == cell_edit_service.CLASH:
            # someone else changed the cell: the editor shows what is stored now, so a retry can succeed
            fresh, fresh_blocked = corrections.lookup(employee, key, record_id)
            if fresh is None:
                raise Http404
            return _correct_editor(
                request,
                key,
                fresh,
                old=corrections.shown_text(fresh, key),
                error=result.error,
                blocked=fresh_blocked,
            )
        # the editor again, with the user's text and the old text they loaded (not a fresher one)
        return _correct_editor(
            request,
            key,
            record,
            old=request.POST.get("old", ""),
            reason=request.POST.get("reason", ""),
            error=result.error,
            data=request.POST,
        )
    return _correct_editor(request, key, record, old=corrections.shown_text(record, key), blocked=blocked)


@login_required
@require_http_methods(["POST"])
def cells_bulk(request: HttpRequest) -> HttpResponse:
    """Bulk cell edit (reports.bulk_edit, D-080 phase 3). The JSON body is a batch of cells: a dry run when `apply` is
    false, a save of the ok cells when true. Answers the outcome of every cell. 400 for a body of the wrong shape or
    over 500 cells; a field that is not editable is a refused cell, not a 400."""
    try:
        body = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": bulk_edit_service.BAD_REQUEST}, status=400)
    try:
        apply, cells = bulk_edit_service.parse_body(body)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    outcomes = bulk_edit_service.run(request.user, cells, apply=apply)
    saved = sum(1 for outcome in outcomes if outcome.ok) if apply else 0
    return JsonResponse({"cells": [asdict(outcome) for outcome in outcomes], "saved": saved})
