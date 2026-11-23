"""The log pages' API under /api/v1/logs/, as the React pages read them.

- GET /employee and GET /system: one batch of the log, with the cleaned filters, the chip (employee log only), the
  filter options, the tabs and the address.
- GET /employee/export and GET /system/export: the log as an .xlsx file of every row the screen shows.

The rows, filters, paging and chip come from logs.employee_query, logs.system_query and logs.page_rules. This module
reads the request, presents the answer and draws the row texts (date, time, names, labels, kind chip classes, change
lines) that the Django templates _employee_items.html and _system_items.html draw. The employee log needs
macs.view_employees and the system log needs accounts.view_audit (403 "forbidden" for others, 401 for no login).
Every response is marked Cache-Control: no-store, so a log page is not served from the Back cache.
"""

from typing import Any, Literal

from accounts.audit import ACTIONS, Category, record_export
from accounts.models import SystemLogEntry, User
from config import batching
from django.http import HttpRequest, HttpResponse, QueryDict
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, Employee
from logs import export, page_rules
from logs.employee_query import EmployeeLogFilter, page, parse_filter
from logs.system_query import SystemLogFilter, parse_system_filter, system_page
from logs.templatetags.log_extras import action_label, category_label
from ninja import Query, Router, Schema
from ninja.security import django_auth

from api.errors import ApiError
from api.params import batch_offset
from api.popups import FORBIDDEN, request_user

log_router = Router(tags=["logs"])

NO_NAME = "Систем"  # the actor of an entry the system wrote, and of an entry whose user has no name
EMPTY_NEW = "(хоосон)"  # a change whose new value is empty (_employee_items.html)


class LogChangeOut(Schema):
    field: str
    old: str  # "" when there was none
    new: str  # «(хоосон)» when the new value is empty


class LogEmployeeRowOut(Schema):
    id: int
    date: str  # YYYY-MM-DD, the local day
    time: str  # HH:MM, local time
    employee_id: int
    employee_name: str  # «<family> <given>»
    employee_code: str
    by_name: str  # the actor's full name, else the username, else «Систем»
    kind: str  # an ActivityKind value
    kind_label: str
    kind_class: str  # the chip classes of the kind (page_rules.kind_tone)
    is_note: bool  # a note: its message is drawn in a sky box and keeps its line breaks
    is_correction: bool  # a correction: its message is drawn in amber
    message: str  # drawn as text, never as HTML
    changes: list[LogChangeOut]
    order_id: int | None  # set for an entry about one HR order: the row opens that order's pop-up


class LogChipOut(Schema):
    id: int
    name: str  # «<family> <given>»


class LogOptionOut(Schema):
    value: str
    label: str


class LogEmployeeOptionsOut(Schema):
    kinds: list[LogOptionOut]
    areas: list[LogOptionOut]


class LogEmployeeQueryOut(Schema):
    q: str
    emp: str
    employee: int | None  # the visible person only; a hidden or unknown one is dropped
    by: str
    kinds: list[str]
    area: str
    field: str
    date_from: str  # YYYY-MM-DD or ""
    date_to: str  # YYYY-MM-DD or ""
    system: bool
    oldest: bool


class LogTabsOut(Schema):
    employee: bool
    system: bool
    export: bool


class LogEmployeeOut(Schema):
    rows: list[LogEmployeeRowOut]
    next_offset: int | None  # the offset of the next batch; None when this is the last one
    query: LogEmployeeQueryOut
    chip: LogChipOut | None
    options: LogEmployeeOptionsOut
    tabs: LogTabsOut
    address: str  # the cleaned filters as a query string (the Excel link and the address bar)


class LogSystemRowOut(Schema):
    id: int
    date: str  # YYYY-MM-DD, the local day
    time: str  # HH:MM, local time
    actor_name: str  # the name kept on the entry, else «Систем»
    category_label: str  # an unknown code shows as stored
    action_label: str  # an unknown code shows as stored
    target_type: str
    target_label: str
    message: str  # drawn as text, never as HTML
    changes: list[LogChangeOut]
    ip: str  # "" when the entry has none


class LogSystemQueryOut(Schema):
    q: str
    categories: list[str]
    action: str
    by: str
    target: str
    ip: str
    date_from: str  # YYYY-MM-DD or ""
    date_to: str  # YYYY-MM-DD or ""
    oldest: bool


class LogSystemOptionsOut(Schema):
    categories: list[LogOptionOut]
    actions: list[LogOptionOut]


class LogSystemOut(Schema):
    rows: list[LogSystemRowOut]
    next_offset: int | None  # the offset of the next batch; None when this is the last one
    query: LogSystemQueryOut
    options: LogSystemOptionsOut
    tabs: LogTabsOut
    address: str  # the cleaned filters as a query string (the Excel link and the address bar)


def _person_name(employee: Employee) -> str:
    return f"{employee.family_name} {employee.given_name}"


def _tabs_out(user: User, page: Literal["employee", "system"]) -> LogTabsOut:
    tabs = page_rules.tabs_for(user, page)
    return LogTabsOut(employee=tabs.employee, system=tabs.system, export=tabs.export)


def _query_dict(values: dict[str, str], repeated: dict[str, list[str]]) -> QueryDict:
    """The typed parameters as the URL would carry them, so the parsers read them exactly as the Django views do."""
    params = QueryDict(mutable=True)
    for name, value in values.items():
        if value:
            params[name] = value
    for name, items in repeated.items():
        params.setlist(name, items)
    return params


def _employee_filter(
    q: str,
    emp: str,
    employee: str,
    by: str,
    area: str,
    field: str,
    from_: str,
    to: str,
    kind: list[str] | None,
    system: str,
    oldest: str,
) -> EmployeeLogFilter:
    """The employee log's typed parameters through the same parser the Django page uses (junk is dropped)."""
    return parse_filter(
        _query_dict(
            {
                "q": q,
                "emp": emp,
                "employee": employee,
                "by": by,
                "area": area,
                "field": field,
                "from": from_,
                "to": to,
                "system": system,
                "oldest": oldest,
            },
            {"kind": kind or []},
        )
    )


def _system_filter(
    q: str,
    by: str,
    target: str,
    ip: str,
    action: str,
    from_: str,
    to: str,
    category: list[str] | None,
    oldest: str,
) -> SystemLogFilter:
    """The system log's typed parameters through the same parser the Django page uses (junk is dropped)."""
    return parse_system_filter(
        _query_dict(
            {
                "q": q,
                "by": by,
                "target": target,
                "ip": ip,
                "action": action,
                "from": from_,
                "to": to,
                "oldest": oldest,
            },
            {"category": category or []},
        )
    )


def _by_name(entry: ActivityEntry) -> str:
    if entry.by is None:
        return NO_NAME
    return entry.by.get_full_name() or entry.by.username or NO_NAME


def _change(change: dict[str, Any]) -> LogChangeOut:
    new = change.get("new")
    return LogChangeOut(
        field=str(change.get("field") or ""),
        old=str(change.get("old") or ""),
        new=str(new) if new else EMPTY_NEW,
    )


def _employee_row(entry: ActivityEntry) -> LogEmployeeRowOut:
    at = timezone.localtime(entry.at)
    employee = entry.employee
    return LogEmployeeRowOut(
        id=entry.pk,
        date=at.date().isoformat(),
        time=at.strftime("%H:%M"),
        employee_id=entry.employee_id,
        employee_name=_person_name(employee),
        employee_code=employee.code,
        by_name=_by_name(entry),
        kind=entry.kind,
        kind_label=entry.get_kind_display(),
        kind_class=page_rules.kind_tone(entry.kind),
        is_note=entry.kind == ActivityKind.NOTE,
        is_correction=entry.kind == ActivityKind.CORRECTION,
        message=entry.message,
        changes=[_change(change) for change in entry.changes or []],
        order_id=entry.order_id,
    )


def _system_row(entry: SystemLogEntry) -> LogSystemRowOut:
    at = timezone.localtime(entry.at)
    return LogSystemRowOut(
        id=entry.pk,
        date=at.date().isoformat(),
        time=at.strftime("%H:%M"),
        actor_name=entry.actor_name or NO_NAME,
        category_label=category_label(entry.category),
        action_label=action_label(entry.action),
        target_type=entry.target_type,
        target_label=entry.target_label,
        message=entry.message,
        changes=[_change(change) for change in entry.changes or []],
        ip=str(entry.ip) if entry.ip else "",
    )


def _system_query_out(f: SystemLogFilter) -> LogSystemQueryOut:
    return LogSystemQueryOut(
        q=f.q,
        categories=f.categories,
        action=f.action,
        by=f.by,
        target=f.target,
        ip=f.ip,
        date_from=f.date_from.isoformat() if f.date_from is not None else "",
        date_to=f.date_to.isoformat() if f.date_to is not None else "",
        oldest=f.oldest_first,
    )


def _query_out(f: EmployeeLogFilter) -> LogEmployeeQueryOut:
    return LogEmployeeQueryOut(
        q=f.q,
        emp=f.emp,
        employee=f.employee,
        by=f.by,
        kinds=f.kinds,
        area=f.area,
        field=f.field,
        date_from=f.date_from.isoformat() if f.date_from is not None else "",
        date_to=f.date_to.isoformat() if f.date_to is not None else "",
        system=f.system_only,
        oldest=f.oldest_first,
    )


@log_router.get("/employee", response=LogEmployeeOut, auth=django_auth)
def employee_log(
    request: HttpRequest,
    response: HttpResponse,
    q: str = "",
    emp: str = "",
    employee: str = "",
    by: str = "",
    area: str = "",
    field: str = "",
    from_: str = Query("", alias="from"),
    to: str = "",
    kind: Query[list[str] | None] = None,
    system: str = "",
    oldest: str = "",
    offset: str = "",
) -> LogEmployeeOut:
    """One batch of the employee log, newest first unless `oldest`. Unknown or junk filter values are dropped."""
    user = request_user(request)
    if not user.has_perm("macs.view_employees"):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    f = _employee_filter(q, emp, employee, by, area, field, from_, to, kind, system, oldest)
    # A person the user may not see is dropped before the address and the paging read the filter.
    chip = page_rules.visible_chip(user, f)
    start = batch_offset(offset)
    size = batching.LIST_BATCH  # read at call time so tests can shrink the batch
    entries, more = page(user, f, start, size)
    response["Cache-Control"] = "no-store"
    return LogEmployeeOut(
        rows=[_employee_row(entry) for entry in entries],
        next_offset=start + size if more else None,
        query=_query_out(f),
        chip=LogChipOut(id=chip.pk, name=_person_name(chip)) if chip is not None else None,
        options=LogEmployeeOptionsOut(
            kinds=[LogOptionOut(value=value, label=str(label)) for value, label in ActivityKind.choices],
            areas=[LogOptionOut(value=value, label=label) for value, label in page_rules.AREA_LABELS],
        ),
        tabs=_tabs_out(user, "employee"),
        address=page_rules.employee_address(f),
    )


@log_router.get("/system", response=LogSystemOut, auth=django_auth)
def system_log(
    request: HttpRequest,
    response: HttpResponse,
    q: str = "",
    by: str = "",
    target: str = "",
    ip: str = "",
    action: str = "",
    from_: str = Query("", alias="from"),
    to: str = "",
    category: Query[list[str] | None] = None,
    oldest: str = "",
    offset: str = "",
) -> LogSystemOut:
    """One batch of the system log, newest first unless `oldest`. Unknown or junk filter values are dropped."""
    user = request_user(request)
    if not user.has_perm("accounts.view_audit"):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    f = _system_filter(q, by, target, ip, action, from_, to, category, oldest)
    start = batch_offset(offset)
    size = batching.LIST_BATCH  # read at call time so tests can shrink the batch
    entries, more = system_page(f, start, size)
    response["Cache-Control"] = "no-store"
    return LogSystemOut(
        rows=[_system_row(entry) for entry in entries],
        next_offset=start + size if more else None,
        query=_system_query_out(f),
        options=LogSystemOptionsOut(
            categories=[LogOptionOut(value=value, label=str(label)) for value, label in Category.choices],
            actions=[LogOptionOut(value=value, label=label) for value, label in ACTIONS.items()],
        ),
        tabs=_tabs_out(user, "system"),
        address=page_rules.system_address(f),
    )


@log_router.get("/employee/export", auth=django_auth)
def employee_export(
    request: HttpRequest,
    q: str = "",
    emp: str = "",
    employee: str = "",
    by: str = "",
    area: str = "",
    field: str = "",
    from_: str = Query("", alias="from"),
    to: str = "",
    kind: Query[list[str] | None] = None,
    system: str = "",
    oldest: str = "",
) -> HttpResponse:
    """The employee log as an Excel file: every row the screen shows for this address. Needs view and export rights."""
    user = request_user(request)
    if not page_rules.tabs_for(user, "employee").export:  # view_employees AND export_lists, as the Django view
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    f = _employee_filter(q, emp, employee, by, area, field, from_, to, kind, system, oldest)
    # visible_chip clears f.employee when the user may not see that person, so the file has no hidden rows or name.
    page_rules.visible_chip(user, f)
    workbook, tally = page_rules.employee_workbook(user, f)
    record_export(
        request,
        "export_log",
        "Ажилтны бүртгэл",
        filters=export.employee_filter_label(f),
        rows=tally.rows,
    )
    workbook["Cache-Control"] = "no-store"
    return workbook


@log_router.get("/system/export", auth=django_auth)
def system_export(
    request: HttpRequest,
    q: str = "",
    by: str = "",
    target: str = "",
    ip: str = "",
    action: str = "",
    from_: str = Query("", alias="from"),
    to: str = "",
    category: Query[list[str] | None] = None,
    oldest: str = "",
) -> HttpResponse:
    """The system log as an Excel file: every row the screen shows for this address. Needs audit and export rights."""
    user = request_user(request)
    if not page_rules.tabs_for(user, "system").export:  # view_audit AND export_lists, as the Django view
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    f = _system_filter(q, by, target, ip, action, from_, to, category, oldest)
    workbook, tally = page_rules.system_workbook(f)
    record_export(
        request,
        "export_log",
        "Системийн бүртгэл",
        filters=export.system_filter_label(f),
        rows=tally.rows,
    )
    workbook["Cache-Control"] = "no-store"
    return workbook
