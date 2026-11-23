"""The rules of the two log pages that need no request: the address of a filter, the employee chip, the tabs, the
kind tones and the body of the Excel files. The Django views (logs/views.py) and the React API (app/api/logs.py) both
use them.
"""

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

from accounts.models import User
from django.http import HttpResponse
from django.utils import timezone
from employees import access
from employees.models import Employee

from logs import export
from logs.employee_query import EmployeeLogFilter, filtered
from logs.system_query import SystemLogFilter
from logs.system_query import filtered as filtered_system

EXPORT_PERM = "accounts.export_lists"  # the Excel file and its button
AREA_LABELS = (
    ("salary", "Цалин"),
    ("personal", "Хувийн мэдээлэл"),
    ("orders", "Тушаал"),
    ("notes", "Тэмдэглэл"),
)

KIND_TAG = "whitespace-nowrap rounded px-1.5 py-0.5 text-xs "
_KIND_TONES = {
    "correction": "bg-amber-50 text-amber-700",
    "history": "bg-violet-50 text-violet-700",
    "note": "bg-sky-50 text-sky-700",
    "created": "bg-emerald-50 text-emerald-700",
    "added": "bg-emerald-50 text-emerald-700",
    "deleted": "bg-red-50 text-red-700",
    "cancelled": "bg-red-50 text-red-700",
}
_DEFAULT_TONE = "bg-slate-100 text-slate-600"


@dataclass(frozen=True)
class LogTabs:
    employee: bool
    system: bool
    export: bool


def employee_address(f: EmployeeLogFilter) -> str:
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


def system_address(f: SystemLogFilter) -> str:
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


def visible_chip(user: User, f: EmployeeLogFilter) -> Employee | None:
    """The employee named by the filter if the user may see them; otherwise the filter is dropped and None returned."""
    chip = access.visible_employees(user).filter(pk=f.employee).first() if f.employee is not None else None
    f.employee = chip.pk if chip is not None else None
    return chip


def tabs_for(user: User, page: Literal["employee", "system"]) -> LogTabs:
    """Which log tabs the user sees, and whether the Excel button shows on `page`."""
    page_perm = "macs.view_employees" if page == "employee" else "accounts.view_audit"
    return LogTabs(
        employee=user.has_perm("macs.view_employees"),
        system=user.has_perm("accounts.view_audit"),
        export=user.has_perm(EXPORT_PERM) and user.has_perm(page_perm),
    )


def kind_tone(kind: str) -> str:
    """The chip classes of one activity kind (the same colours as _employee_items.html)."""
    return KIND_TAG + _KIND_TONES.get(kind, _DEFAULT_TONE)


def employee_workbook(user: User, f: EmployeeLogFilter) -> tuple[HttpResponse, export.Tally]:
    """The employee log as an Excel response: the rows the screen shows for this address (the caller logs it)."""
    tally = export.Tally()
    today = timezone.localdate().isoformat()
    response = export.workbook_response(
        f"employee-log-{today}.xlsx",
        export.EMPLOYEE_HEADERS,
        export.capped_rows(filtered(user, f), export.employee_row, tally),
        export.EMPLOYEE_WIDTHS,
    )
    return response, tally


def system_workbook(f: SystemLogFilter) -> tuple[HttpResponse, export.Tally]:
    """The system log as an Excel response: the rows the screen shows for this address (the caller logs the export)."""
    tally = export.Tally()
    today = timezone.localdate().isoformat()
    response = export.workbook_response(
        f"system-log-{today}.xlsx",
        export.SYSTEM_HEADERS,
        export.capped_rows(filtered_system(f), export.system_row, tally),
        export.SYSTEM_WIDTHS,
    )
    return response, tally
