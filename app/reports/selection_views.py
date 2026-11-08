"""The Excel, CSV and print files of the rows a user picked on a report. Each is one POST: the report's address
(`query`) plus the ticked ids or `all`, checked by selection.pick before anything is written."""

import logging
import re
from dataclasses import dataclass
from datetime import date

from accounts.audit import record_export
from accounts.models import User
from checklists import access as checklist_access
from checklists.forms import template_match_choices
from checklists.models import ChecklistKind, ChecklistTemplate
from checklists.services import lifecycle
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse, QueryDict
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from employees import listing
from employees.models import CompanySettings
from macs.models import Employee

from reports import excel, registry
from reports.csvout import csv_bytes
from reports.filters import describe
from reports.selection import Picked, SelectionError, pick, subset
from reports.table import Table, allowed_columns, column_classes
from reports.types import Report
from reports.views import EXPORT_PERM, MAX_PORTRAIT_COLUMNS, XLSX

NO_NAME_COLUMN = "Нэр харуулах багана алга"  # the copy needs the report's name column, and the user may see it


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)  # login_required guarantees a real user
    return request.user


def _report_for(request: HttpRequest, key: str, *, export: bool) -> Report:
    """The report, if it can pick people: 404 when missing or it has no person, 403 when the user may not open it
    (or, for a file, may not export)."""
    user = _user(request)
    report = registry.get(key)
    if report is None or report.person is None:
        raise Http404
    if not registry.can_open(user, report) or (export and not user.has_perm(EXPORT_PERM)):
        raise PermissionDenied
    return report


def _refused(error: SelectionError) -> HttpResponse:
    return HttpResponse(error.message, status=400, content_type="text/plain; charset=utf-8")


def _lines(user: User, report: Report, table: Table) -> tuple[list[str], str]:
    """The filter lines the file shows, and the same lines as one audit label."""
    labels = {c.key: c.label for c in allowed_columns(report, user)}
    lines = describe(table.filters, report.filters, labels=labels)
    log_label = describe(table.filters, report.filters, for_log=True, labels=labels)
    return lines, "; ".join(log_label)


@login_required
@require_POST
def selected_excel(request: HttpRequest, key: str) -> HttpResponse:
    """The chosen people's rows as an Excel file: the screen's visible columns, no footer."""
    user = _user(request)
    report = _report_for(request, key, export=True)
    try:
        picked = pick(request, user, report)
    except SelectionError as error:
        return _refused(error)
    table = subset(picked.table, report, picked.ids)
    lines, log_label = _lines(user, report, table)
    note = report.note(table.filters) if report.note is not None else ""
    lines += [note] if note else []
    today = timezone.localdate().isoformat()
    response = HttpResponse(excel.workbook_bytes(report.title, lines, table, sheet=report.key), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{report.key}-selected-{today}.xlsx"'
    record_export(request, "export_selected", report.title, filters=log_label, rows=table.count)
    return response


@login_required
@require_POST
def selected_csv(request: HttpRequest, key: str) -> HttpResponse:
    """The chosen people's rows as a CSV file (UTF-8 with BOM)."""
    user = _user(request)
    report = _report_for(request, key, export=True)
    try:
        picked = pick(request, user, report)
    except SelectionError as error:
        return _refused(error)
    table = subset(picked.table, report, picked.ids)
    lines, log_label = _lines(user, report, table)
    today = timezone.localdate().isoformat()
    response = HttpResponse(csv_bytes(lines, table), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{report.key}-selected-{today}.csv"'
    record_export(request, "export_selected", report.title, filters=log_label, rows=table.count)
    return response


@login_required
@require_POST
def selected_print(request: HttpRequest, key: str) -> HttpResponse:
    """The print page of the chosen people's rows: the same page as the whole report's print, with the subset."""
    user = _user(request)
    report = _report_for(request, key, export=False)
    try:
        picked = pick(request, user, report)
    except SelectionError as error:
        return _refused(error)
    table = subset(picked.table, report, picked.ids)
    lines, log_label = _lines(user, report, table)
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
    record_export(request, "print_selected", report.title, filters=log_label, rows=table.count)
    return response


# every character str.splitlines() breaks a line on, plus the tab: each becomes one space, so a person is one line
LINE_BREAKS = re.compile(r"[\t\n\r\x0b\x0c\x1c\x1d\x1e\x85  ]")


def _one_line(value: object) -> str:
    """A cell's text on one line: blank for None, and every tab or line break becomes a space."""
    return LINE_BREAKS.sub(" ", "" if value is None else str(value))


@login_required
@require_POST
def selected_copy(request: HttpRequest, key: str) -> HttpResponse:
    """The chosen people's names, one line each in report order, with the work email after a tab when the user may
    see the report's email column. Audited as an export (`copy_selected`), as the file and print actions are."""
    user = _user(request)
    report = _report_for(request, key, export=False)
    by_key = {c.key: c for c in allowed_columns(report, user)}
    name = by_key.get("name")
    if name is None:
        return HttpResponse(NO_NAME_COLUMN, status=400, content_type="text/plain; charset=utf-8")
    email = by_key.get("email")
    try:
        picked = pick(request, user, report)
    except SelectionError as error:
        return _refused(error)
    table = subset(picked.table, report, picked.ids)
    lines: list[str] = []
    for row in table.rows:
        line = _one_line(name.value(row))
        if email is not None:
            line += "\t" + _one_line(email.value(row))
        lines.append(line)
    _, log_label = _lines(user, report, table)
    record_export(request, "copy_selected", report.title, filters=log_label, rows=table.count)
    return JsonResponse({"text": "\n".join(lines), "count": len(lines), "dropped": picked.dropped})


logger = logging.getLogger(__name__)

KIND = ChecklistKind.OFFBOARDING.value  # the only kind the pop-up starts; onboarding starts itself at the hire
ANCHOR_MIN = date(1990, 1, 1)  # the earliest anchor day a checklist may take
ANCHOR_MAX = date(2100, 12, 31)
DATE_TEXT_LENGTH = 10  # YYYY-MM-DD, the only date text read
OUTCOME_LABELS = {
    "started": "Эхэлсэн",
    "already_open": "Нээлттэй байсан",
    "no_template": "Загвар алга",
    "not_allowed": "Харах эрх алга",
    "left": "Ажлаас гарсан",
    "error": "Алдаа гарлаа",
}
MSG_KIND = "Энд зөвхөн «Ажлаас гарах» жагсаалт эхлүүлнэ."
MSG_DATE = "Огноог 2026-11-07 хэлбэрээр оруулна уу."
MSG_RANGE = f"Огноо {ANCHOR_MIN.isoformat()}-ээс {ANCHOR_MAX.isoformat()} хооронд байх ёстой."
MSG_REASON = "Шалтгаан буруу байна. Жагсаалтаас сонгоно уу."


@dataclass(frozen=True)
class _Values:
    """The checklist pop-up's fields as the user left them. The date is kept as typed, for showing again."""

    kind: str
    reason: str
    anchor_day: str


DATE_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # ASCII digits only; week dates and other forms are refused


@dataclass(frozen=True)
class _Outcome:
    """What happened for one picked person. `employee` is None only when the person could not be read back."""

    pk: int
    employee: Employee | None
    outcome: str


def _typed(data: QueryDict, today: str) -> _Values:
    """The fields as the user typed them, for showing the form again after a refusal. The date text is shown as typed
    (at most 10 characters), today when nothing was typed."""
    return _Values(
        kind=KIND,
        reason=data.get("reason", ""),
        anchor_day=data.get("anchor_day", "")[:DATE_TEXT_LENGTH] or today,
    )


def _anchor_day(text: str) -> date:
    """A calendar day written as YYYY-MM-DD with ASCII digits. Raises ValueError for any other text."""
    if DATE_TEXT.fullmatch(text) is None:
        raise ValueError(text)
    return date.fromisoformat(text)


def _reason_choices(kind: str) -> list[tuple[str, str]]:
    """The reasons that some active template of `kind` lists, with their names (value = the text a template stores)."""
    listed: set[str] = set()
    for template in ChecklistTemplate.objects.filter(kind=kind, active=True):
        listed.update(str(reason) for reason in template.reasons or [])
    return [(value, label) for value, label in template_match_choices(kind) if value in listed]


def _read_values(data: QueryDict) -> tuple[_Values, date | None, list[str]]:
    """The posted fields, checked. Returns the values, the anchor day (None when not valid) and the errors."""
    errors: list[str] = []
    if "kind" in data and data["kind"] != KIND:  # the field is no longer shown; an absent kind means offboarding
        errors.append(MSG_KIND)
    reason = data.get("reason", "")
    if reason and reason not in {value for value, _ in _reason_choices(KIND)}:
        errors.append(MSG_REASON)
    text = data.get("anchor_day", "")
    anchor: date | None = None
    try:
        anchor = _anchor_day(text)
    except ValueError:
        errors.append(MSG_DATE)
    else:
        if not ANCHOR_MIN <= anchor <= ANCHOR_MAX:
            errors.append(MSG_RANGE)
            anchor = None
    return _Values(kind=KIND, reason=reason, anchor_day=text[:DATE_TEXT_LENGTH]), anchor, errors


def _checklist_form(
    request: HttpRequest,
    key: str,
    *,
    picked: Picked | None,
    values: _Values,
    errors: list[str],
) -> HttpResponse:
    """The checklist pop-up, always status 200 (htmx swaps 2xx; UI_RULES §6): a refused field shows its error in the
    form. The selection goes back as hidden fields: the report address, the all-matching flag, or the ids `pick`
    checked (never raw input)."""
    all_people = request.POST.get("all") == "1"
    context = {
        "action": reverse("reports:sel_checklist", args=[key]),
        "reasons": _reason_choices(KIND),
        "reason": values.reason,
        "anchor_day": values.anchor_day,
        "anchor_min": ANCHOR_MIN.isoformat(),
        "anchor_max": ANCHOR_MAX.isoformat(),
        "query": request.POST.get("query", ""),
        "all_people": all_people,
        "ids": [] if picked is None or all_people else list(picked.ids),
        "count": len(picked.ids) if picked is not None else 0,
        "errors": errors,
        "template_missing": not ChecklistTemplate.objects.filter(kind=KIND, active=True).exists(),
    }
    return render(request, "reports/_selection_checklist.html", context)


def _outcome(user: User, employee: Employee, values: _Values, anchor_day: date, today: date) -> str:
    """The outcome for one person. Checked in this order: a person who has left gets no checklist even if one is
    open; an open checklist of the kind is left as it is (its day and task dates never move); else one is started."""
    if not checklist_access.can_see_employee(user, employee):
        return "not_allowed"
    if listing.row_for(employee, today).state == "left":
        return "left"
    if lifecycle.open_checklist(employee, values.kind) is not None:
        return "already_open"
    started = lifecycle.start(employee, values.kind, reason=values.reason or None, anchor_day=anchor_day, by=user)
    return "no_template" if started is None else "started"


def _start_each(user: User, picked: Picked, values: _Values, anchor_day: date, today: date) -> list[_Outcome]:
    """Check and start each picked person, one after another. A refusal or an unexpected error for one person is
    that person's outcome and never stops the others. The start itself writes the activity entry and the log.
    Every picked id gets one outcome, so the counts add up to the picked count."""
    employees = Employee.objects.in_bulk(picked.ids)
    outcomes: list[_Outcome] = []
    for pk in picked.ids:
        employee = employees.get(pk)
        if employee is None:
            outcomes.append(_Outcome(pk, None, "not_allowed"))  # picked, but not readable now: never silently dropped
            continue
        try:
            outcome = _outcome(user, employee, values, anchor_day, today)
        except Exception:  # one person's failure is reported on their line; the rest still run
            logger.exception("Checklist start failed for employee %s", pk)
            outcome = "error"
        outcomes.append(_Outcome(pk, employee, outcome))
    return outcomes


@login_required
def selected_checklist(request: HttpRequest, key: str) -> HttpResponse:
    """The offboarding checklist pop-up for the chosen people, POST only. A POST without `confirm` renders the form
    (the selection comes back as hidden fields); a POST with `confirm` starts a checklist for each person and renders
    the result per person. Needs the right to start a checklist by hand."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    user = _user(request)
    report = _report_for(request, key, export=False)
    if not checklist_access.can_start(user):
        raise PermissionDenied
    today = timezone.localdate()
    typed = _typed(request.POST, today.isoformat())
    try:
        picked = pick(request, user, report)
    except SelectionError as error:
        return _checklist_form(request, key, picked=None, values=typed, errors=[error.message])
    if "confirm" not in request.POST:
        return _checklist_form(request, key, picked=picked, values=typed, errors=[])
    values, anchor, errors = _read_values(request.POST)
    if anchor is None or errors:
        return _checklist_form(request, key, picked=picked, values=values, errors=errors)
    outcomes = _start_each(user, picked, values, anchor, today)
    counts = {name: sum(1 for item in outcomes if item.outcome == name) for name in OUTCOME_LABELS}
    rows = [
        {
            "code": (item.employee.code if item.employee else None) or str(item.pk),
            "name": item.employee.full_name if item.employee else "",
            "outcome": OUTCOME_LABELS[item.outcome],
        }
        for item in outcomes
    ]
    context = {"report": report, "counts": counts, "rows": rows, "dropped": picked.dropped}
    return render(request, "reports/_selection_result.html", context)
