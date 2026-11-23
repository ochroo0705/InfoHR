"""The employee log page («Ажилтны бүртгэл», /logs/).

Filters live in the address and rows load in batches (UI_RULES §4, §4b, §5).
"""

import dataclasses
from typing import Any

from accounts.audit import ACTIONS, Category, record_export
from accounts.models import User
from config import batching
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET
from django.views.decorators.vary import vary_on_headers
from employees.models import ActivityKind

from logs import export
from logs.employee_query import page, parse_filter
from logs.page_rules import (
    AREA_LABELS,
    EXPORT_PERM,
    employee_workbook,
    system_workbook,
)
from logs.page_rules import (
    employee_address as _address,
)
from logs.page_rules import (
    system_address as _system_address,
)
from logs.page_rules import (
    visible_chip as _visible_chip,
)
from logs.system_query import parse_system_filter, system_page

ROW_COLSPAN = 5


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


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


@login_required
@require_GET
def employee_xlsx(request: HttpRequest) -> HttpResponse:
    """The employee log as an Excel file: the rows the screen shows for this address, every batch of them."""
    user = _user(request)
    if not user.has_perm("macs.view_employees") or not user.has_perm(EXPORT_PERM):
        raise PermissionDenied
    f = parse_filter(request.GET)
    _visible_chip(user, f)
    response, tally = employee_workbook(user, f)
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
    response, tally = system_workbook(f)
    record_export(
        request,
        "export_log",
        "Системийн бүртгэл",
        filters=export.system_filter_label(f),
        rows=tally.rows,
    )
    return response
