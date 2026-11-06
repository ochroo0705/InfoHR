"""Approver side of leave requests (spec 5.6, 5.7): the requests list, the detail pop-up, approve and reject.

The list shows what the user decides («Надад ирсэн», `waiting_for`) and, with `leave.view_leave`, every request
they may see («Бүгд»). The pop-up shows one request only: the person's post and balance, and who else in the same
department is on leave or waiting for the same days. No salary, register number or other personal data.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from accounts.models import User
from config import batching
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, Max, OuterRef, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from employees import history_range
from employees.access import own_employee
from employees.models import Employee, JobRecord
from employees.scope import restriction
from employees.services import history
from macs.models import LeaveAssign

from leave import access
from leave.forms import ApproveForm, RejectForm, RequestForm
from leave.models import ActionKind, LeaveExt, LeaveRequest, LeaveRequestAction, RequestStatus, type_ext
from leave.services import ledger, rows
from leave.services import requests as request_service
from leave.services.approvers import (
    approval_enabled,
    approvers,
    approvers_many,
    can_act,
    visible_requests,
    waiting_for,
)
from leave.services.records import LeaveError
from leave.views import _done, _require, _user, today

# Status filters of the «Бүгд» list: the request's own statuses, then two views of an approved request whose leave
# HR cancelled. They split as the row shows them (rows.leave_status): «Буруу бүртгэсэн» is a cancelled leave with
# `LeaveExt.mistake`, «Цуцалсан» the other cancelled ones. Values do not clash with RequestStatus.
LEAVE_CANCELLED = "cancelled"
LEAVE_MISTAKE = "mistake"
STATUS_FILTERS = [*RequestStatus.choices, (LEAVE_CANCELLED, "Цуцалсан"), (LEAVE_MISTAKE, "Буруу бүртгэсэн")]


@dataclass
class Row:
    """One line of the requests list: the request, the rule that picks its approver and, while it waits, since when."""

    req: LeaveRequest
    rule: str
    since: datetime | None = None
    status: str = ""  # shown instead of the request's own status when its leave was cancelled or marked a mistake


def _rows(reqs: list[LeaveRequest], day: date) -> list[Row]:
    """Rows for one page. Rules and waiting-since dates are resolved once per page, for the waiting requests only."""
    waiting = [r for r in reqs if r.status == RequestStatus.WAITING]
    rules = approvers_many(waiting, day) if waiting else {}
    since = _waiting_since(waiting)
    leave_status = rows.leave_status(reqs)
    return [
        Row(r, rules[r.pk].rule.label if r.pk in rules else "", since.get(r.pk), leave_status.get(r.pk, ""))
        for r in reqs
    ]


def _waiting_since(waiting: list[LeaveRequest]) -> dict[int, datetime]:
    """When each waiting request reached its current step: the approval of the step before it, or the submission
    for step 1. One query for the whole page, and none when every request is on step 1."""
    since = {r.pk: r.created_at for r in waiting}
    later = [r for r in waiting if r.current_step > 1]
    if later:
        approved = (
            LeaveRequestAction.objects.filter(request_id__in=[r.pk for r in later], action=ActionKind.APPROVED)
            .values("request_id", "step")
            .annotate(last=Max("at"))
        )
        last = {(a["request_id"], a["step"]): a["last"] for a in approved}
        for r in later:
            since[r.pk] = last.get((r.pk, r.current_step - 1), r.created_at)
    return since


def _cancelled_leave() -> QuerySet[LeaveAssign]:
    return LeaveAssign.objects.filter(pk=OuterRef("assign_id"), status=LeaveAssign.CANCELLED)


def _mistake_leave() -> QuerySet[LeaveExt]:
    return LeaveExt.objects.filter(pk=OuterRef("assign_id"), mistake=True)


def _by_status(qs: QuerySet[LeaveRequest], status: str) -> QuerySet[LeaveRequest]:
    """Filter the list by a status value of STATUS_FILTERS, in SQL (the list is paged). A request with no linked
    leave (`assign_id` empty) counts as not cancelled."""
    approved = qs.filter(status=RequestStatus.APPROVED)
    if status == RequestStatus.APPROVED:
        return approved.filter(~Exists(_cancelled_leave()))
    if status == LEAVE_MISTAKE:
        return approved.filter(Exists(_cancelled_leave()), Exists(_mistake_leave()))
    if status == LEAVE_CANCELLED:
        return approved.filter(Exists(_cancelled_leave()), ~Exists(_mistake_leave()))
    return qs.filter(status=status)


def _visible_request(user: User, pk: int, day: date) -> tuple[LeaveRequest, bool, bool]:
    """(request, may act, is override). 404 unless the user may act on it or may see the person's leave."""
    req = get_object_or_404(LeaveRequest.objects.select_related("employee", "leave_type"), pk=pk)
    may, override = can_act(user, req, day)
    if may:
        return req, may, override
    if access.can_view(user) and visible_requests(user).filter(pk=req.pk).exists():
        return req, False, False
    raise Http404


@login_required
def requests_list(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    day = today()
    tab = "all" if request.GET.get("tab") == "all" else "mine"
    status = ""
    if tab == "all":
        _require(access.can_view(user))
        status = request.GET.get("status", "")
        if status not in {value for value, _ in STATUS_FILTERS}:
            status = ""
        qs = visible_requests(user).select_related("employee", "leave_type").order_by("-created_at", "-pk")
        if status:
            qs = _by_status(qs, status)

        def fetch_all(offset: int, size: int) -> tuple[list[LeaveRequest], bool]:
            page = list(qs[offset : offset + size + 1])
            return page[:size], len(page) > size

        batch = batching.paged(request, fetch_all)
    else:
        queue = waiting_for(user, day)

        def fetch_mine(offset: int, size: int) -> tuple[list[LeaveRequest], bool]:
            return queue[offset : offset + size], offset + size < len(queue)

        batch = batching.paged(request, fetch_mine)
    context = {
        "items": _rows(batch.shown, day),
        "offset": batch.offset,
        "next_query": batch.next_query,
        "tab": tab,
        "status": status,
        "statuses": STATUS_FILTERS,
        "can_all": access.can_view(user),
        "filters": request.GET,
    }
    template = "leave/_request_rows.html" if request.headers.get("HX-Request") else "leave/requests.html"
    return render(request, template, context)


@dataclass
class Other:
    """Someone else in the same department on leave, or waiting, for days that overlap the request."""

    name: str
    start: date
    end: date
    state: str


@dataclass
class Balance:
    balance_after: int | None
    warnings: list[str] = field(default_factory=list)
    needs_override: bool = False


def _balance(req: LeaveRequest, day: date) -> Balance:
    """Balance left after the request's days, read without writing anything: a GET must not create grants.

    Only the annual balance is counted. Approve still runs records.check (which may write grants and refuses a
    negative balance without a reason), so an unusual case is caught there, not here.
    """
    if not type_ext(req.leave_type).uses_annual_balance:
        return Balance(None)
    found, _ = ledger.periods(req.employee, day)
    period = next((p for p in found if p.start <= req.start_date <= p.end), None)
    if period is None:  # same as records.check: no period means nothing is available, so the reason is asked
        after = -req.working_days
        return Balance(after, [f"Энэ огноонд амралтын эрх олдсонгүй ({ledger.NO_PERIOD_LABEL})."], needs_override=True)
    after = period.left - req.working_days
    return Balance(after, needs_override=after < 0)


def _others(user: User, req: LeaveRequest, day: date) -> list[Other]:
    """Names and dates only, for people in the requester's department that the user's data scope covers."""
    job = history.job_on(req.employee, day)
    if job is None:
        return []
    same_department = (
        JobRecord.objects.filter(history_range.on(day), department_id=job.department_id)
        .exclude(employee_id=req.employee_id)
        .values("employee_id")
    )
    peers = Employee.objects.filter(pk__in=same_department)
    limit = restriction(user, day)
    if limit is not None:
        peers = peers.filter(limit)
    people = {e.pk: e for e in peers}
    if not people:
        return []
    found = [
        Other(people[lv.employee_id].full_name, lv.start, lv.end, "Чөлөөтэй")
        for lv in rows.leaves(employee_ids=list(people), start=req.start_date, end=req.end_date)
        if lv.counts and lv.employee_id in people
    ]
    found += [
        Other(people[w.employee_id].full_name, w.start_date, w.end_date, "Хүлээгдэж буй")
        for w in LeaveRequest.objects.filter(
            employee_id__in=list(people),
            status=RequestStatus.WAITING,
            start_date__lte=req.end_date,
            end_date__gte=req.start_date,
        ).exclude(pk=req.pk)
    ]
    return sorted(found, key=lambda o: o.start)


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
    waiting = req.status == RequestStatus.WAITING
    job = history.job_on(req.employee, day)
    balance = _balance(req, day) if waiting else None
    if form is None:
        form = ApproveForm()
    context = {
        "req": req,
        "employee": req.employee,
        "job": job,
        "waiting": waiting,
        "status_label": rows.leave_status([req]).get(req.pk) or req.get_status_display(),
        "rule": approvers(req, day).rule.label if waiting else "",
        "may": may,
        "override": override,
        "balance": balance,
        "past": req.start_date < day,
        "others": _others(user, req, day),
        "history": req.actions.select_related("by").order_by("pk"),
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
    employee = own_employee(user)
    if employee is None:
        raise Http404
    req = get_object_or_404(LeaveRequest, pk=pk, employee_id=employee.pk)
    try:
        request_service.withdraw(req, user, today())
    except LeaveError as e:
        return HttpResponse(format_html('<p class="text-sm text-red-700">{}</p>', str(e)))
    return _done()
