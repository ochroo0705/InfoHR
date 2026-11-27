"""The Excel, CSV and print files of the rows a user picked on a report. Each is one POST: the report's address
(`query`) plus the ticked ids or `all`, checked by selection.pick before anything is written."""

from datetime import date

from accounts.audit import record_export
from accounts.models import User
from checklists import access as checklist_access
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse, QueryDict
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from reports import registry
from reports.selection import Picked, SelectionError, pick
from reports.services import exports
from reports.services import selection_checklist as checklist_service
from reports.services.exports import LINE_BREAKS, NO_NAME_COLUMN, _one_line  # noqa: F401 (tests import them from here)
from reports.services.print_page import build_print
from reports.services.selection_checklist import DATE_TEXT_LENGTH, KIND, MSG_KIND, Values
from reports.types import Report
from reports.views import EXPORT_PERM


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
    exported = exports.selected_file(user, report, picked, "xlsx")
    response = HttpResponse(exported.body, content_type=exported.content_type)
    response["Content-Disposition"] = f'attachment; filename="{exported.filename}"'
    record_export(request, exported.log_action, report.title, filters=exported.log_label, rows=exported.rows)
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
    exported = exports.selected_file(user, report, picked, "csv")
    response = HttpResponse(exported.body, content_type=exported.content_type)
    response["Content-Disposition"] = f'attachment; filename="{exported.filename}"'
    record_export(request, exported.log_action, report.title, filters=exported.log_label, rows=exported.rows)
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
    # the picked table is the report for the posted address, already built: build_print reuses it
    page = build_print(user, report, picked.table.filters, only=picked.ids, table=picked.table)
    context = {
        "report": report,
        "table": page.table,
        "heads": page.heads,
        "lines": page.lines,
        "note": page.note,
        "landscape": page.landscape,
        "company": page.company,
        "today": date.fromisoformat(page.today),
        "printed_by": page.printed_by,
    }
    response = render(request, "reports/print.html", context)
    record_export(request, "print_selected", report.title, filters=page.log_label, rows=page.count)
    return response


@login_required
@require_POST
def selected_copy(request: HttpRequest, key: str) -> HttpResponse:
    """The chosen people's names, one line each in report order, with the work email after a tab when the user may
    see the report's email column. Audited as an export (`copy_selected`), as the file and print actions are."""
    user = _user(request)
    report = _report_for(request, key, export=False)
    try:
        exports.copy_columns(user, report)  # the name column is checked before anyone is picked
        picked = pick(request, user, report)
    except SelectionError as error:
        return _refused(error)
    result = exports.selected_copy(user, report, picked)
    record_export(request, "copy_selected", report.title, filters=result.log_label, rows=result.count)
    return JsonResponse({"text": result.text, "count": result.count, "dropped": result.dropped})


def _typed(data: QueryDict, today: str) -> Values:
    """The fields as the user typed them, for showing the form again after a refusal. The date text is shown as typed
    (at most 10 characters), today when nothing was typed."""
    return Values(
        reason=data.get("reason", ""),
        anchor_day=data.get("anchor_day", "")[:DATE_TEXT_LENGTH] or today,
    )


def _checklist_form(
    request: HttpRequest,
    key: str,
    *,
    picked: Picked | None,
    values: Values,
    errors: list[str],
) -> HttpResponse:
    """The checklist pop-up, always status 200 (htmx swaps 2xx; UI_RULES §6): a refused field shows its error in the
    form. The selection goes back as hidden fields: the report address, the all-matching flag, or the ids `pick`
    checked (never raw input)."""
    all_people = request.POST.get("all") == "1"
    form = checklist_service.form_model(timezone.localdate())
    context = {
        "action": reverse("reports:sel_checklist", args=[key]),
        "reasons": form.reasons,
        "reason": values.reason,
        "anchor_day": values.anchor_day,
        "anchor_min": form.anchor_min,
        "anchor_max": form.anchor_max,
        "query": request.POST.get("query", ""),
        "all_people": all_people,
        "ids": [] if picked is None or all_people else list(picked.ids),
        "count": len(picked.ids) if picked is not None else 0,
        "errors": errors,
        "template_missing": form.template_missing,
    }
    return render(request, "reports/_selection_checklist.html", context)


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
    values, anchor, errors = checklist_service.read_values(
        request.POST.get("reason", ""), request.POST.get("anchor_day", "")
    )
    if request.POST.get("kind", KIND) != KIND:  # the field is no longer shown; an absent kind means offboarding
        errors.insert(0, MSG_KIND)
    if anchor is None or errors:
        return _checklist_form(request, key, picked=picked, values=values, errors=errors)
    outcomes = checklist_service.start_each(user, picked, values, anchor, today)
    result = checklist_service.result_of(outcomes, picked.dropped)
    rows = [{"code": code, "name": name, "outcome": outcome} for code, name, outcome in result.rows]
    context = {"report": report, "counts": result.counts, "rows": rows, "dropped": result.dropped}
    return render(request, "reports/_selection_result.html", context)
