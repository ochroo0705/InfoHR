"""Who may act on a leave request at its current step (spec 5.2).

Nothing about the approver is stored. Each call works it out again from the current role members, the employee's
manager in the job row in force today, and the data scope. A manager who leaves hands the request on automatically,
and an empty step falls back to people with `accounts.approve_leave`, then to Admin users, so no request is stuck.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import date
from enum import StrEnum
from typing import Any, NamedTuple, cast

from accounts import roles
from accounts.models import AccessScope, User
from django.db.models import Q, QuerySet
from employees import history_range
from employees.access import visible_employees
from employees.models import Employee, EmployeeExt, JobRecord
from employees.scope import restriction

from leave.models import LeaveRequest, LeaveSettings, RequestStatus, Step

APPROVE_APP = "accounts"
APPROVE_CODENAME = "approve_leave"
APPROVE_PERM = f"{APPROVE_APP}.{APPROVE_CODENAME}"


class Rule(StrEnum):
    """Which rule chose the approvers of a step (shown on the screen)."""

    ROLE = "role"
    MANAGER = "manager"
    FALLBACK = "fallback"
    ADMIN = "admin"

    @property
    def label(self) -> str:
        return _RULE_LABELS[self]


_RULE_LABELS: dict[Rule, str] = {
    Rule.ROLE: "Рольоор",
    Rule.MANAGER: "Шууд удирдлага",
    Rule.FALLBACK: "Батлах эрхтэй",
    Rule.ADMIN: "Админ",
}


class Approvers(NamedTuple):
    rule: Rule
    user_ids: frozenset[int]


class _Context(NamedTuple):
    """Everything one resolution needs, loaded once for all requests in the batch."""

    linked: dict[int, int]  # employee id -> that employee's login
    managers: dict[int, int | None]  # employee id -> login of the manager today
    members: dict[int, set[int]]  # group id -> active member logins
    admitted: dict[int, set[int] | None]  # login -> employees it may see (None = no limit)
    holders: set[int]  # active logins with accounts.approve_leave (superusers included)
    admins: set[int]  # active Admin members and superusers


def manager_user_ids(employee_ids: Iterable[int], day: date) -> dict[int, int | None]:
    """Employee -> login of their direct manager in the job row in force on `day`.

    None when there is no job row, no manager, the manager has no login, or the login is inactive.
    Two queries at most, whatever the number of employees.
    """
    ids = set(employee_ids)
    if not ids:
        return {}
    manager_of: dict[int, int | None] = dict(
        JobRecord.objects.filter(history_range.on(day), employee_id__in=ids).values_list("employee_id", "manager_id")
    )
    managers = {manager for manager in manager_of.values() if manager is not None}
    login_of: dict[int, int] = {}
    if managers:
        login_of = dict(
            EmployeeExt.objects.filter(
                employee_id__in=managers, user_id__isnull=False, user__is_active=True
            ).values_list("employee_id", "user_id")
        )
    result: dict[int, int | None] = {}
    for employee_id in ids:
        manager = manager_of.get(employee_id)
        result[employee_id] = login_of.get(manager) if manager is not None else None
    return result


def approvers(req: LeaveRequest, day: date) -> Approvers:
    """Who may act on the current step of `req` on `day`."""
    return _resolve([req], day)[req.pk]


def approvers_many(reqs: list[LeaveRequest], day: date) -> dict[int, Approvers]:
    """`approvers` for many requests at once (a list page): the query count does not grow with the list."""
    return _resolve(reqs, day)


def can_act(user: User, req: LeaveRequest, day: date) -> tuple[bool, bool]:
    """(may act, is override). Only waiting requests can be acted on; the requester never can."""
    if not user.is_active or req.status != RequestStatus.WAITING:
        return (False, False)
    if user.pk in _banned(req, _requester_map([req])):
        return (False, False)
    if user.pk in approvers(req, day).user_ids:
        return (True, False)
    if user.has_perm(APPROVE_PERM) and _admits(user, req.employee_id, day):
        return (True, True)
    return (False, False)


def waiting_for(user: User, day: date) -> list[LeaveRequest]:
    """Waiting requests `user` may act on at their current step (overrides not included).

    Runs a fixed number of queries whatever the number of requests: see `_resolve`.
    """
    if not user.is_active:
        return []
    reqs = list(
        LeaveRequest.objects.filter(status=RequestStatus.WAITING)
        .select_related("employee", "leave_type")
        .order_by("created_at", "pk")
    )
    resolved = _resolve(reqs, day)
    return [req for req in reqs if user.pk in resolved[req.pk].user_ids]


def _per_user[T](user: User | None, key: str, compute: Callable[[], T]) -> T:
    """`compute()` once per user object (kept in its __dict__, like the data-scope cache), so the nav link, the Today
    item and My page of one HTTP request share the answer. Without a user, nothing is kept."""
    if user is None:
        return compute()
    cache: dict[str, Any] = user.__dict__.setdefault("_leave_flags", {})
    if key not in cache:
        cache[key] = compute()
    return cast(T, cache[key])


def approval_enabled(user: User | None = None) -> bool:
    """Whether approval is switched on. A read only: a missing settings row counts as off and none is created."""

    def read() -> bool:
        row = LeaveSettings.objects.filter(pk=1).first()
        return row is not None and row.approval_on

    return _per_user(user, "approval_enabled", read)


def requests_active(user: User | None = None) -> bool:
    """Whether the request screens have anything to show: approval is on, or requests are still waiting.

    A settings change does not touch waiting requests (spec 5.1), so they stay approvable after approval is off.
    """
    return _per_user(
        user,
        "requests_active",
        lambda: approval_enabled(user) or LeaveRequest.objects.filter(status=RequestStatus.WAITING).exists(),
    )


def waiting_for_cached(user: User, day: date) -> list[LeaveRequest]:
    """`waiting_for`, worked out once per user object and day, so the nav link, the Today item and My page of one
    HTTP request share it (the cache lives in the user's __dict__, like the data-scope cache)."""
    cache: dict[date, list[LeaveRequest]] = user.__dict__.setdefault("_waiting_for_cache", {})
    if day not in cache:
        cache[day] = waiting_for(user, day)
    return cache[day]


def may_decide(user: User, day: date) -> bool:
    """A cheap test, before the queue is worked out, that the user could approve some waiting request.

    It must never say no to someone `waiting_for` would return: each route into it is checked here. A step group the
    user is in, the line manager of someone, the approve right, or the Admin group (fallback and admin steps).
    Worked out once per user object and day (`_per_user`).
    """
    return _per_user(user, f"may_decide:{day.isoformat()}", lambda: _may_decide(user, day))


def _may_decide(user: User, day: date) -> bool:
    if user.is_superuser or user.has_perm(APPROVE_PERM) or user.groups.filter(name=roles.ADMIN).exists():
        return True
    groups = user.groups.values("pk")
    if (
        LeaveRequest.objects.filter(status=RequestStatus.WAITING)
        .filter(Q(step1_group__in=groups) | Q(step2_group__in=groups))
        .exists()
    ):
        return True
    linked = EmployeeExt.objects.filter(user=user).values("employee_id")
    return JobRecord.objects.filter(history_range.on(day), manager__in=linked).exists()


def visible_requests(user: User) -> QuerySet[LeaveRequest]:
    """Every request for an employee `user` can see. Needs `leave.view_leave`; otherwise nothing."""
    if not user.is_active or not user.has_perm("leave.view_leave"):
        return LeaveRequest.objects.none()
    return LeaveRequest.objects.filter(employee_id__in=visible_employees(user).values("pk"))


def _resolve(reqs: list[LeaveRequest], day: date) -> dict[int, Approvers]:
    """Approvers of each request's current step. Query count depends on the number of distinct groups, managers
    and candidate users, never on the number of requests."""
    if not reqs:
        return {}
    steps = {req.pk: req.step(req.current_step) for req in reqs}
    employee_ids = {req.employee_id for req in reqs}
    manager_employees = {req.employee_id for req in reqs if _is_manager_step(steps[req.pk])}
    group_ids = {step.group_id for step in steps.values() if step.group_id is not None}

    members: dict[int, set[int]] = {}
    if group_ids:
        rows = User.groups.through.objects.filter(group_id__in=group_ids, user__is_active=True).values_list(
            "group_id", "user_id"
        )
        for group_id, user_id in rows:
            members.setdefault(group_id, set()).add(user_id)

    holders = set(_holders().values_list("pk", flat=True))
    admins = set(_admins().values_list("pk", flat=True))
    candidates = holders.union(*members.values())
    ctx = _Context(
        linked=_requester_map(reqs),
        managers=manager_user_ids(manager_employees, day),
        members=members,
        admitted=_admitted(candidates, admins, employee_ids, day),
        holders=holders,
        admins=admins,
    )
    return {req.pk: _decide(req, ctx) for req in reqs}


def _decide(req: LeaveRequest, ctx: _Context) -> Approvers:
    banned = _banned(req, ctx.linked)
    step = req.step(req.current_step)
    if step.group_id is not None:
        role_ids = {uid for uid in ctx.members.get(step.group_id, set()) if _sees(ctx, uid, req.employee_id)}
        role_ids -= banned
        if role_ids:
            return Approvers(Rule.ROLE, frozenset(role_ids))
    elif step.manager:
        manager = ctx.managers.get(req.employee_id)
        if manager is not None and manager not in banned:
            return Approvers(Rule.MANAGER, frozenset({manager}))
    fallback = {uid for uid in ctx.holders if _sees(ctx, uid, req.employee_id)} - banned
    if fallback:
        return Approvers(Rule.FALLBACK, frozenset(fallback))
    return Approvers(Rule.ADMIN, frozenset(ctx.admins - banned))


def _is_manager_step(step: Step) -> bool:
    """A step with a role uses the role; a step with only the manager flag uses the manager."""
    return step.group_id is None and step.manager


def _sees(ctx: _Context, user_id: int, employee_id: int) -> bool:
    if user_id not in ctx.admitted:
        return False
    allowed = ctx.admitted[user_id]
    return allowed is None or employee_id in allowed


def _banned(req: LeaveRequest, linked: Mapping[int, int]) -> set[int]:
    """Logins that may never approve this request: the employee's own login and the creator."""
    banned: set[int] = set()
    login = linked.get(req.employee_id)
    if login is not None:
        banned.add(login)
    if req.created_by_id is not None:
        banned.add(req.created_by_id)
    return banned


def _requester_map(reqs: list[LeaveRequest]) -> dict[int, int]:
    """Employee id -> login linked to that employee. One query."""
    return dict(
        EmployeeExt.objects.filter(
            employee_id__in={req.employee_id for req in reqs}, user_id__isnull=False
        ).values_list("employee_id", "user_id")
    )


def _admitted(user_ids: set[int], admins: set[int], employee_ids: set[int], day: date) -> dict[int, set[int] | None]:
    """Login -> the given employees it may see on `day` (None = no data-scope limit).

    One query finds which candidates have a limited AccessScope row; the rest, and every Admin or superuser, are
    unlimited without any further query. `restriction` runs only for the really limited users (a few queries each:
    it reads its own scope row, the Admin group, and the departments or team it lists).
    """
    limited_ids = set(AccessScope.objects.filter(user_id__in=user_ids, limited=True).values_list("user_id", flat=True))
    limited_ids -= admins
    result: dict[int, set[int] | None] = {uid: None for uid in user_ids if uid not in limited_ids}
    for user_id, user in User.objects.in_bulk(list(limited_ids)).items():
        limit = restriction(user, day)
        if limit is None:
            result[user_id] = None
        else:
            result[user_id] = set(Employee.objects.filter(limit, pk__in=employee_ids).values_list("pk", flat=True))
    return result


def _admits(user: User, employee_id: int, day: date) -> bool:
    limit = restriction(user, day)
    return limit is None or Employee.objects.filter(limit, pk=employee_id).exists()


def _holders() -> QuerySet[User]:
    """Active users with the approve_leave right, directly, through a group, or as superusers."""
    return (
        User.objects.filter(is_active=True)
        .filter(
            Q(is_superuser=True)
            | Q(
                groups__permissions__codename=APPROVE_CODENAME,
                groups__permissions__content_type__app_label=APPROVE_APP,
            )
            | Q(
                user_permissions__codename=APPROVE_CODENAME,
                user_permissions__content_type__app_label=APPROVE_APP,
            )
        )
        .distinct()
    )


def _admins() -> QuerySet[User]:
    """Active members of the Admin group and superusers."""
    return User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(groups__name=roles.ADMIN)).distinct()
