"""The My page API: GET /api/v1/me, the own-result notice dismissal, the withdrawal of an own waiting request, and the
checklist tick of a task the user owns.

The facts come from employees.services.me_page.me_facts (the same dict the Django page renders). The gates for the
withdrawal and the tick live in leave.services.requests.withdraw_own and checklists.services.lifecycle.tick_for, which
the Django views call too. This module only presents the facts as the API sends them: the badge tone, the status label
suffix and the current-or-upcoming period filter mirror me.html (the Django template keeps its own copy until cutover).
"""

from typing import Any

from accounts.models import User
from checklists.services import lifecycle
from django.http import Http404, HttpRequest
from django.template.defaultfilters import floatformat
from django.utils import timezone
from employees import attention
from employees.access import own_employee
from employees.services.me_page import decided, me_facts
from employees.templatetags.hr import thumb
from leave.models import LeaveRequest, RequestStatus
from leave.services import requests as request_service
from leave.services.records import LeaveError
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from api.errors import ApiError

me_router = Router(tags=["me"])
checklists_router = Router(tags=["checklists"])

_NOT_FOUND = "Хуудас олдсонгүй"


class EmployeeOut(Schema):
    id: int
    full_name: str
    initial: str  # the first letter of the given name, the placeholder when there is no photo
    photo: str  # "" when there is no photo


class JobOut(Schema):
    position: str
    department: str
    manager: str  # "" without a manager


class NoticeOut(Schema):
    key: str
    text: str
    approved: bool


class QueueOut(Schema):
    id: int
    employee: str
    leave_type: str
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    step: str  # "current/count"


class TaskOut(Schema):
    id: int
    title: str
    employee: str
    kind_label: str
    due: str  # YYYY-MM-DD
    overdue: bool
    can_tick: bool


class TeamAwayOut(Schema):
    full_name: str
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD


class HolidayOut(Schema):
    day: str  # YYYY-MM-DD
    name: str


class PeriodOut(Schema):
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    current: bool
    granted: str  # floatformat(x, "-1") as the template shows it
    taken: str
    left: str
    negative: bool  # the balance is below zero


class BalanceOut(Schema):
    start_missing: bool  # no start date, so no leave year can be worked out
    configured: bool  # an annual leave type is set up
    started: bool  # the leave year has at least one period (before the current-or-upcoming filter)
    periods: list[PeriodOut]  # only the current and upcoming periods
    nowhere: int  # counted leaves that no leave period contains


class RequestOut(Schema):
    id: int
    leave_type: str
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    working_days: int
    status: str  # the request's own status key: waiting, approved, rejected, withdrawn
    status_label: str
    tone: str  # "muted" | "approved" | "rejected" | "waiting"
    step: str  # "current/count"
    rule: str  # the rule that picks the approver, while waiting
    reason: str  # the rejection reason, when rejected
    can_withdraw: bool


class RecordedOut(Schema):
    leave_type: str
    start: str  # YYYY-MM-DD
    end: str  # YYYY-MM-DD
    days: str  # floatformat(x, "-1")


class MeOut(Schema):
    employee: EmployeeOut
    job: JobOut | None  # None: no job record on today's date
    notices: list[NoticeOut]
    can_request: bool
    queue: list[QueueOut]
    tasks: list[TaskOut]
    has_team: bool
    team_away: list[TeamAwayOut]  # the whole list; the page shows the first eight and a "+N" line
    holidays: list[HolidayOut]
    balance: BalanceOut
    requests: list[RequestOut]
    recorded: list[RecordedOut]


class NoticeIn(Schema):
    key: str


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _employee_out(employee: Any) -> dict[str, Any]:
    return {
        "id": employee.pk,
        "full_name": employee.full_name,
        "initial": employee.given_name[:1],
        "photo": thumb(employee, 80),
    }


def _job_out(job: Any) -> dict[str, str] | None:
    if job is None:
        return None
    return {
        "position": str(job.position),
        "department": str(job.department),
        "manager": job.manager.full_name if job.manager is not None else "",
    }


_TONE_BY_STATUS = {"approved": "approved", "rejected": "rejected", "waiting": "waiting"}


def _tone(shown: str, status: str) -> str:
    """The badge colour of a request, as me.html picks it: a state shown by the list wins, then the request's status."""
    if shown:
        return "muted"
    return _TONE_BY_STATUS.get(status, "muted")


def _request_out(entry: dict[str, Any]) -> dict[str, Any]:
    req: LeaveRequest = entry["req"]
    shown: str = entry["status"]
    waiting = req.status == RequestStatus.WAITING
    label = (shown or req.get_status_display()) + (f" · шат {req.current_step}/{req.step_count}" if waiting else "")
    return {
        "id": req.pk,
        "leave_type": str(req.leave_type),
        "start": req.start_date.isoformat(),
        "end": req.end_date.isoformat(),
        "working_days": req.working_days,
        "status": req.status,
        "status_label": label,
        "tone": _tone(shown, req.status),
        "step": f"{req.current_step}/{req.step_count}",
        "rule": entry["show_rule"],
        "reason": entry["show_reason"],
        "can_withdraw": entry["can_withdraw"],
    }


def _balance_out(facts: dict[str, Any]) -> dict[str, Any]:
    """The balance as the page shows it: the current and upcoming periods, with floatformat amounts."""
    return {
        "start_missing": facts["start_missing"],
        "configured": facts["leave_configured"],
        "started": bool(facts["periods"]),
        "periods": [
            {
                "start": p.start.isoformat(),
                "end": p.end.isoformat(),
                "current": p.current,
                "granted": str(floatformat(p.granted, "-1")),
                "taken": str(floatformat(p.taken, "-1")),
                "left": str(floatformat(p.left, "-1")),
                "negative": p.left < 0,
            }
            for p in facts["periods"]
            if p.current or p.upcoming
        ],
        "nowhere": len(facts["leave_nowhere"]),
    }


@me_router.get("", auth=django_auth, response=MeOut)
def me(request: HttpRequest) -> dict[str, Any]:
    """The My page of the signed-in user (its own record only; 404 without an employee record)."""
    user = _user(request)
    employee = own_employee(user)
    if employee is None:  # a login without an employee record has no My page
        raise HttpError(404, _NOT_FOUND)
    facts = me_facts(user, employee, timezone.localdate())
    return {
        "employee": _employee_out(facts["employee"]),
        "job": _job_out(facts["job"]),
        "notices": [{"key": n.item.key, "text": n.item.text, "approved": n.approved} for n in facts["notices"]],
        "can_request": facts["can_request"],
        "queue": [
            {
                "id": q["req"].pk,
                "employee": q["req"].employee.full_name,
                "leave_type": str(q["req"].leave_type),
                "start": q["req"].start_date.isoformat(),
                "end": q["req"].end_date.isoformat(),
                "step": q["step"],
            }
            for q in facts["queue"]
        ],
        "tasks": [
            {
                "id": t["task"].pk,
                "title": t["task"].title,
                "employee": t["task"].checklist.employee.full_name,
                "kind_label": t["task"].checklist.get_kind_display(),
                "due": t["task"].due_on.isoformat(),
                "overdue": t["overdue"],
                "can_tick": t["can_tick"],
            }
            for t in facts["tasks"]
        ],
        "has_team": facts["has_team"],
        "team_away": [
            {"full_name": a["employee"].full_name, "start": a["start"].isoformat(), "end": a["end"].isoformat()}
            for a in facts["team_away"]
        ],
        "holidays": [{"day": d.isoformat(), "name": name} for d, name in facts["holidays"]],
        "balance": _balance_out(facts),
        "requests": [_request_out(q) for q in facts["requests"]],
        "recorded": [
            {
                "leave_type": str(lv.leave_type),
                "start": lv.start.isoformat(),
                "end": lv.end.isoformat(),
                "days": str(floatformat(lv.days, "-1")),
            }
            for lv in facts["recorded"]
        ],
    }


@me_router.post("/notice", auth=django_auth, response={204: None})
def dismiss_notice(request: HttpRequest, payload: NoticeIn) -> tuple[int, None]:
    """«Мэдлээ» on one result notice. Only a notice of the user's own request can be dismissed (404 otherwise)."""
    user = _user(request)
    employee = own_employee(user)
    if employee is None:
        raise HttpError(404, _NOT_FOUND)
    found = next((n for n in decided(employee) if n.item.key == payload.key), None)
    if found is None:
        raise HttpError(404, _NOT_FOUND)
    attention.dismiss(user, found.item)
    return 204, None


@me_router.post("/requests/{pk}/withdraw", auth=django_auth, response={204: None})
def withdraw_request(request: HttpRequest, pk: int) -> tuple[int, None]:
    """«Буцаах»: the user takes back their own waiting request. Someone else's request is 404; a refused change 409."""
    user = _user(request)
    try:
        request_service.withdraw_own(user, pk, timezone.localdate())
    except Http404:
        raise HttpError(404, _NOT_FOUND) from None
    except LeaveError as error:
        raise ApiError(409, [str(error)]) from error
    return 204, None


@checklists_router.post("/tasks/{pk}/tick", auth=django_auth, response={204: None})
def tick_task(request: HttpRequest, pk: int) -> tuple[int, None]:
    """«Хийгдсэн» on a checklist task the user owns (404 when the user may not tick it, 409 when it is refused)."""
    user = _user(request)
    try:
        lifecycle.tick_for(user, pk, timezone.localdate())
    except Http404:
        raise HttpError(404, _NOT_FOUND) from None
    except lifecycle.ChecklistError as error:
        raise ApiError(409, [error.message]) from error
    return 204, None
