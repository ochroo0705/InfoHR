"""The My page («Миний хуудас») rules, shared by the Django page (employees.views_me) and the API (api.me).

`me_facts` composes everything the page shows for one user on one day: the own result notices, the approver's queue,
the open checklist tasks (with the tick gate), the own requests (with the state the list shows), the leave balance,
the team strip and the holidays. Each caller only presents the dict: the Django template prints it, the API
serialises it. Only the user's own record is read here, so no view right is needed (spec 5.7).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from accounts.models import User
from django.utils import timezone
from leave.models import LeaveRequest, RequestStatus
from leave.services import ledger, rows
from leave.services.approvers import (
    approval_enabled,
    approvers_many,
    may_decide,
    requests_active,
    waiting_for_cached,
)

from employees import attention
from employees import today as facts
from employees.models import Employee
from employees.scope import team_ids
from employees.services import history

NOTICE_KIND = "leave_request_result"
NOTICE_SCAN = 20  # decided requests read per page; dismissed ones are skipped from this window
NOTICE_SHOWN = 5  # notices shown at once
NOTICE_DAYS = 90  # a decision older than this no longer raises a notice
RECENT_LIMIT = 20  # own requests listed on the page, newest first
TEAM_DAYS = 14  # the team strip: from the day shown, this many days


@dataclass
class Notice:
    """One result notice: the dismissable item (text and key) and the decision it reports."""

    item: attention.Attention
    approved: bool


def _notice(employee: Employee, req: LeaveRequest) -> Notice:
    """One result line for an own request. The kind carries the request id, so two notices never share a key."""
    span = f"{req.leave_type} {req.start_date:%Y-%m-%d}–{req.end_date:%Y-%m-%d}"
    approved = req.status == RequestStatus.APPROVED
    if approved:
        text = f"Чөлөөний хүсэлт батлагдсан: {span}"
    else:
        text = f"Чөлөөний хүсэлт татгалзсан: {span}. Шалтгаан: {req.reason}"
    return Notice(attention.Attention(employee, text, f"{NOTICE_KIND}:{req.pk}"), approved)


def decided(employee: Employee) -> list[Notice]:
    """Own requests approved or rejected in the last NOTICE_DAYS days, newest first, dismissed or not."""
    since = timezone.now() - timedelta(days=NOTICE_DAYS)
    found = (
        LeaveRequest.objects.filter(
            employee=employee, status__in=[RequestStatus.APPROVED, RequestStatus.REJECTED], updated_at__gte=since
        )
        .select_related("leave_type")
        .order_by("-updated_at", "-pk")[:NOTICE_SCAN]
    )
    return [_notice(employee, req) for req in found]


def own_notices(user: User, employee: Employee) -> list[Notice]:
    """The result notices the user has not dismissed yet (D-013: a dismissal is kept per user and per text)."""
    found = decided(employee)
    shown, _ = attention.split(user, [n.item for n in found])
    keys = {a.key for a in shown}
    return [n for n in found if n.item.key in keys][:NOTICE_SHOWN]


def waiting_queue(user: User, day: date) -> list[dict[str, Any]]:
    """Requests waiting for this user's decision (approver view). Shown while approval is on or requests still wait
    (spec 5.1), and only worked out for a user who could decide something (may_decide is the cheap test)."""
    if not requests_active(user) or not may_decide(user, day):
        return []
    return [{"req": req, "step": f"{req.current_step}/{req.step_count}"} for req in waiting_for_cached(user, day)]


def my_tasks(user: User, day: date) -> list[dict[str, Any]]:
    """Open checklist tasks (onboarding and offboarding) the user owns, earliest first, each with its overdue flag and
    whether the user may tick it. `may_have_tasks` is the cheap test: a user who owns no task pays nothing more. The
    owners are worked out once and shared by the list and the tick gate."""
    from checklists.services import owners  # local import: checklists depends on employees, not the reverse

    if not owners.may_have_tasks(user, day):
        return []
    owned = owners.my_tasks_owned(user, day)
    tasks = [task for task, _owners in owned]
    ticks = owners.can_tick_many(user, tasks, {task.pk: o for task, o in owned}, day)
    return [{"task": task, "overdue": task.due_on < day, "can_tick": ticks.get(task.pk, False)} for task in tasks]


def own_requests(employee: Employee, day: date) -> list[dict[str, Any]]:
    """The most recent own requests with their state (a cancelled or mistaken leave shows that) and, while waiting, the
    rule that picks the approver."""
    reqs = list(
        LeaveRequest.objects.filter(employee=employee)
        .select_related("leave_type")
        .order_by("-created_at", "-pk")[:RECENT_LIMIT]
    )
    waiting = [r for r in reqs if r.status == RequestStatus.WAITING]
    rules = approvers_many(waiting, day) if waiting else {}
    shown = rows.leave_status(reqs)  # «Цуцалсан» / «Буруу бүртгэсэн» as the requests list shows it
    out: list[dict[str, Any]] = []
    for r in reqs:
        waiting = r.status == RequestStatus.WAITING
        rule = rules[r.pk].rule.label if r.pk in rules else ""
        out.append(
            {
                "req": r,
                "rule": rule,  # the raw rule (the Django template gates it on the status itself)
                "status": shown.get(r.pk, ""),
                "can_withdraw": waiting,
                "show_rule": rule if waiting else "",  # the approver rule is shown only while waiting
                "show_reason": r.reason if r.status == RequestStatus.REJECTED else "",  # only when rejected
            }
        )
    return out


def team_away(employee: Employee, day: date, team: set[int]) -> list[dict[str, Any]]:
    """People in `team` (the manager's direct and indirect reports, from scope.team_ids) with a counting leave inside
    [day, day + TEAM_DAYS). One entry per person: the earliest start and the latest end of their leaves in the window.
    Names and dates only: the leave type is not shown to a manager. Sorted by start; empty without a team."""
    if not team:
        return []
    last = day + timedelta(days=TEAM_DAYS - 1)  # [day, day + TEAM_DAYS): rows.leaves takes an inclusive end
    leaves = [lv for lv in rows.leaves(employee_ids=team, start=day, end=last) if lv.counts]
    if not leaves:
        return []
    people = Employee.objects.in_bulk(list({lv.employee_id for lv in leaves}))
    spans: dict[int, dict[str, Any]] = {}
    for lv in leaves:
        if lv.employee_id not in people:
            continue
        span = spans.setdefault(lv.employee_id, {"employee": people[lv.employee_id], "start": lv.start, "end": lv.end})
        span["start"] = min(span["start"], lv.start)
        span["end"] = max(span["end"], lv.end)
    return sorted(spans.values(), key=lambda a: (a["start"], a["employee"].pk))


def me_facts(user: User, employee: Employee, day: date) -> dict[str, Any]:
    """Everything the My page shows for `user` (whose own record is `employee`) on `day`, composed once. The keys are
    the context of the Django page; `periods` is unfiltered (the presentation picks the current and upcoming ones),
    and `tasks` carry `can_tick`."""
    from leave.templatetags.leave_tags import leave_start_missing  # local import: the tag module loads the leave app

    periods, nowhere = ledger.periods(employee, day)
    year_start, year_end = date(day.year, 1, 1), date(day.year, 12, 31)
    recorded = sorted(
        (lv for lv in rows.leaves(employee_ids=[employee.pk], start=year_start, end=year_end) if lv.counts),
        key=lambda lv: lv.start,
        reverse=True,
    )
    team = team_ids(employee.pk, day)  # once per request: the team strip and its line use it
    return {
        "employee": employee,
        "job": history.job_on(employee, day),
        "today": day,
        "notices": own_notices(user, employee),
        "can_request": approval_enabled(user) and user.has_perm("leave.request_own_leave"),
        "periods": periods,
        "leave_nowhere": nowhere,
        "leave_configured": ledger.annual_configured(),
        "start_missing": leave_start_missing(employee),
        "recorded": recorded,
        "requests": own_requests(employee, day),
        "queue": waiting_queue(user, day),
        "tasks": my_tasks(user, day),
        "has_team": bool(team),
        "team_away": team_away(employee, day, team),
        "holidays": facts.holidays_ahead(day),
    }
