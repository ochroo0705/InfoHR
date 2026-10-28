"""The «Тайлан» catalogue page (every old-program report, grouped, with a search box) and the shared report page."""

from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import parse_qsl

from accounts.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404, HttpRequest, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
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
from reports.catalogue import CATALOGUE, GROUPS, Entry
from reports.filters import (
    ATTRIBUTES,
    GENDERS,
    LEAVE_STATES,
    MOVEMENT_KINDS,
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
from reports.models import SavedView
from reports.table import allowed_columns, build_table, column_classes, offered_filters, shown_keys
from reports.types import Column, Report

MAX_PORTRAIT_COLUMNS = 7  # more columns than this print on A4 landscape
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_PERM = "accounts.export_lists"  # the Excel file and its button
DUPLICATE_NAME = "Ийм нэртэй харагдац байна."
TOO_LONG = "Харагдац хэт урт байна."
NAME_CONSTRAINT = "reports_savedview_unique_name"  # UniqueConstraint(report, name) on SavedView
QUERY_LIMIT = SavedView._meta.get_field("query").max_length  # the stored query is cut at this many characters


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
    sections: list[Section] = []
    for code, title in GROUPS:
        rows: list[Row] = []
        for entry in CATALOGUE:
            row = _row(request.user, entry) if entry.group == code else None
            if row is not None:
                rows.append(row)
        if rows:
            sections.append(Section(title=title, rows=rows))
    return render(request, "reports/catalogue.html", {"sections": sections})


@dataclass(frozen=True)
class HeaderCell:
    label: str
    href: str  # the address that sorts the table by this column (a second click reverses it)
    arrow: str  # "↑", "↓" on the sorted column, else ""
    cls: str  # alignment classes


def _address(path: str, f: Filters) -> str:
    query = to_query(f)
    return f"{path}?{query}" if query else path


def _next_sort(current: str, key: str) -> str:
    """Sort ascending on a new column, descending on the second click, ascending again on the third."""
    if current == key:
        return f"-{key}"
    return key


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
        # the filters the form keeps as hidden inputs: every current filter except the columns and the grouping
        "keep": parse_qsl(to_query(replace(f, columns=(), group=""))),
    }
    return render(request, "reports/_columns_modal.html", context)


@login_required
def report_page(request: HttpRequest, key: str) -> HttpResponse:
    user = request.user
    assert isinstance(user, User)  # login_required guarantees a real user
    report = registry.get(key)
    if report is None:
        raise Http404
    if not registry.can_open(user, report):
        raise PermissionDenied
    table = build_table(report, user, parse_filters(request.GET))
    f = table.filters
    heads = [
        HeaderCell(
            label=c.label,
            href=_address(request.path, replace(f, sort=_next_sort(f.sort, c.key))),
            arrow="↓" if f.sort == f"-{c.key}" else ("↑" if f.sort == c.key else ""),
            cls=cls,
        )
        for c, cls in zip(table.columns, column_classes(table.columns), strict=True)
    ]
    names = offered_filters(report, user)  # the filter bar draws these, in the report's order
    period_start, period_end = period_of(f)
    context = {
        "report": report,
        "filters": f,
        "query": to_query(f),
        "print_url": _address(reverse("reports:print", args=[report.key]), f),
        "excel_url": _address(reverse("reports:excel", args=[report.key]), f) if user.has_perm(EXPORT_PERM) else "",
        "table": table,
        "heads": heads,
        "note": report.note(f) if report.note is not None else "",
        "filter_names": names,
        "states": STATES,
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
    }
    if report.saved_views:
        context.update(_saved_context(user, report, to_query(f)))
    response = render(request, "reports/report.html", context)
    if request.headers.get("HX-Request"):
        # the filter form pushes the raw address it sent; the address bar gets the cleaned one, so no old year is kept
        response["HX-Push-Url"] = _address(request.path, f)
    return response


@dataclass(frozen=True)
class SavedOption:
    name: str
    url: str  # the report's address with this view's query
    selected: bool  # the address shows this view's setup now


def _view_url(report_url: str, query: str) -> str:
    return f"{report_url}?{query}" if query else report_url


def _may_change(user: User, view: SavedView) -> bool:
    """A saved view is renamed and deleted by its author, or by a user with reports.manage_saved_views."""
    return view.author_id == user.pk or user.has_perm("reports.manage_saved_views")


def _saved_context(user: User, report: Report, query: str) -> dict[str, Any]:
    """The title-row controls: the report's views, the one the address matches, and whether the user may change it."""
    report_url = reverse("reports:report", args=[report.key])
    views = list(SavedView.objects.filter(report=report.key))
    current = next((v for v in views if v.query == query), None)
    options = [SavedOption(name=v.name, url=_view_url(report_url, v.query), selected=v is current) for v in views]
    return {
        "report_url": report_url,
        "saved_options": options,
        "current_view": current,
        "can_edit_view": current is not None and _may_change(user, current),
    }


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
    context = {
        "report": report,
        "table": table,
        "heads": [(c.label, cls) for c, cls in zip(table.columns, column_classes(table.columns), strict=True)],
        "lines": describe(table.filters, report.filters),
        "note": report.note(table.filters) if report.note is not None else "",
        "landscape": len(table.columns) > MAX_PORTRAIT_COLUMNS,
        "company": CompanySettings.get().name,
        "today": timezone.localdate(),
        "printed_by": user.get_full_name() or user.get_username(),
    }
    return render(request, "reports/print.html", context)


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
    note = report.note(table.filters) if report.note is not None else ""
    lines = describe(table.filters, report.filters) + ([note] if note else [])  # the grey note goes in the sheet too
    today = timezone.localdate().isoformat()
    response = HttpResponse(excel.workbook_bytes(report.title, lines, table, sheet=report.key), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{report.key}-{today}.xlsx"'
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
    """True when the database refused the (report, name) pair; any other integrity error is not ours to hide."""
    diag = getattr(error.__cause__, "diag", None)  # psycopg puts the violated constraint's name here
    return getattr(diag, "constraint_name", None) == NAME_CONSTRAINT


def _known_only(report: Report, f: Filters) -> Filters:
    """The address with only the column, group and sort keys this report has, so a saved view stores nothing unknown."""
    known = {c.key for c in report.columns}
    sort = f.sort[1:] if f.sort.startswith("-") else f.sort
    return replace(
        f,
        columns=tuple(k for k in f.columns if k in known),
        group=f.group if f.group in known else "",
        sort=f.sort if sort in known else "",
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
    query = to_query(_known_only(report, parse_filters(QueryDict(form.cleaned_data["query"]))))  # never the raw text
    if QUERY_LIMIT is not None and len(query) > QUERY_LIMIT:
        form.add_error(None, TOO_LONG)
        return _view_modal(request, "Харагдац хадгалах", form, action, None)
    try:
        with transaction.atomic():
            SavedView.objects.create(report=key, name=form.cleaned_data["name"], query=query, author=user)
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
    """The «Засах» pop-up: rename the view, or delete it after the «устгах уу?» question."""
    view = _view_for(request, pk)
    action = reverse("reports:view_edit", args=[pk])
    title = "Харагдац засах"
    if request.method != "POST":
        return _view_modal(request, title, SavedViewForm(initial={"name": view.name}), action, view)
    form = SavedViewForm(request.POST)
    if not form.is_valid():
        return _view_modal(request, title, form, action, view)
    view.name = form.cleaned_data["name"]
    try:
        with transaction.atomic():
            view.save(update_fields=["name", "updated_at"])
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
