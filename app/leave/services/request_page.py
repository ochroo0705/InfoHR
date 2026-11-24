"""The requests list's rules: how the query string becomes a filter, which rows a batch holds, and the status filters.

The «Надад ирсэн» queue (`mine`) and the «Бүгд» list (`all`) both come from here. Rules only; drawing is the caller's
job, and so is the rights check for «Бүгд».
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from accounts.models import User
from django.db.models import Exists, Max, OuterRef, QuerySet
from django.http import Http404
from django.shortcuts import get_object_or_404
from employees import history_range
from employees.models import Employee, JobRecord
from employees.scope import restriction
from employees.services import history
from macs.models import LeaveAssign

from leave import access
from leave.models import (
    ActionKind,
    LeaveExt,
    LeaveRequest,
    LeaveRequestAction,
    RequestStatus,
    type_ext,
)
from leave.services import ledger, rows
from leave.services.approvers import approvers, approvers_many, can_act, visible_requests, waiting_for

# Status filters of the «Бүгд» list: the request's own statuses, then two views of an approved request whose leave
# HR cancelled. They split as the row shows them (rows.leave_status): «Буруу бүртгэсэн» is a cancelled leave with
# `LeaveExt.mistake`, «Цуцалсан» the other cancelled ones. Values do not clash with RequestStatus.
LEAVE_CANCELLED = "cancelled"
LEAVE_MISTAKE = "mistake"
STATUS_FILTERS = [*RequestStatus.choices, (LEAVE_CANCELLED, "Цуцалсан"), (LEAVE_MISTAKE, "Буруу бүртгэсэн")]


@dataclass(frozen=True)
class RequestFilter:
    tab: Literal["mine", "all"]  # «Надад ирсэн» (the user's own queue) or «Бүгд» (every visible request)
    status: str  # a STATUS_FILTERS value on «Бүгд», «» otherwise


def parse_filter(query: Mapping[str, str]) -> RequestFilter:
    """The filter the query string asks for. Any tab other than `all` is `mine`; an unknown status is dropped, and a
    status is only kept on `all`. No rights check here: the view refuses `all` without `leave.view_leave`."""
    if query.get("tab") != "all":
        return RequestFilter(tab="mine", status="")
    status = query.get("status", "")
    if status not in {value for value, _ in STATUS_FILTERS}:
        status = ""
    return RequestFilter(tab="all", status=status)


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


def list_batch(user: User, flt: RequestFilter, offset: int, size: int, day: date) -> tuple[list[Row], bool]:
    """One batch of the list as rows, and whether more rows follow it. `mine` slices the user's queue (oldest first);
    `all` pages the visible requests (newest first) with the status filter in SQL."""
    if flt.tab == "mine":
        queue = waiting_for(user, day)
        return _rows(queue[offset : offset + size], day), offset + size < len(queue)
    qs = visible_requests(user).select_related("employee", "leave_type").order_by("-created_at", "-pk")
    if flt.status:
        qs = _by_status(qs, flt.status)
    page = list(qs[offset : offset + size + 1])
    return _rows(page[:size], day), len(page) > size


# --- The detail pop-up: one request, its person's balance, who else is off, and its history.


def visible_request(
    user: User, pk: int, day: date, decide: Callable[[User, LeaveRequest, date], tuple[bool, bool]] = can_act
) -> tuple[LeaveRequest, bool, bool]:
    """(request, may act, is override). 404 unless the user may act on it or may see the person's leave.
    `decide` gives (may act, is override); the Django view passes its own `can_act` so a test can replace it."""
    req = get_object_or_404(LeaveRequest.objects.select_related("employee", "leave_type"), pk=pk)
    may, override = decide(user, req, day)
    if may:
        return req, may, override
    if access.can_view(user) and visible_requests(user).filter(pk=req.pk).exists():
        return req, False, False
    raise Http404


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


def balance_of(req: LeaveRequest, day: date) -> Balance:
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


def others_of(user: User, req: LeaveRequest, day: date) -> list[Other]:
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


@dataclass
class RequestDetail:
    """What the detail pop-up shows about one request. Drawing and the decision forms are the caller's job."""

    job: JobRecord | None  # the person's job on the day
    waiting: bool
    status_label: str  # the leave's state when HR cancelled it, else the request's own status
    rule: str  # which rule picks the approvers; «» once decided
    balance: Balance | None  # None unless the request is waiting
    past: bool  # the leave starts before the day
    others: list[Other]
    history: list[LeaveRequestAction]


def detail_for(user: User, req: LeaveRequest, day: date) -> RequestDetail:
    waiting = req.status == RequestStatus.WAITING
    return RequestDetail(
        job=history.job_on(req.employee, day),
        waiting=waiting,
        status_label=rows.leave_status([req]).get(req.pk) or req.get_status_display(),
        rule=approvers(req, day).rule.label if waiting else "",
        balance=balance_of(req, day) if waiting else None,
        past=req.start_date < day,
        others=others_of(user, req, day),
        history=list(req.actions.select_related("by").order_by("pk")),
    )
