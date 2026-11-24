"""Approver side of leave requests (spec 5.6, 5.7): the requests list, the detail pop-up, approve and reject.

The list shows what the user decides («Надад ирсэн», `waiting_for`) and, with `leave.view_leave`, every request
they may see («Бүгд»). The pop-up shows one request only: the person's post and balance, and who else in the same
department is on leave or waiting for the same days. No salary, register number or other personal data.
"""

from datetime import date

from accounts.models import User
from config import batching
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from employees.access import own_employee
from employees.models import Employee

from leave import access
from leave.forms import ApproveForm, RejectForm, RequestForm
from leave.models import LeaveRequest
from leave.services import request_page
from leave.services import requests as request_service
from leave.services.approvers import (
    approval_enabled,
    can_act,
)
from leave.services.records import LeaveError
from leave.services.request_page import STATUS_FILTERS, detail_for, list_batch, parse_filter
from leave.views import _done, _require, _user, today


def _visible_request(user: User, pk: int, day: date) -> tuple[LeaveRequest, bool, bool]:
    """(request, may act, is override). 404 unless the user may act on it or may see the person's leave."""
    return request_page.visible_request(user, pk, day, can_act)


@login_required
def requests_list(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    day = today()
    flt = parse_filter(request.GET)
    if flt.tab == "all":
        _require(access.can_view(user))
    batch = batching.paged(request, lambda offset, size: list_batch(user, flt, offset, size, day))
    context = {
        "items": batch.shown,
        "offset": batch.offset,
        "next_query": batch.next_query,
        "tab": flt.tab,
        "status": flt.status,
        "statuses": STATUS_FILTERS,
        "can_all": access.can_view(user),
        "filters": request.GET,
    }
    template = "leave/_request_rows.html" if request.headers.get("HX-Request") else "leave/requests.html"
    return render(request, template, context)


def _modal(
    request: HttpRequest,
    user: User,
    req: LeaveRequest,
    may: bool,
    override: bool,
    day: date,
    *,
    form: ApproveForm | None = None,
    error: str = "",
) -> HttpResponse:
    detail = detail_for(user, req, day)
    if form is None:
        form = ApproveForm()
    balance = detail.balance
    context = {
        "req": req,
        "employee": req.employee,
        "job": detail.job,
        "waiting": detail.waiting,
        "status_label": detail.status_label,
        "rule": detail.rule,
        "may": may,
        "override": override,
        "balance": balance,
        "past": detail.past,
        "others": detail.others,
        "history": detail.history,
        "form": form,
        "show_reason": may and (bool(error) or (balance is not None and (balance.needs_override or bool(form.errors)))),
        "reject_form": RejectForm(),
        "error": error,
    }
    return render(request, "leave/_request_detail.html", context)


@login_required
def request_detail(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    day = today()
    req, may, override = _visible_request(user, pk, day)
    return _modal(request, user, req, may, override, day)


@login_required
@require_POST
def request_approve(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    day = today()
    req, may, override = _visible_request(user, pk, day)
    if not may:
        raise Http404
    form = ApproveForm(request.POST)
    if not form.is_valid():
        return _modal(request, user, req, may, override, day, form=form)
    step = request.POST.get("step", "")
    try:
        request_service.approve(
            req,
            user,
            day,
            override_reason=form.cleaned_data["override_reason"],
            expected_step=int(step) if step.isascii() and step.isdecimal() else None,
        )
    except LeaveError as e:
        req, may, override = _visible_request(user, pk, day)  # reload: the request may have moved on
        return _modal(request, user, req, may, override, day, form=form, error=str(e))
    return _done()


@login_required
def request_reject(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    day = today()
    req, may, _ = _visible_request(user, pk, day)
    if not may:
        raise Http404
    form = RejectForm(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        try:
            request_service.reject(req, user, form.cleaned_data["reason"], day)
            return _done()
        except LeaveError as e:
            error = str(e)
    return render(request, "leave/_request_reject.html", {"req": req, "form": form, "error": error})


# --- Staff side (Task 6, spec 5.6, 5.7). The employee is always the logged-in user's own record, never a form field.


def _requester(request: HttpRequest) -> tuple[User, Employee]:
    """The logged-in user and their own record, when they may request leave now: the right, a record, approval on."""
    user = _user(request)
    employee = own_employee(user)
    if employee is None or not user.has_perm("leave.request_own_leave") or not approval_enabled():
        raise PermissionDenied
    return user, employee


@login_required
def request_new(request: HttpRequest) -> HttpResponse:
    user, employee = _requester(request)
    error = ""
    form = RequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            request_service.submit(employee, d["leave_type"], d["start_date"], d["end_date"], d["note"], user, today())
            return _done()
        except LeaveError as e:
            error = str(e)
    return render(request, "leave/_request_form.html", {"form": form, "error": error})


@login_required
@require_POST
def request_check(request: HttpRequest) -> HttpResponse:
    """Live preview of the request form (days, balance, overlaps). POST only: preview may write automatic grants."""
    _, employee = _requester(request)
    form = RequestForm(request.POST)
    if not form.is_valid():
        return HttpResponse("")
    d = form.cleaned_data
    check = request_service.preview(employee, d["leave_type"], d["start_date"], d["end_date"], today())
    return render(request, "leave/_check.html", {"check": check})


@login_required
@require_POST
def request_withdraw(request: HttpRequest, pk: int) -> HttpResponse:
    """The employee takes back their own waiting request. Someone else's request is 404."""
    user = _user(request)
    try:
        request_service.withdraw_own(user, pk, today())
    except LeaveError as e:
        return HttpResponse(format_html('<p class="text-sm text-red-700">{}</p>', str(e)))
    return _done()
