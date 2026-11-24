"""Leave requests API under /api/v1/leave/requests: the approver's requests list («Надад ирсэн», «Бүгд») and the request
detail pop-up, as the React page reads them.

GET /leave/requests (one batch of the list: the user's queue, or every visible request with `tab=all`) and
GET /leave/requests/{pk} (one request: the person's balance, who else is off, and the history). The rules come from
leave.services.request_page; this module reads the request and presents the answer. Rights: `tab=all` needs
leave.view_leave (403 "forbidden" otherwise); the queue and the detail need only a signed-in session (401 without one).
A request the user may not see is 404, as the Django views.

The writes: POST {pk}/approve and {pk}/reject (the approver; 404 unless the user may act on the request), GET /options
and POST /check and POST "" (the staff side: the user's own record and approval on, else 403). Every write answers 200
with the one LeaveWriteResultOut shape, as the leave API does. The same forms and services as the Django views.
"""

from datetime import datetime
from typing import Any

from accounts.models import User
from config import batching
from django.forms import BaseForm
from django.http import Http404, HttpRequest, HttpResponse
from django.utils import timezone
from employees.access import own_employee
from employees.models import Employee
from leave import access
from leave.forms import ApproveForm, RejectForm, RequestForm
from leave.models import LeaveRequest, LeaveRequestAction, RequestStatus
from leave.services import requests as request_service
from leave.services.approvers import approval_enabled, can_act
from leave.services.records import LeaveError
from leave.services.request_page import (
    STATUS_FILTERS,
    RequestDetail,
    Row,
    detail_for,
    list_batch,
    parse_filter,
    visible_request,
)
from ninja import Router, Schema
from ninja.security import django_auth

from api.errors import ApiError, form_error_payload
from api.leave import LeaveCheckOut, LeaveCheckPeriodOut, LeaveChoiceOut, LeaveWriteResultOut
from api.params import batch_offset
from api.popups import FORBIDDEN, request_user, service_errors

leave_requests_router = Router(tags=["leave"])

EMPTY_TEXT = "Хүсэлт олдсонгүй"  # the list's text when no row matches (_request_rows.html)
NO_JOB_TEXT = "Ажлын мэдээлэл алга"  # the detail's line when the person has no job on the day (_request_detail.html)


class LeaveRequestStatusOut(Schema):
    value: str
    label: str


class LeaveRequestRowOut(Schema):
    id: int
    employee_name: str  # «<family> <given>»
    leave_type: str
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    working_days: int
    waiting: bool
    current_step: int | None  # None once decided
    step_count: int | None  # None once decided
    rule: str  # which rule picks the approvers; «» once decided
    status_label: str  # the leave's state when HR cancelled it, else the request's own status
    since: str | None  # YYYY-MM-DD; set only while waiting: the day the request reached its current step


class LeaveRequestListOut(Schema):
    tab: str  # mine or all
    status: str  # the status filter of «Бүгд» («» on mine, and for an unknown status)
    statuses: list[LeaveRequestStatusOut]  # the status filters of «Бүгд», in the order the list shows them
    can_all: bool  # the user may see the «Бүгд» tab (leave.view_leave)
    rows: list[LeaveRequestRowOut]
    next_offset: int | None  # the offset of the next batch; None when this is the last one
    empty_text: str


class LeaveRequestOtherOut(Schema):
    name: str
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    state: str  # «Чөлөөтэй» or «Хүлээгдэж буй»


class LeaveRequestHistoryOut(Schema):
    at: str  # YYYY-MM-DD
    text: str  # the history line as the template draws it: date · action [(n-р шат)] [(эрхээр)] [· by] [· reason]


class LeaveRequestDetailOut(Schema):
    id: int
    employee_name: str
    job_line: str  # «department · position» or «Ажлын мэдээлэл алга»
    leave_type: str
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    working_days: int
    created: str  # YYYY-MM-DD: the day the request was made
    waiting: bool
    current_step: int | None  # None once decided
    step_count: int | None  # None once decided
    rule: str  # «» once decided
    override: bool  # the user may act only by the HR override («эрхээр»)
    balance_after: int | None  # the annual balance left after the request; None unless waiting on an annual type
    warnings: list[str]
    past: bool  # the leave starts before today (the screen shows it only while waiting)
    status_label: str
    reason: str  # the rejection reason (the screen shows it once decided)
    others: list[LeaveRequestOtherOut]
    history: list[LeaveRequestHistoryOut]
    may: bool  # the user may approve or reject it
    needs_reason: bool  # the approval needs an override reason (a negative balance) and the user may act


class LeaveRequestOptionsOut(Schema):
    types: list[LeaveChoiceOut]  # the types staff may request


class LeaveRequestApproveIn(Schema):
    step: int | None = None  # the step the approver's screen was opened at; None: no step check
    override_reason: str = ""


class LeaveRequestRejectIn(Schema):
    reason: str = ""


class LeaveRequestFormIn(Schema):
    """The staff request form as posted. There is no employee: the own record is always used."""

    leave_type: int | None
    start_date: str | None  # YYYY-MM-DD
    end_date: str | None  # YYYY-MM-DD
    note: str = ""


def _query(**values: str | None) -> dict[str, str]:
    """The typed parameters that were sent (an absent one is left out, as the Django address leaves it out)."""
    return {name: value for name, value in values.items() if value is not None}


def _local_day(value: datetime) -> str:
    """The day of a stored time, in local time, as the template's date filter shows it."""
    return timezone.localtime(value).date().isoformat()


def _history_text(action: LeaveRequestAction) -> str:
    """One history line, built as _request_detail.html builds it (the same parts, in the same order)."""
    text = f"{_local_day(action.at)} · {action.get_action_display()}"
    if action.step:
        text += f" ({action.step}-р шат)"
    if action.override:
        text += " (эрхээр)"
    if action.by is not None:
        text += f" · {action.by.get_full_name() or action.by.username}"
    if action.reason:
        text += f" · {action.reason}"
    return text


def _row_out(row: Row) -> LeaveRequestRowOut:
    req: LeaveRequest = row.req
    waiting = req.status == RequestStatus.WAITING
    return LeaveRequestRowOut(
        id=req.pk,
        employee_name=req.employee.full_name,
        leave_type=str(req.leave_type),
        start=req.start_date.isoformat(),
        end=req.end_date.isoformat(),
        working_days=req.working_days,
        waiting=waiting,
        current_step=req.current_step if waiting else None,
        step_count=req.step_count if waiting else None,
        rule=row.rule,
        status_label=row.status or req.get_status_display(),
        since=_local_day(row.since) if waiting and row.since is not None else None,
    )


def _detail_out(req: LeaveRequest, detail: RequestDetail, may: bool, override: bool) -> LeaveRequestDetailOut:
    balance = detail.balance
    job = detail.job
    return LeaveRequestDetailOut(
        id=req.pk,
        employee_name=req.employee.full_name,
        job_line=f"{job.department} · {job.position}" if job is not None else NO_JOB_TEXT,
        leave_type=str(req.leave_type),
        start=req.start_date.isoformat(),
        end=req.end_date.isoformat(),
        working_days=req.working_days,
        created=_local_day(req.created_at),
        waiting=detail.waiting,
        current_step=req.current_step if detail.waiting else None,
        step_count=req.step_count if detail.waiting else None,
        rule=detail.rule,
        override=override,
        balance_after=balance.balance_after if balance is not None else None,
        warnings=balance.warnings if balance is not None else [],
        past=detail.past,
        status_label=detail.status_label,
        reason=req.reason,
        others=[
            LeaveRequestOtherOut(name=o.name, start=o.start.isoformat(), end=o.end.isoformat(), state=o.state)
            for o in detail.others
        ],
        history=[LeaveRequestHistoryOut(at=_local_day(a.at), text=_history_text(a)) for a in detail.history],
        may=may,
        needs_reason=bool(may and balance is not None and balance.needs_override),
    )


@leave_requests_router.get("", response=LeaveRequestListOut, auth=django_auth)
def leave_requests_list(
    request: HttpRequest,
    response: HttpResponse,
    tab: str | None = None,
    status: str | None = None,
    offset: str = "",
) -> LeaveRequestListOut:
    """One batch of the requests list. `tab=all` needs leave.view_leave; any other tab is the user's own queue."""
    user = request_user(request)
    flt = parse_filter(_query(tab=tab, status=status))
    can_view = access.can_view(user)
    if flt.tab == "all" and not can_view:
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    day = timezone.localdate()
    start = batch_offset(offset)
    size = batching.LIST_BATCH  # read at call time so tests can shrink the batch
    batch, more = list_batch(user, flt, start, size, day)
    response["Cache-Control"] = "no-store"
    return LeaveRequestListOut(
        tab=flt.tab,
        status=flt.status,
        statuses=[LeaveRequestStatusOut(value=str(value), label=str(label)) for value, label in STATUS_FILTERS],
        can_all=can_view,
        rows=[_row_out(row) for row in batch],
        next_offset=start + size if more else None,
        empty_text=EMPTY_TEXT,
    )


def _requester(request: HttpRequest) -> tuple[User, Employee]:
    """The logged-in user and their own record, when they may request leave now: the right, a record, approval on.
    The same rule as views_requests._requester; refused with 403 "forbidden"."""
    user = request_user(request)
    employee = own_employee(user)
    if employee is None or not user.has_perm("leave.request_own_leave") or not approval_enabled():
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return user, employee


def _request_form_data(payload: LeaveRequestFormIn) -> dict[str, str]:
    """The posted request form as the browser would send it: an empty box is an empty text, not a missing key."""
    return {
        "leave_type": "" if payload.leave_type is None else str(payload.leave_type),
        "start_date": payload.start_date or "",
        "end_date": payload.end_date or "",
        "note": payload.note,
    }


# /options and /check are declared before /{pk} so that the words are never read as a request id.
@leave_requests_router.get("/options", response=LeaveRequestOptionsOut, auth=django_auth)
def leave_request_options(request: HttpRequest) -> LeaveRequestOptionsOut:
    """The types the staff request form offers (active, and staff may request them)."""
    _requester(request)
    return LeaveRequestOptionsOut(
        types=[LeaveChoiceOut(value=t.pk, label=str(t)) for t in request_service.requestable_types()]
    )


@leave_requests_router.post("/check", response=LeaveCheckOut, auth=django_auth)
def leave_request_check(request: HttpRequest, payload: LeaveRequestFormIn) -> LeaveCheckOut:
    """The live preview of the request form: days, the period, the balance after and the overlaps. An invalid form
    answers valid false with empty lists. Nothing is written."""
    _, employee = _requester(request)
    form = RequestForm(_request_form_data(payload))
    if not form.is_valid():
        return LeaveCheckOut(valid=False, working_days=0, balance_after=None, period=None, errors=[], warnings=[])
    d = form.cleaned_data
    found = request_service.preview(employee, d["leave_type"], d["start_date"], d["end_date"], timezone.localdate())
    period = None
    if found.period is not None:
        period = LeaveCheckPeriodOut(start=found.period.start.isoformat(), end=found.period.end.isoformat())
    return LeaveCheckOut(
        valid=not found.errors,
        working_days=found.working_days,
        balance_after=found.balance_after,
        period=period,
        errors=found.errors,
        warnings=found.warnings,
    )


@leave_requests_router.get("/{pk}", response=LeaveRequestDetailOut, auth=django_auth)
def leave_request_detail(request: HttpRequest, response: HttpResponse, pk: int) -> LeaveRequestDetailOut:
    """The detail pop-up of one request. 404 unless the user may act on it or may see the person's leave."""
    user = request_user(request)
    day = timezone.localdate()
    with service_errors():
        req, may, override = visible_request(user, pk, day, can_act)
    detail = detail_for(user, req, day)
    response["Cache-Control"] = "no-store"
    return _detail_out(req, detail, may, override)


# --- writes -------------------------------------------------------------------------------------------------------
# Every write answers 200 with the one LeaveWriteResultOut shape: ok true, or ok false with the form's own errors
# (field_errors, form_errors) or the service's message (error). A refused write changes nothing.


def _saved() -> dict[str, Any]:
    return {"ok": True, "error": "", "form_errors": [], "field_errors": {}}


def _refused_error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message, "form_errors": [], "field_errors": {}}


def _refused_form(form: BaseForm) -> dict[str, Any]:
    payload = form_error_payload(form)
    return {"ok": False, "error": "", "form_errors": payload["form_errors"], "field_errors": payload["field_errors"]}


def _acting_request(request: HttpRequest, pk: int) -> tuple[User, LeaveRequest]:
    """The request the user may act on, else 404 (as the Django views, so a read-only viewer gets 404 too)."""
    user = request_user(request)
    day = timezone.localdate()
    with service_errors():
        req, may, _override = visible_request(user, pk, day, can_act)
        if not may:
            raise Http404
    return user, req


@leave_requests_router.post("/{pk}/approve", response=LeaveWriteResultOut, auth=django_auth)
def leave_request_approve(request: HttpRequest, pk: int, payload: LeaveRequestApproveIn) -> dict[str, Any]:
    """Approve the current step. The last step writes the leave. A step that is not the one the screen was opened at
    is refused (STEP_MOVED), as the Django view's expected step."""
    user, req = _acting_request(request, pk)
    day = timezone.localdate()
    form = ApproveForm({"override_reason": payload.override_reason})
    if not form.is_valid():
        return _refused_form(form)
    try:
        request_service.approve(
            req,
            user,
            day,
            override_reason=form.cleaned_data["override_reason"],
            expected_step=payload.step,
        )
    except LeaveError as exc:
        return _refused_error(str(exc))
    return _saved()


@leave_requests_router.post("/{pk}/reject", response=LeaveWriteResultOut, auth=django_auth)
def leave_request_reject(request: HttpRequest, pk: int, payload: LeaveRequestRejectIn) -> dict[str, Any]:
    """Reject the request at the current step. The reason is required; no leave is written."""
    user, req = _acting_request(request, pk)
    form = RejectForm({"reason": payload.reason})
    if not form.is_valid():
        return _refused_form(form)
    try:
        request_service.reject(req, user, form.cleaned_data["reason"], timezone.localdate())
    except LeaveError as exc:
        return _refused_error(str(exc))
    return _saved()


@leave_requests_router.post("", response=LeaveWriteResultOut, auth=django_auth)
def leave_request_create(request: HttpRequest, payload: LeaveRequestFormIn) -> dict[str, Any]:
    """Submit a leave request for the user's own record. The same form and service as the Django request view."""
    user, employee = _requester(request)
    form = RequestForm(_request_form_data(payload))
    if not form.is_valid():
        return _refused_form(form)
    d = form.cleaned_data
    try:
        request_service.submit(
            employee, d["leave_type"], d["start_date"], d["end_date"], d["note"], user, timezone.localdate()
        )
    except LeaveError as exc:
        return _refused_error(str(exc))
    return _saved()
