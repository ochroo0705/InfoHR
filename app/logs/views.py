"""The employee log page («Ажилтны бүртгэл», /logs/).

Filters live in the address and rows load in batches (UI_RULES §4, §4b, §5).
"""

import dataclasses
from typing import Any
from urllib.parse import urlencode

from accounts.audit import ACTIONS, Category, record_export
from accounts.models import User
from config import batching
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.vary import vary_on_headers
from employees import access
from employees.models import ActivityKind, Employee

from logs import export
from logs.employee_query import EmployeeLogFilter, filtered, page, parse_filter
from logs.system_query import SystemLogFilter, parse_system_filter, system_page
from logs.system_query import filtered as filtered_system

EXPORT_PERM = "accounts.export_lists"  # the Excel file and its button
AREA_LABELS = (
    ("salary", "Цалин"),
    ("personal", "Хувийн мэдээлэл"),
    ("orders", "Тушаал"),
    ("notes", "Тэмдэглэл"),
)
ROW_COLSPAN = 5


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _address(f: EmployeeLogFilter) -> str:
    """The cleaned filters as a query string: what the page shows, never the raw text the user typed into the URL."""
    pairs: list[tuple[str, str]] = []
    if f.q:
        pairs.append(("q", f.q))
    if f.emp:
        pairs.append(("emp", f.emp))
    if f.employee is not None:
        pairs.append(("employee", str(f.employee)))
    if f.by:
        pairs.append(("by", f.by))
    pairs.extend(("kind", kind) for kind in f.kinds)
    if f.area:
        pairs.append(("area", f.area))
    if f.field:
        pairs.append(("field", f.field))
    if f.date_from is not None:
        pairs.append(("from", f.date_from.isoformat()))
    if f.date_to is not None:
        pairs.append(("to", f.date_to.isoformat()))
    if f.system_only:
        pairs.append(("system", "1"))
    if f.oldest_first:
        pairs.append(("oldest", "1"))
    return urlencode(pairs)


@login_required
@require_GET
@vary_on_headers("HX-Request")
def employee_log(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    if not user.has_perm("macs.view_employees"):
        raise PermissionDenied
    f = parse_filter(request.GET)
    # A person the user may not see, or one that does not exist, is dropped: the page shows everyone else's rows.
    chip = _visible_chip(user, f)
    batch = batching.paged(request, lambda offset, size: page(user, f, offset, size))
    htmx = bool(request.headers.get("HX-Request")) and not request.headers.get("HX-History-Restore-Request")
    base_url = reverse("logs:employee")
    query = _address(f)
    context: dict[str, Any] = {
        "rows": batch.shown,
        "offset": batch.offset,
        "next_query": batch.next_query,
        "employee": chip,
        "employee_name": f"{chip.family_name} {chip.given_name}" if chip is not None else "",
        "chip_remove_url": base_url + ("?" + _address(dataclasses.replace(f, employee=None))),
        "q": f.q,
        "emp": f.emp,
        "by": f.by,
        "kinds": f.kinds,
        "kind_choices": ActivityKind.choices,
        "area": f.area,
        "areas": AREA_LABELS,
        "field": f.field,
        "date_from": f.date_from.isoformat() if f.date_from is not None else "",
        "date_to": f.date_to.isoformat() if f.date_to is not None else "",
        "system": f.system_only,
        "oldest": f.oldest_first,
        "clear_url": base_url,
        "show_employee_tab": user.has_perm("macs.view_employees"),
        "show_system_tab": user.has_perm("accounts.view_audit"),
        "row_colspan": ROW_COLSPAN,
        "query": query,
        "excel_base": reverse("logs:employee_xlsx") if user.has_perm(EXPORT_PERM) else "",
    }
    if not htmx:
        template = "logs/employee.html"
    elif batch.offset:
        template = "logs/_employee_items.html"  # a later batch adds rows to the table
    else:
        template = "logs/_employee_rows.html"  # a filter change replaces the table
    response = render(request, template, context)
    if htmx and not batch.offset:
        # the address bar gets the cleaned filters, so Back and a shared link reopen the same view
        response["HX-Push-Url"] = base_url + ("?" + query if query else "")
    return response


SYSTEM_ROW_COLSPAN = 7


def _system_address(f: SystemLogFilter) -> str:
    """The cleaned system-log filters as a query string (never the raw text typed into the URL)."""
    pairs: list[tuple[str, str]] = []
    if f.q:
        pairs.append(("q", f.q))
    pairs.extend(("category", category) for category in f.categories)
    if f.action:
        pairs.append(("action", f.action))
    if f.by:
        pairs.append(("by", f.by))
    if f.target:
        pairs.append(("target", f.target))
    if f.ip:
        pairs.append(("ip", f.ip))
    if f.date_from is not None:
        pairs.append(("from", f.date_from.isoformat()))
    if f.date_to is not None:
        pairs.append(("to", f.date_to.isoformat()))
    if f.oldest_first:
        pairs.append(("oldest", "1"))
    return urlencode(pairs)


@login_required
@require_GET
@vary_on_headers("HX-Request")
def system_log(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    if not user.has_perm("accounts.view_audit"):
        raise PermissionDenied
    f = parse_system_filter(request.GET)
    batch = batching.paged(request, lambda offset, size: system_page(f, offset, size))
    htmx = bool(request.headers.get("HX-Request")) and not request.headers.get("HX-History-Restore-Request")
    base_url = reverse("logs:system")
    query = _system_address(f)
    context: dict[str, Any] = {
        "rows": batch.shown,
        "offset": batch.offset,
        "next_query": batch.next_query,
        "q": f.q,
        "categories": f.categories,
        "category_choices": Category.choices,
        "action": f.action,
        "action_choices": list(ACTIONS.items()),
        "by": f.by,
        "target": f.target,
        "ip": f.ip,
        "date_from": f.date_from.isoformat() if f.date_from is not None else "",
        "date_to": f.date_to.isoformat() if f.date_to is not None else "",
        "oldest": f.oldest_first,
        "clear_url": base_url,
        "show_employee_tab": user.has_perm("macs.view_employees"),  # the Auditor has no employee log
        "show_system_tab": True,  # this page needs accounts.view_audit, the same right as the tab
        "row_colspan": SYSTEM_ROW_COLSPAN,
        "query": query,
        "excel_base": reverse("logs:system_xlsx") if user.has_perm(EXPORT_PERM) else "",
    }
    if not htmx:
        template = "logs/system.html"
    elif batch.offset:
        template = "logs/_system_items.html"  # a later batch adds rows to the table
    else:
        template = "logs/_system_rows.html"  # a filter change replaces the table
    response = render(request, template, context)
    if htmx and not batch.offset:
        # the address bar gets the cleaned filters, so Back and a shared link reopen the same view
        response["HX-Push-Url"] = base_url + ("?" + query if query else "")
    return response


def _visible_chip(user: User, f: EmployeeLogFilter) -> Employee | None:
    """The employee named by the filter if the user may see them; otherwise the filter is dropped and None returned."""
    chip = access.visible_employees(user).filter(pk=f.employee).first() if f.employee is not None else None
    f.employee = chip.pk if chip is not None else None
    return chip


@login_required
@require_GET
def employee_xlsx(request: HttpRequest) -> HttpResponse:
    """The employee log as an Excel file: the rows the screen shows for this address, every batch of them."""
    user = _user(request)
    if not user.has_perm("macs.view_employees") or not user.has_perm(EXPORT_PERM):
        raise PermissionDenied
    f = parse_filter(request.GET)
    _visible_chip(user, f)
    tally = export.Tally()
    today = timezone.localdate().isoformat()
    response = export.workbook_response(
        f"employee-log-{today}.xlsx",
        export.EMPLOYEE_HEADERS,
        export.capped_rows(filtered(user, f), export.employee_row, tally),
        export.EMPLOYEE_WIDTHS,
    )
    record_export(
        request,
        "export_log",
        "Ажилтны бүртгэл",
        filters=export.employee_filter_label(f),
        rows=tally.rows,
    )
    return response


@login_required
@require_GET
def system_xlsx(request: HttpRequest) -> HttpResponse:
    """The system log as an Excel file: the rows the screen shows for this address, every batch of them."""
    user = _user(request)
    if not user.has_perm("accounts.view_audit") or not user.has_perm(EXPORT_PERM):
        raise PermissionDenied
    f = parse_system_filter(request.GET)
    tally = export.Tally()
    today = timezone.localdate().isoformat()
    response = export.workbook_response(
        f"system-log-{today}.xlsx",
        export.SYSTEM_HEADERS,
        export.capped_rows(filtered_system(f), export.system_row, tally),
        export.SYSTEM_WIDTHS,
    )
    record_export(
        request,
        "export_log",
        "Системийн бүртгэл",
        filters=export.system_filter_label(f),
        rows=tally.rows,
    )
    return response
