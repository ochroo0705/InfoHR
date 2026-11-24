from datetime import date
from typing import Any

from accounts.models import User
from config import batching
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from employees import access as employee_access
from employees.models import Department, Employee
from employees.services.macs_writes import ListEntryInUse
from macs.models import LeaveTypeRow

from leave import access
from leave.forms import (
    ApprovalSettingsForm,
    CancelForm,
    LeaveForm,
    LeaveTypeForm,
    loaded_from_post,
)
from leave.models import LeaveSettings
from leave.services import records, writes
from leave.services.balance_page import balance_batch
from leave.services.calendar_page import (
    build_calendar,
    parse_department,
    parse_month,
)
from leave.services.form_page import (
    add_initial,
    assisted_lines,
    cancel_info,
    check_for,
    edit_initial,
    own_leave,
    visible_pk,
)
from leave.services.holiday_page import apply_holiday_action, holiday_page, parse_year
from leave.services.list_page import banners, list_batch, not_configured_text, parse_filter, parse_id
from leave.services.settings_page import (
    approval_initial,
    ext_values,
    save_approval,
    save_auto_grant,
    type_initial,
    type_rows,
)


def today() -> date:
    return timezone.localdate()


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _require(allowed: bool) -> None:
    if not allowed:
        raise PermissionDenied


def _done() -> HttpResponse:
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


@login_required
def leave_list(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_view(user))
    flt = parse_filter(user, request.GET)
    t = today()
    batch = batching.paged(request, lambda offset, size: list_batch(user, flt, offset, size))
    not_configured, missing = banners(t)
    context = {
        "items": batch.shown,
        "offset": batch.offset,
        "next_query": batch.next_query,
        "types": LeaveTypeRow.objects.all(),
        "filters": request.GET,
        "q": flt.q,
        "can_record": access.can_record(user),
        "today": t,
        "not_configured": not_configured,
        "missing_holidays": missing,
    }
    template = "leave/_rows.html" if request.headers.get("HX-Request") else "leave/list.html"
    return render(request, template, context)


def _leave_form(
    request: HttpRequest,
    form: LeaveForm,
    *,
    title: str,
    leave_id: int | None = None,
    loaded: writes.AssignSnapshot | None = None,
    error: str = "",
    extra: dict[str, Any] | None = None,
) -> HttpResponse:
    context = {
        "form": form,
        "action": request.path,
        "title": title,
        "error": error,
        "leave_id": leave_id or "",
        "loaded": loaded,
        "not_configured": not_configured_text(),
        **(extra or {}),
    }
    return render(request, "leave/_form.html", context)


def _add_extra(
    request: HttpRequest, user: User, employees: QuerySet[Employee], employee_pk: int | None
) -> dict[str, Any] | None:
    """The assistant's lines for the add form, None when the page was not opened from the assistant. The form posts to
    the address it was opened with, so an invalid POST still knows the origin and the filled values (display only)."""
    if request.GET.get("from") != "assistant":
        return None
    t = today()
    _, filled = add_initial(request.GET, employees, t)
    return {"action": request.get_full_path(), "from_assistant": True, **assisted_lines(user, employee_pk, filled, t)}


@login_required
def leave_add(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    employees = employee_access.visible_employees(user)
    if request.method != "POST":
        initial, _ = add_initial(request.GET, employees, today())
        form = LeaveForm(initial=initial, employees=employees)
        extra = _add_extra(request, user, employees, initial.get("employee"))
        return _leave_form(request, form, title="Чөлөө бүртгэх", extra=extra)
    form = LeaveForm(request.POST, employees=employees)
    if not form.is_valid():
        extra = _add_extra(request, user, employees, visible_pk(request.POST.get("employee"), employees))
        return _leave_form(request, form, title="Чөлөө бүртгэх", extra=extra)
    try:
        records.record(form.draft(), user, today())
    except records.LeaveError as e:
        extra = _add_extra(request, user, employees, visible_pk(request.POST.get("employee"), employees))
        return _leave_form(request, form, title="Чөлөө бүртгэх", error=str(e), extra=extra)
    return _done()


@login_required
def leave_edit(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    a, row = own_leave(user, pk)
    employees = employee_access.visible_employees(user)
    title = "Чөлөө засах"
    if request.method != "POST":
        initial = edit_initial(a, row)
        form = LeaveForm(initial=initial, employees=employees, current_type=a.leave_type)
        return _leave_form(request, form, title=title, leave_id=a.pk, loaded=writes.snapshot(a))
    loaded = loaded_from_post(request.POST)
    form = LeaveForm(request.POST, employees=employees, current_type=a.leave_type)
    if loaded is None:  # the hidden row values are missing: show the current row so the next save can work
        return _leave_form(request, form, title=title, leave_id=a.pk, loaded=writes.snapshot(a), error=writes.STALE)
    if not form.is_valid():
        return _leave_form(request, form, title=title, leave_id=a.pk, loaded=loaded)
    try:
        records.update(a, form.draft(leave_id=a.pk, loaded=loaded), user, today())
    except records.LeaveError as e:
        return _leave_form(request, form, title=title, leave_id=a.pk, loaded=loaded, error=str(e))
    return _done()


@login_required
@require_POST
def leave_check(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    form = LeaveForm(request.POST, employees=employee_access.visible_employees(user))
    check = check_for(user, form, parse_id(request.POST.get("leave_id")), today())
    if check is None:
        return HttpResponse("")
    return render(request, "leave/_check.html", {"check": check})


@login_required
def leave_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_record(user))
    a, row = own_leave(user, pk)
    loaded = writes.snapshot(a)
    form = CancelForm(request.POST or None)
    error = ""
    if request.method == "POST":
        posted = loaded_from_post(request.POST)
        if posted is None:
            error = writes.STALE
        else:
            loaded = posted
            if form.is_valid():
                try:
                    records.cancel(a, posted, form.cleaned_data["reason"], user, today())
                    return _done()
                except records.LeaveError as e:
                    error = str(e)
    context = {
        "form": form,
        "row": row,
        "loaded": loaded,
        "error": error,
        "mistake": cancel_info(a, row, today()).mistake,  # same rule as records.cancel
    }
    return render(request, "leave/_cancel.html", context)


@login_required
def balances(request: HttpRequest) -> HttpResponse:
    """Every employee's leave days for the work year that contains today, with the dates the days are valid."""
    user = _user(request)
    _require(access.can_view(user))
    t = today()

    def fetch(offset: int, size: int) -> tuple[list[Any], bool]:
        lines, more = balance_batch(user, offset, size, t)
        return [(line.employee, line.period, line.waiting) for line in lines], more

    batch = batching.paged(request, fetch)
    context = {
        "lines": batch.shown,
        "offset": batch.offset,
        "next_query": batch.next_query,
        "today": t,
        "not_configured": not_configured_text(),
    }
    template = "leave/_balance_rows.html" if batch.offset else "leave/balances.html"
    return render(request, template, context)


@login_required
def team_calendar(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_view(user))
    first = parse_month(request.GET.get("month"), today())
    department = parse_department(request.GET.get("department"))
    page = build_calendar(user, first, department)
    return render(
        request,
        "leave/calendar.html",
        {
            "first": page.first,
            "days": page.days,
            "lines": [(line.employee, line.cells) for line in page.lines],
            "holidays": page.holidays,
            "prev": page.prev,
            "next": page.next,
            "this_month": today().strftime("%Y-%m") if first != today().replace(day=1) else "",
            "today": today(),
            "department": department,
            "departments": Department.objects.exclude(ext__active=False),
            "not_configured": not_configured_text(),
        },
    )


@login_required
def holidays(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    year = parse_year(request.GET.get("year"), today().year)
    error = ""
    if request.method == "POST":
        error = apply_holiday_action(
            year,
            request.POST.get("action", ""),
            request.POST.get("date", ""),
            request.POST.get("name", ""),
            user,
        )
        if not error:
            return redirect(f"{request.path}?year={year}")
    page = holiday_page(year)
    return render(
        request,
        "leave/holidays.html",
        {
            "year": page.year,
            "holidays": page.holidays,
            "error": error,
            "fixed_count": page.fixed_count,
        },
    )


def _settings_page(
    request: HttpRequest, setting: LeaveSettings, approval_form: ApprovalSettingsForm | None = None
) -> HttpResponse:
    context = {
        "types": type_rows(),
        "auto": setting.auto_annual_grant,
        "approval_form": approval_form or ApprovalSettingsForm(initial=approval_initial(setting)),
    }
    return render(request, "leave/settings.html", context)


@login_required
def leave_settings(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    setting = LeaveSettings.get()
    if request.method == "POST" and "step1" in request.POST:  # the approval form (its own submit button)
        approval_form = ApprovalSettingsForm(request.POST)
        if not approval_form.is_valid():
            return _settings_page(request, setting, approval_form=approval_form)
        save_approval(setting, approval_form.settings_values())
        return redirect("leave:settings")
    if request.method == "POST":
        save_auto_grant(setting, request.POST.get("auto_annual_grant", "") in {"on", "1", "true", "True"})
        return redirect("leave:settings")
    return _settings_page(request, setting)


def _type_modal(
    request: HttpRequest, form: LeaveTypeForm, *, row: LeaveTypeRow | None, error: str = ""
) -> HttpResponse:
    if row is None:
        action, title = reverse("leave:type_add"), "Чөлөөний төрөл нэмэх"
    else:
        action, title = reverse("leave:type_edit", args=[row.pk]), "Чөлөөний төрөл засах"
    context = {"form": form, "row": row, "action": action, "title": title, "error": error}
    return render(request, "leave/_type_form.html", context)


@login_required
def leave_type_add(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    if request.method != "POST":
        return _type_modal(request, LeaveTypeForm(initial={"is_active": True, "order": 0}), row=None)
    form = LeaveTypeForm(request.POST)
    if not form.is_valid():
        return _type_modal(request, form, row=None)
    writes.save_leave_type(form.cleaned_data["name"], ext_values(form.cleaned_data))
    return _done()


@login_required
def leave_type_edit(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    row = get_object_or_404(LeaveTypeRow, pk=pk)
    if request.method != "POST":
        return _type_modal(request, LeaveTypeForm(initial=type_initial(row)), row=row)
    form = LeaveTypeForm(request.POST)
    if not form.is_valid():
        return _type_modal(request, form, row=row)
    writes.save_leave_type(form.cleaned_data["name"], ext_values(form.cleaned_data), row=row)
    return _done()


@login_required
@require_POST
def leave_type_delete(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage_settings(user))
    row = get_object_or_404(LeaveTypeRow, pk=pk)
    try:
        writes.delete_leave_type(row)
    except ListEntryInUse as exc:
        return _type_modal(request, LeaveTypeForm(initial=type_initial(row)), row=row, error=str(exc))
    return _done()
