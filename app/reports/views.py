"""The «Тайлан» catalogue page (every MACS report, grouped, with a search box) and the shared report page."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode

from accounts.audit import record_export
from accounts.models import User
from config import batching
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.vary import vary_on_headers
from employees import access, listing
from employees.models import CompanySettings
from macs.models import (
    AbsenceType,
    Branch,
    ContactType,
    Department,
    DisciplineType,
    FiredReason,
    LeaveTypeRow,
    Position,
    PresentType,
)

from reports import excel, registry
from reports import layouts as layouts_mod
from reports import marks as marks_mod
from reports import rules as rules_mod
from reports import totals as totals_mod
from reports.catalogue import CATALOGUE, GROUPS, Entry
from reports.column_filters import COLUMN_FILTERS, params_of
from reports.filters import (
    ATTRIBUTES,
    EMPTYPES,
    GENDERS,
    LEAVE_STATES,
    MAX_SORT_KEYS,
    MOVEMENT_KINDS,
    NO_WORKING_STATE,
    ORDER_TYPES,
    STATES,
    TRAINING_TYPES,
    Filters,
    describe,
    parse_filters,
    period_of,
    this_quarter,
    to_query,
)
from reports.forms import SavedViewForm
from reports.kinds import KINDS
from reports.layouts import offered_layouts
from reports.models import SavedView
from reports.table import (
    Table,
    allowed_columns,
    build_table,
    column_classes,
    css_classes,
    offered_column_filters,
    offered_filters,
    pin_style,
    restricted_filters,
    shown_keys,
    usable_filters,
)
from reports.types import Column, Report, Template

MAX_PORTRAIT_COLUMNS = 7  # more columns than this print on A4 landscape
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_PERM = "accounts.export_lists"  # the Excel file and its button
DUPLICATE_NAME = "Ийм нэртэй харагдац байна."
TOO_LONG = "Харагдац хэт урт байна."
NAME_CONSTRAINT = "reports_savedview_unique_name"  # UniqueConstraint(report, name) on SavedView
QUERY_LIMIT = SavedView._meta.get_field("query").max_length  # the stored query is cut at this many characters
SHARED = "shared"  # SavedView.visibility: every user who may open the report sees the view
PRIVATE = "private"  # SavedView.visibility: only the author sees the view
MANAGE_PERM = "reports.manage_saved_views"  # may change any saved view, and see private views with no author


@dataclass(frozen=True)
class Row:
    entry: Entry
    link: bool  # the report is built and the user may open it; otherwise greyed «удахгүй»
    empty: bool  # the built report's main table has no rows yet («бүртгэл алга»)


@dataclass(frozen=True)
class Section:
    title: str
    rows: list[Row]


def _row(user: User | AnonymousUser, entry: Entry) -> Row | None:
    report = registry.get(entry.key)
    if report is None:
        return Row(entry=entry, link=False, empty=False)
    if not registry.can_open(user, report):
        return None  # a built report the user may not open is not listed
    empty = report.source is not None and not report.source._default_manager.exists()
    return Row(entry=entry, link=True, empty=empty)


@login_required
def catalogue(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("reports.view_reports"):
        raise PermissionDenied
    # Every card is drawn; ?q= only prefills the search box, and the page's own filter applies it on load.
    # Dropping cards here would leave them missing after the box is cleared.
    q = request.GET.get("q", "").strip()[:200]
    sections: list[Section] = []
    for code, title in GROUPS:
        rows: list[Row] = []
        for entry in CATALOGUE:
            if entry.group != code:
                continue
            row = _row(request.user, entry)
            if row is not None:
                rows.append(row)
        if rows:
            sections.append(Section(title=title, rows=rows))
    return render(request, "reports/catalogue.html", {"sections": sections, "q": q})


@dataclass(frozen=True)
class HeaderCell:
    label: str
    href: str  # the address that sorts the table by this column (a second click reverses it)
    append_href: str  # the address that adds this column to the sort, or flips it (Shift+click)
    arrow: str  # "↑", "↓" on the sorted column, "↑1", "↓2" when several keys sort, else ""
    cls: str  # alignment classes
    sticky_left: str = ""  # the inline offset of a pinned column, "" when not pinned (table.pin_style)

    @property
    def css(self) -> str:
        """The th's classes on the screen: alignment and pinning."""
        return css_classes(self.cls, "", self.sticky_left)


# The address of a view with an empty cleaned query: a parameter, so the bare-address default does not apply.
PLAIN_VIEW = "view=plain"


def _address(path: str, f: Filters, adds: Sequence[str] = (), *, plain: bool = False) -> str:
    """The report's address for these filters. `adds` are the column filters named by `add` (the picker's ephemeral
    chips): they go in the address bar only, never in the filters, print or Excel. `plain` (a report with saved views)
    makes an empty query read `view=plain`, so the bare address does not open the default view again."""
    query = "&".join(part for part in (to_query(f), urlencode([("add", name) for name in adds])) if part)
    if query:
        return f"{path}?{query}"
    return f"{path}?{PLAIN_VIEW}" if plain else path


def _added_names(get: QueryDict, offered: list[str]) -> list[str]:
    """The column filters named by `add`, in the order given. Only names the user may use; a repeat is kept once."""
    names: list[str] = []
    for name in get.getlist("add"):
        if name in offered and name not in names:
            names.append(name)
    return names


def _column_filter_panels(
    path: str, f: Filters, offered: list[str], adds: list[str], plain: bool = False
) -> tuple[list[tuple[str, str, str]], list[dict[str, Any]]]:
    """The picker's entries (name, label, href) for the offered filters not yet shown, and the chips (dicts) for the
    shown ones. A filter is shown when it has a value or `add` names it. Code-list rows are read for shown chips
    only."""
    given = dict(f.extra)
    choices: list[tuple[str, str, str]] = []
    chips: list[dict[str, Any]] = []
    for name in offered:
        cf = COLUMN_FILTERS[name]
        params = params_of(cf)
        if name not in adds and not any(p in given for p in params):
            choices.append((name, cf.label, _address(path, f, [*adds, name], plain=plain)))
            continue
        options: list[tuple[str, str]] = []
        if cf.kind == "code" and cf.model is not None:
            rows = cf.model._default_manager.order_by("name").values_list("pk", "name")
            options = [(str(pk), label or "—") for pk, label in rows]  # a row with no name reads «—», not «None»
        elif cf.kind == "choice":
            options = [(str(key), label) for key, label in cf.choices]
        values = [given.get(p, "") for p in params]
        # removing the chip drops its values and its add entry; the other filters and add names stay
        rest = replace(f, extra=tuple(pair for pair in f.extra if pair[0] not in params))
        chips.append(
            {
                "name": name,
                "label": cf.label,
                "kind": cf.kind,
                "options": options,
                "values": values,
                "remove_href": _address(path, rest, [a for a in adds if a != name], plain=plain),
            }
        )
    return choices, chips


def _next_sort(current: str, key: str, append: bool = False) -> str:
    """The sort after a click on a column header. A plain click sorts by this column alone: ascending, descending on
    the second click, ascending again on the third. Shift+click (append) adds the column after the other keys,
    ascending, or flips its direction where it already is; it never removes a key."""
    keys = [part for part in current.split(",") if part]
    if not append:
        return f"-{key}" if current == key else key
    if any(part.removeprefix("-") == key for part in keys):
        return ",".join(
            (part[1:] if part.startswith("-") else f"-{part}") if part.removeprefix("-") == key else part
            for part in keys
        )
    if len(keys) >= MAX_SORT_KEYS:
        return current
    return ",".join([*keys, key])


def _sort_mark(sort: str, key: str) -> str:
    """A column's arrow: "↑" for ascending, "↓" for descending, "" when it is not sorted. With two or more keys the
    arrow carries the column's place in the sort ("↑1", "↓2")."""
    keys = [part for part in sort.split(",") if part]
    for place, part in enumerate(keys, start=1):
        if part.removeprefix("-") != key:
            continue
        arrow = "↓" if part.startswith("-") else "↑"
        return f"{arrow}{place}" if len(keys) >= 2 else arrow
    return ""


def _group_text(group: str, choices: Sequence[Column]) -> str:
    """The label of a grouping with several keys ("a,b"), as the «Бүлэглэх» select shows it: the column labels joined.
    Empty for one key or none, which the select's own options show."""
    if "," not in group:
        return ""
    labels = {c.key: c.label for c in choices}
    return " · ".join(labels.get(key, key) for key in group.split(","))


@dataclass(frozen=True)
class Pick:
    key: str
    label: str
    checked: bool  # the column is shown now


@login_required
def columns_modal(request: HttpRequest, key: str) -> HttpResponse:
    """The «Багана сонгох» pop-up: the columns the user may see (shown ones ticked) and the grouping."""
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    report = registry.get(key)
    if report is None or not report.picks_columns:
        raise Http404
    if not registry.can_open(user, report):
        raise PermissionDenied
    f = parse_filters(request.GET)
    allowed = allowed_columns(report, user)
    shown = set(shown_keys(report, user, f))
    by_group: dict[str, list[Pick]] = {}
    for c in allowed:
        by_group.setdefault(c.group, []).append(Pick(key=c.key, label=c.label, checked=c.key in shown))
    group_choices: list[Column] = [c for c in allowed if c.key in report.group_options]
    context = {
        "report": report,
        "groups": list(by_group.items()),
        "group_choices": group_choices,
        "group": f.group,
        "group_text": _group_text(f.group, group_choices),
        # the filters the form keeps as hidden inputs: every current filter except the columns and the grouping
        # the chips named by `add` survive the pop-up's round trip too, as the page's own filter form keeps them
        # the hidden inputs carry this viewer's cleaned address, so a hidden column key never echoes back
        "keep": parse_qsl(to_query(replace(_cleaned_for(user, report, f), columns=(), group="")))
        + [("add", name) for name in _added_names(request.GET, offered_column_filters(report, user))],
    }
    return render(request, "reports/_columns_modal.html", context)


def _rule_kind(column: Column) -> str:
    """The kind a pop-up can use without rows: the column's own kind, else number for amounts, else text."""
    if column.kind in KINDS:
        return column.kind
    return "number" if column.numeric or column.money else "text"


@login_required
def rules_modal(request: HttpRequest, key: str) -> HttpResponse:
    """The «Шүүлтүүр» pop-up: the conditions the user may use, the current ones, and the other filters kept as hidden
    inputs. Statistic reports (no count line) have no rules pop-up."""
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    report = registry.get(key)
    if report is None or not report.shows_count:
        raise Http404
    if not registry.can_open(user, report):
        raise PermissionDenied
    f = parse_filters(request.GET)
    allowed = allowed_columns(report, user)
    current = rules_mod.restrict(rules_mod.parse_rules(f.rules), {c.key for c in allowed})
    context = {
        "report": report,
        "columns_json": [{"key": c.key, "label": c.label, "kind": _rule_kind(c)} for c in allowed],
        "ops_json": {
            kind: [{"code": code, "label": rules_mod.OP_LABELS[code]} for code in codes]
            for kind, codes in rules_mod.OPS.items()
        },
        "rules_json": rules_mod.dump_rules(current),
        # every current filter except the rules, as the page's own filter form keeps them; the `add` chips survive too
        "keep": parse_qsl(to_query(replace(_cleaned_for(user, report, f), rules="")))
        + [("add", name) for name in _added_names(request.GET, offered_column_filters(report, user))],
    }
    return render(request, "reports/_rules_modal.html", context)


# the colour names of the «Хэлбэр» pop-up, in the order the pop-up offers them
FORMAT_COLOURS = (("red", "Улаан"), ("amber", "Шар"), ("green", "Ногоон"), ("blue", "Цэнхэр"), ("grey", "Саарал"))
AGG_LABELS = {"sum": "Нийлбэр", "avg": "Дундаж", "min": "Хамгийн бага", "max": "Хамгийн их", "count": "Тоо"}
# the aggregates a column of each kind offers: a number all five, a date the three that mean something for dates
AGGS_BY_KIND = {
    "number": ("sum", "avg", "min", "max", "count"),
    "date": ("min", "max", "count"),
    "text": ("count",),
}


@login_required
def format_modal(request: HttpRequest, key: str) -> HttpResponse:
    """The «Хэлбэр» pop-up: the footer totals, the pinned columns and the colour rules the user may use, the current
    ones, and the other filters kept as hidden inputs. Statistic reports (no count line) have no format pop-up."""
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    report = registry.get(key)
    if report is None or not report.shows_count:
        raise Http404
    if not registry.can_open(user, report):
        raise PermissionDenied
    f = parse_filters(request.GET)
    allowed = allowed_columns(report, user)
    # the current totals and colours as the table applies them: only the columns this user may see
    current = restricted_filters(report, user, usable_filters(report, user, f))
    context = {
        "report": report,
        "columns_json": [{"key": c.key, "label": c.label, "kind": _rule_kind(c)} for c in allowed],
        "shown_json": shown_keys(report, user, current),
        "ops_json": {
            kind: [{"code": code, "label": rules_mod.OP_LABELS[code]} for code in codes]
            for kind, codes in rules_mod.OPS.items()
        },
        "aggs_json": AGGS_BY_KIND,
        "agg_labels_json": AGG_LABELS,
        "colours_json": [
            {"key": name, "label": label, "classes": marks_mod.COLOURS[name]} for name, label in FORMAT_COLOURS
        ],
        "totals_json": [list(pair) for pair in totals_mod.parse_totals(current.totals)],
        "marks_json": [
            {"c": m.column, "o": m.rule_op, "v": m.value, "k": m.colour} for m in marks_mod.parse_marks(current.marks)
        ],
        "pin": current.pin,
        # every current filter except the totals, colours and pin, as the page's own filter form keeps them;
        # the `add` chips survive too
        "keep": parse_qsl(to_query(replace(_cleaned_for(user, report, f), totals="", marks="", pin=0)))
        + [("add", name) for name in _added_names(request.GET, offered_column_filters(report, user))],
    }
    return render(request, "reports/_format_modal.html", context)


LAYOUT_LABELS = {  # the switcher's labels (UI_RULES §4b)
    "table": "Хүснэгт",
    "board": "Самбар",
    "calendar": "Хуанли",
    "timeline": "Цагийн шугам",
    "cards": "Карт",
    "chart": "Диаграм",
    "pivot": "Хөрвүүлэлт",
}
CHART_LABELS = {"bar": "Баганан", "line": "Шугаман", "donut": "Дугуй"}  # the chart kinds of the layout bar
CARD_EXTRAS = 4  # the shown columns after the title and subtitle, drawn as label: value lines on a card


@dataclass(frozen=True)
class LayoutOption:
    """One segment of the switcher: its key, label, address and whether it is the layout on screen."""

    name: str
    label: str
    url: str
    current: bool


def _number_or_none(value: object) -> float | None:
    """A chart value as a float; None when there is nothing to aggregate or the value is not a number."""
    return float(value) if isinstance(value, int | float | Decimal) else None


def _chart_payload(chart: layouts_mod.Chart) -> dict[str, Any]:
    """The chart's numbers for report_chart.js (in #report-chart-data): labels, values as floats (None stays null),
    the kind and whether the values are money. The table under the chart is drawn from the same points."""
    return {
        "kind": chart.kind,
        "labels": [point.label for point in chart.points],
        "values": [_number_or_none(point.value) for point in chart.points],
        "money": any(point.money for point in chart.points),
        "value_label": chart.value_label,
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
    names = offered_layouts(report, user)

    def url(name: str) -> str:
        # another layout starts from its own defaults; the filters, sort, rules and format stay
        cleared = replace(f, layout="" if name == "table" else name, lby="", lby2="", lval="", lchart="", lmonth="")
        return _address(request.path, cleared, adds, plain=plain)

    urls = {name: url(name) for name in names}
    keep = parse_qsl(to_query(replace(f, layout="", lby="", lby2="", lval="", lchart="")))
    context: dict[str, Any] = {
        "layout": spec.layout,
        "layout_names": names,
        "layout_urls": urls,
        "layout_options": [LayoutOption(n, LAYOUT_LABELS[n], urls[n], n == spec.layout) for n in names],
        "layout_label": LAYOUT_LABELS,
        "layout_template": f"reports/layouts/{spec.layout}.html",
        "layout_choices": layouts_mod.layout_choices(report, user, spec.layout),
        "layout_value": layouts_mod.value_text(spec.value),
        "layout_keep": keep + [("add", name) for name in adds],  # hidden inputs of the layout bar's form
        "chart_labels": CHART_LABELS,
        "spec": spec,
    }
    cards: batching.Batch[layouts_mod.Item] | None = None
    if spec.layout == "board":
        context["board"] = layouts_mod.build_board(table, spec, marks, today)
    elif spec.layout == "calendar":
        calendar = layouts_mod.build_calendar(table, spec, marks, today)
        context["calendar"] = calendar
        context["calendar_prev_url"] = _address(request.path, replace(f, lmonth=calendar.prev), adds, plain=plain)
        context["calendar_next_url"] = _address(request.path, replace(f, lmonth=calendar.next), adds, plain=plain)
    elif spec.layout == "timeline":
        context["timeline"] = layouts_mod.build_timeline(table, spec, marks, today)
        context["timeline_years"] = layouts_mod.TIMELINE_YEARS
    elif spec.layout == "chart":
        chart = layouts_mod.build_chart(table, spec)
        context["chart"] = chart
        context["chart_json"] = _chart_payload(chart)
        context["chart_kind_label"] = CHART_LABELS[chart.kind]
    elif spec.layout == "pivot":
        pivot = layouts_mod.build_pivot(table, spec)
        context["pivot"] = pivot
        # one line per row: its label, its cells and its total (a template cannot index cells by row)
        context["pivot_lines"] = list(zip(pivot.row_labels, pivot.cells, pivot.row_totals, strict=True))
    elif spec.layout == "cards":
        items = layouts_mod.make_items(table, table.rows, marks, today, extras=CARD_EXTRAS)
        cards = batching.window(request, items)
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
    if request.method == "GET" and not request.GET and not request.headers.get("HX-Request") and report.saved_views:
        # the bare address opens the report's default saved view; the target has a query, so it never loops
        default = _visible_views(user, report.key).filter(is_default=True).first()
        cleaned = _viewer_query(user, report, default.query) if default is not None else ""
        if cleaned:
            return redirect(_view_url(reverse("reports:report", args=[report.key]), cleaned))
    table = build_table(report, user, parse_filters(request.GET))
    f = table.filters
    # rows load in batches only when the table is not grouped: a grouped table shows every row under its heading
    # (the other layouts draw all their rows; only cards page, through their own batch below)
    batch: batching.Batch[Any] | None = None
    if table.spec.layout == "table" and not f.group:
        batch = batching.window(request, table.groups[0][1])
        table.groups = [("", batch.shown)]
    column_names = offered_column_filters(report, user)
    adds = _added_names(request.GET, column_names)  # the picker's chips without a value yet; never stored
    plain = bool(report.saved_views)  # an empty address then says view=plain, not the bare default-view address
    layout_context, cards = _layout_context(request, user, report, table, adds, plain)
    column_choices, column_chips = _column_filter_panels(request.path, f, column_names, adds, plain)
    # the Багана button's address: the report's query plus the chips named by `add`
    columns_query = "&".join(part for part in (to_query(f), urlencode([("add", n) for n in adds])) if part)
    heads = []
    for i, (c, cls) in enumerate(zip(table.columns, column_classes(table.columns), strict=True)):
        heads.append(
            HeaderCell(
                label=c.label,
                href=_address(request.path, replace(f, sort=_next_sort(f.sort, c.key)), adds, plain=plain),
                append_href=_address(
                    request.path, replace(f, sort=_next_sort(f.sort, c.key, append=True)), adds, plain=plain
                ),
                arrow=_sort_mark(f.sort, c.key),
                cls=cls,
                sticky_left=pin_style(i, table.pin),
            )
        )
    names = offered_filters(report, user)  # the filter bar draws these, in the report's order
    period_start, period_end = period_of(f)
    context = {
        "report": report,
        "filters": f,
        "rules_text": table.rules_text,
        "clear_rules_url": _address(request.path, replace(f, rules=""), adds, plain=plain),
        "clear_url": _address(request.path, Filters(), plain=plain),  # the filter bar's «Цэвэрлэх»
        "query": to_query(f),
        "columns_query": columns_query,
        "print_url": _address(reverse("reports:print", args=[report.key]), f),
        "excel_url": _address(reverse("reports:excel", args=[report.key]), f) if user.has_perm(EXPORT_PERM) else "",
        "table": table,
        "heads": heads,
        "shown_rows": batch.shown if batch is not None else [],
        "next_query": batch.next_query if batch is not None else "",
        "batch_url": request.path,
        "note": report.note(f) if report.note is not None else "",
        "filter_names": names,
        "column_filter_choices": column_choices,
        "active_column_filters": column_chips,
        "states": STATES,
        "emptypes": EMPTYPES,
        "no_working_state": NO_WORKING_STATE,
        "genders": GENDERS,
        "branches": Branch.objects.order_by("name"),
        "departments": Department.objects.order_by("name"),
        "positions": Position.objects.order_by("name"),
        "period_from": period_start,
        "period_to": period_end,
        "change_kinds": MOVEMENT_KINDS,
        "order_types": ORDER_TYPES,
        "leave_states": LEAVE_STATES,
        "leave_types": LeaveTypeRow.objects.order_by("name") if "leave_type" in names else [],
        "absence_types": AbsenceType.objects.order_by("name") if "absence_type" in names else [],
        "attributes": ATTRIBUTES if "attribute" in names else {},
        "contact_types": ContactType.objects.order_by("name") if "contact_type" in names else [],
        "year": (f.year or timezone.localdate().year) if "year" in names else None,
        "training_types": TRAINING_TYPES if "tr_type" in names else {},
        "quarter": (f.quarter or this_quarter()) if "quarter" in names else None,
        "present_types": PresentType.objects.order_by("name") if "present_type" in names else [],
        # the lists behind the dropdowns are read only when their filter is in the bar
        "reasons": FiredReason.objects.order_by("name") if "reason" in names else [],
        "discipline_types": DisciplineType.objects.order_by("name") if "discipline" in names else [],
        "people": (
            access.visible_employees(user)
            .exclude(emptype__in=listing.NEVER_WORKED)
            .order_by("family_name", "given_name")
            if "employee" in names
            else []
        ),
        # the «Бүлэглэх» select replaces the column picker's grouping, so only reports without the picker offer it
        "group_choices": (
            [] if report.picks_columns else [c for c in allowed_columns(report, user) if c.key in report.group_options]
        ),
        "group_text": _group_text(f.group, [c for c in allowed_columns(report, user) if c.key in report.group_options]),
    }
    context.update(layout_context)
    if batch is not None and batch.offset:
        # the «Цааш харуулах» pill asked for the next batch: only its rows and the pill after them go back
        return render(request, "reports/_batch_rows.html", context)
    if cards is not None and cards.offset:
        return render(request, "reports/layouts/_cards_batch.html", context)
    if report.saved_views:
        # the match uses the address as this viewer may use it, cleaned the same way a stored view is (defaults such as
        # the default columns are not part of it, so an empty view matches the plain address)
        context.update(_saved_context(user, report, to_query(_cleaned_for(user, report, parse_filters(request.GET)))))
    response = render(request, "reports/report.html", context)
    if request.headers.get("HX-Request"):
        # the filter form pushes the raw address it sent; the address bar gets the cleaned one, so no old year is kept
        response["HX-Push-Url"] = _address(request.path, f, adds, plain=plain)
    return response


@dataclass(frozen=True)
class SavedOption:
    name: str
    url: str  # the report's address with this view's query
    selected: bool  # the address shows this view's setup now


def _view_url(report_url: str, query: str) -> str:
    return f"{report_url}?{query}" if query else f"{report_url}?{PLAIN_VIEW}"


def _may_change(user: User, view: SavedView) -> bool:
    """A saved view is renamed and deleted by its author, or by a user with reports.manage_saved_views."""
    return view.author_id == user.pk or user.has_perm("reports.manage_saved_views")


def _sees_private(user: User, view: SavedView) -> bool:
    """A private view is seen by its author; one whose author was deleted (no author) only by a manager."""
    return view.author_id == user.pk or (view.author_id is None and user.has_perm(MANAGE_PERM))


def _visible_views(user: User, report_key: str) -> QuerySet[SavedView]:
    """The report's saved views this user sees: every shared one, the user's own private ones, and the private ones
    with no author left when the user may manage saved views."""
    visible = Q(visibility=SHARED) | Q(author=user)
    if user.has_perm(MANAGE_PERM):
        visible |= Q(author__isnull=True, visibility=PRIVATE)
    return SavedView.objects.filter(report=report_key).filter(visible)


def _default_allowed(user: User, report_key: str, pk: int | None) -> bool:
    """May this user make the view `pk` the report's default? Yes when no other view is the default, or when they may
    change the current default (its author, or a manager). A plain author cannot displace someone else's default."""
    current = SavedView.objects.filter(report=report_key, is_default=True)
    if pk is not None:
        current = current.exclude(pk=pk)
    current_default = current.first()
    return current_default is None or _may_change(user, current_default)


def _clear_defaults(report_key: str, keep: int | None = None) -> None:
    """Unsets the report's default view, except `keep`: a report has at most one default. Runs inside the caller's
    transaction, so a refused save puts the old default back."""
    others = SavedView.objects.filter(report=report_key, is_default=True)
    if keep is not None:
        others = others.exclude(pk=keep)
    others.update(is_default=False)


def _visibility_and_default(form: SavedViewForm) -> tuple[str, bool]:
    """The view's visibility (blank is shared) and whether it opens first. Only a shared view can be the default."""
    visibility = form.cleaned_data["visibility"] or SHARED
    return visibility, bool(form.cleaned_data["is_default"]) and visibility == SHARED


def _option_name(view: SavedView) -> str:
    """The select's text: a star on the default view, and a suffix on a private one."""
    name = f"★ {view.name}" if view.is_default else view.name
    return f"{name} (хувийн)" if view.visibility == PRIVATE else name


def _cleaned_for(user: User, report: Report, f: Filters) -> Filters:
    """An address as this user may use it: the filters they may not use (column filters on hidden columns included)
    are reset, the columns, sort and group keys they may not see are dropped, and rules, totals and marks keep only
    their columns. Used for what a user saves and for each saved view a user sees."""
    usable = usable_filters(report, user, f)
    known = _known_only(report, usable)
    allowed = {c.key for c in allowed_columns(report, user)}
    visible = replace(
        known,
        columns=tuple(k for k in known.columns if k in allowed),
        group=_known_keys(known.group, allowed, sort=False),
        sort=_known_keys(known.sort, allowed, sort=True),
    )
    return restricted_filters(report, user, visible)


def _viewer_query(user: User, report: Report, stored: str) -> str:
    """A saved view's query as this viewer may see it. A view whose rules all vanish for this viewer is the plain
    address."""
    return to_query(_cleaned_for(user, report, parse_filters(QueryDict(stored))))


def _saved_context(user: User, report: Report, query: str) -> dict[str, Any]:
    """The title-row controls: the report's views, the one the address matches, and whether the user may change it.
    Each view's address and the match use the query as this viewer may see it."""
    report_url = reverse("reports:report", args=[report.key])
    shown = [(v, _viewer_query(user, report, v.query)) for v in _visible_views(user, report.key)]
    current = next((v for v, own in shown if own == query), None)
    options = [
        SavedOption(name=_option_name(v), url=_view_url(report_url, own), selected=v is current) for v, own in shown
    ]
    # the starter templates («Загвар»): read-only, offered only when every column their rules use is one this viewer
    # may see; a saved view that matches the address wins the selection over a template
    template_options = []
    for t in report.templates:
        if not _template_allowed(user, report, t):
            continue
        own = _viewer_query(user, report, t.query)
        if own:
            template_options.append(
                SavedOption(name=t.name, url=_view_url(report_url, own), selected=current is None and own == query)
            )
    return {
        "report_url": report_url,
        "plain_url": _view_url(report_url, ""),  # the «—» option: the report with no saved setup
        "saved_options": options,
        "current_view": current,
        "can_edit_view": current is not None and _may_change(user, current),
        "template_options": template_options,
        "template_current": any(o.selected for o in template_options),
    }


def _template_allowed(user: User, report: Report, template: Template) -> bool:
    """A template is offered when its rules parse and use only columns this user may see."""
    tree = rules_mod.parse_rules(parse_filters(QueryDict(template.query)).rules)
    if tree is None:
        return False
    return set(rules_mod.rule_columns(tree)) <= {c.key for c in allowed_columns(report, user)}


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
    table = build_table(report, user, parse_filters(request.GET))
    labels = {c.key: c.label for c in allowed_columns(report, user)}
    lines = describe(table.filters, report.filters, labels=labels)
    context = {
        "report": report,
        "table": table,
        "heads": [(c.label, cls) for c, cls in zip(table.columns, column_classes(table.columns), strict=True)],
        "lines": lines,
        "note": report.note(table.filters) if report.note is not None else "",
        "landscape": len(table.columns) > MAX_PORTRAIT_COLUMNS,
        "company": CompanySettings.get().name,
        "today": timezone.localdate(),
        "printed_by": user.get_full_name() or user.get_username(),
    }
    response = render(request, "reports/print.html", context)
    record_export(
        request,
        "print_page",
        report.title,
        filters="; ".join(describe(table.filters, report.filters, for_log=True, labels=labels)),
        rows=table.count,
    )
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
    table = build_table(report, user, parse_filters(request.GET))
    labels = {c.key: c.label for c in allowed_columns(report, user)}
    note = report.note(table.filters) if report.note is not None else ""
    lines = describe(table.filters, report.filters, labels=labels)
    lines += [note] if note else []  # the grey note goes in the sheet too
    today = timezone.localdate().isoformat()
    response = HttpResponse(excel.workbook_bytes(report.title, lines, table, sheet=report.key), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{report.key}-{today}.xlsx"'
    log_label = describe(table.filters, report.filters, for_log=True, labels=labels)
    record_export(request, "export_report", report.title, filters="; ".join(log_label), rows=table.count)
    return response


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)  # login_required guarantees a real user
    return request.user


def _saveable_report(user: User, key: str) -> Report:
    """The report of a saved view: 404 when it keeps no saved views, 403 when the user may not open it."""
    report = registry.get(key)
    if report is None or not report.saved_views:
        raise Http404
    if not registry.can_open(user, report):
        raise PermissionDenied
    return report


def _view_for(request: HttpRequest, pk: int) -> SavedView:
    """A saved view the user may rename or delete: 404 if missing, 403 if the user may not change it."""
    user = _user(request)
    view = get_object_or_404(SavedView, pk=pk)
    if view.visibility == PRIVATE and not _sees_private(user, view):
        raise Http404  # a private view is not visible to anyone else, a manager included
    _saveable_report(user, view.report)
    if not _may_change(user, view):
        raise PermissionDenied
    return view


def _view_modal(
    request: HttpRequest, title: str, form: SavedViewForm, action: str, view: SavedView | None
) -> HttpResponse:
    context = {"title": title, "form": form, "action": action, "view": view}
    return render(request, "reports/_view_modal.html", context)


def _is_name_clash(error: IntegrityError) -> bool:
    """True when the database refused the (report, name) pair; any other integrity error is not ours to hide.
    Accepted (decision, low impact): the name is unique across private views too, so a clash reveals that another
    user's private view has that name; removing it needs a schema change."""
    diag = getattr(error.__cause__, "diag", None)  # psycopg puts the violated constraint's name here
    if getattr(diag, "constraint_name", None) == NAME_CONSTRAINT:
        return True
    # Firebird has no such attribute: its message names the (upper-case) index, e.g. ... "REPORTS_SAVEDVIEW_UNIQUE_NAME".
    return diag is None and NAME_CONSTRAINT in str(error).lower()


def _known_keys(text: str, known: set[str], *, sort: bool) -> str:
    """A comma-separated list of keys with only the known ones kept, in order. A sort key may start with «-»; a group
    key may not, so a «-» part is dropped from a group list (parse_filters would drop the whole list anyway)."""
    parts = text.split(",") if sort else [p for p in text.split(",") if not p.startswith("-")]
    return ",".join(part for part in parts if part.lstrip("-") in known)


def _known_only(report: Report, f: Filters) -> Filters:
    """The address with only the column, group and sort keys this report has, so a saved view stores nothing unknown.
    Rules, totals and marks keep only the report's own columns too."""
    known = {c.key for c in report.columns}
    kept_rules = rules_mod.dump_rules(rules_mod.restrict(rules_mod.parse_rules(f.rules), known))
    kept_totals = totals_mod.dump_totals([pair for pair in totals_mod.parse_totals(f.totals) if pair[0] in known])
    kept_marks = marks_mod.dump_marks([mark for mark in marks_mod.parse_marks(f.marks) if mark.column in known])
    return replace(
        f,
        columns=tuple(k for k in f.columns if k in known),
        group=_known_keys(f.group, known, sort=False),
        sort=_known_keys(f.sort, known, sort=True),
        rules=kept_rules,
        totals=kept_totals,
        marks=kept_marks,
    )


@login_required
def view_new(request: HttpRequest, key: str) -> HttpResponse:
    """The «Хадгалах» pop-up. Saves the cleaned address under a name; every user who can open the report sees it."""
    user = _user(request)
    report = _saveable_report(user, key)
    action = reverse("reports:view_new", args=[key])
    if request.method != "POST":
        initial = {"query": to_query(parse_filters(request.GET))}
        return _view_modal(request, "Харагдац хадгалах", SavedViewForm(initial=initial), action, None)
    form = SavedViewForm(request.POST)
    if not form.is_valid():
        return _view_modal(request, "Харагдац хадгалах", form, action, None)
    # never the raw text: what the author may not use or see (a hidden filter, rule, sort or group) is not stored
    query = to_query(_cleaned_for(user, report, parse_filters(QueryDict(form.cleaned_data["query"]))))
    if QUERY_LIMIT is not None and len(query) > QUERY_LIMIT:
        form.add_error(None, TOO_LONG)
        return _view_modal(request, "Харагдац хадгалах", form, action, None)
    visibility, wants_default = _visibility_and_default(form)
    make_default = wants_default and _default_allowed(user, key, None)  # not displacing someone else's default
    try:
        with transaction.atomic():
            if make_default:
                _clear_defaults(key)
            SavedView.objects.create(
                report=key,
                name=form.cleaned_data["name"],
                query=query,
                author=user,
                visibility=visibility,
                is_default=make_default,
            )
    except IntegrityError as error:
        if not _is_name_clash(error):
            raise
        form.add_error("name", DUPLICATE_NAME)
        return _view_modal(request, "Харагдац хадгалах", form, action, None)
    response = HttpResponse(status=204)
    response["HX-Redirect"] = _view_url(reverse("reports:report", args=[key]), query)
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
    form = SavedViewForm(data)
    if not form.is_valid():
        return _view_modal(request, title, form, action, view)
    view.name = form.cleaned_data["name"]
    view.visibility, wants_default = _visibility_and_default(form)
    view.is_default = wants_default and _default_allowed(user, view.report, view.pk)
    try:
        with transaction.atomic():
            if view.is_default:
                _clear_defaults(view.report, keep=view.pk)
            view.save(update_fields=["name", "visibility", "is_default", "updated_at"])
    except IntegrityError as error:
        if not _is_name_clash(error):
            raise
        form.add_error("name", DUPLICATE_NAME)
        return _view_modal(request, title, form, action, view)
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"  # the address keeps the same setup, so the page reloads on the same view
    return response


@login_required
@require_POST
def view_delete(request: HttpRequest, pk: int) -> HttpResponse:
    view = _view_for(request, pk)
    key = view.report
    view.delete()
    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse("reports:report", args=[key])
    return response
