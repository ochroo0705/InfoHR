"""Who may tick a checklist task at the moment of acting, and the «my tasks» list.

Nothing about the owner is stored as people. A task keeps its rule (a role group, the direct manager, or none, which
means Admin) and the people are worked out on each call, the same way leave approvers are
(`leave.services.approvers`): role members whose data scope admits the employee, the manager in the job row in force
on `day`, and when that is empty, the active Admin users. The employee's own login is never an owner.

The query count depends on the number of distinct groups, managers and candidate users, never on the number of tasks.
"""

from collections.abc import Callable
from datetime import date
from typing import Any, NamedTuple, cast

from accounts import roles
from accounts.models import User
from django.db.models import Q, QuerySet
from employees.models import EmployeeExt, JobRecord
from leave.services.approvers import _admins, _admitted, manager_user_ids

from checklists.models import ChecklistKind, ChecklistState, ChecklistTask

RULE_ROLE = "role"
RULE_MANAGER = "manager"
RULE_ADMIN = "admin"

ADMIN_FALLBACK_LABEL = "Админ (эзэн олдсонгүй)"  # shown when nobody in scope holds the rule

RULE_LABELS: dict[str, str] = {
    RULE_ROLE: "Рольоор",
    RULE_MANAGER: "Шууд удирдлага",
    RULE_ADMIN: "Админ",
}


class Owners(NamedTuple):
    rule: str
    user_ids: frozenset[int]


def resolution_day(kind: str, anchor_day: date, day: date) -> date:
    """The day owners are worked out on. Onboarding looks at the start day when it is still ahead: the new hire's job
    row (and so the manager and the data scope) only starts then. Offboarding is always resolved on `day`."""
    if kind == ChecklistKind.ONBOARDING:
        return max(day, anchor_day)
    return day


def owners_many(tasks: list[ChecklistTask], day: date) -> dict[int, Owners]:
    """Owners of each task on `day`, keyed by task id.

    The queries do not depend on the number of tasks: the shared ones run once, the manager and data-scope ones once
    per distinct resolution day (see `resolution_day`; that is one day unless future-start onboarding is listed)."""
    if not tasks:
        return {}
    facts = _facts(tasks)
    employee_ids = {employee_id for employee_id, _kind, _anchor in facts.values()}
    day_of = {pk: resolution_day(kind, anchor, day) for pk, (_employee_id, kind, anchor) in facts.items()}

    group_ids = {task.group_id for task in tasks if task.group_id is not None}
    members: dict[int, set[int]] = {}
    if group_ids:
        rows = User.groups.through.objects.filter(group_id__in=group_ids, user__is_active=True).values_list(
            "group_id", "user_id"
        )
        for group_id, user_id in rows:
            members.setdefault(group_id, set()).add(user_id)

    linked = _linked_logins(employee_ids)
    admins = set(_admins().values_list("pk", flat=True))
    candidates = admins.union(*members.values())
    managers: dict[date, dict[int, int | None]] = {}
    admitted: dict[date, dict[int, set[int] | None]] = {}
    for when in set(day_of.values()):
        manager_employees = {facts[task.pk][0] for task in tasks if _is_manager_task(task) and day_of[task.pk] == when}
        managers[when] = manager_user_ids(manager_employees, when)
        admitted[when] = _admitted(candidates, admins, employee_ids, when)

    result: dict[int, Owners] = {}
    for task in tasks:
        employee_id = facts[task.pk][0]
        when = day_of[task.pk]
        banned = {linked[employee_id]} if employee_id in linked else set()
        if task.group_id is not None:
            role_ids = {uid for uid in members.get(task.group_id, set()) if _sees(admitted[when], uid, employee_id)}
            role_ids -= banned
            if role_ids:
                result[task.pk] = Owners(RULE_ROLE, frozenset(role_ids))
                continue
        elif task.manager:
            manager = managers[when].get(employee_id)
            if manager is not None and manager not in banned:
                result[task.pk] = Owners(RULE_MANAGER, frozenset({manager}))
                continue
        result[task.pk] = Owners(RULE_ADMIN, frozenset(admins - banned))
    return result


def can_tick(user: User, task: ChecklistTask, day: date) -> bool:
    """Whether `user` may tick `task` on `day`. One task through `can_tick_many`, where the rules live."""
    return can_tick_many(user, [task], None, day).get(task.pk, False)


def can_tick_many(
    user: User, tasks: list[ChecklistTask], resolved: dict[int, Owners] | None = None, day: date | None = None
) -> dict[int, bool]:
    """Whether `user` may tick each task: the task is open, its checklist is open, and the user is an owner.

    An Admin may tick any open task, owned or not (decided 2026-11-02; HR may not). The employee's own login is never
    allowed to tick its own task, Admin or not. Tasks not open (or of a checklist that is not open) are absent from
    the result. `resolved` is the owners already worked out with `owners_many` for every open task of an open
    checklist (a panel passes them to avoid a second lookup); when None they are worked out here on `day`, which is
    then required. At most two queries beyond that whatever the number of tasks."""
    candidates = [t for t in tasks if t.done_at is None and t.checklist.state == ChecklistState.OPEN]
    if not candidates or not user.is_active:
        return {}
    if _is_admin(user):
        employee_ids = {t.checklist.employee_id for t in candidates}
        own = set(
            EmployeeExt.objects.filter(employee_id__in=employee_ids, user=user).values_list("employee_id", flat=True)
        )
        return {t.pk: t.checklist.employee_id not in own for t in candidates}
    if resolved is None:
        if day is None:
            raise ValueError("can_tick_many needs `resolved` or `day`")
        resolved = owners_many(candidates, day)
    return {t.pk: user.pk in resolved[t.pk].user_ids for t in candidates}


def my_tasks(user: User, day: date) -> list[ChecklistTask]:
    """Open tasks of open checklists that `user` owns on `day`, earliest due date first."""
    if not user.is_active:
        return []
    candidates = list(
        _open_tasks().filter(_candidate_filter(user)).select_related("checklist__employee").order_by("due_on", "pk")
    )
    owned = owners_many(candidates, day)
    return [task for task in candidates if user.pk in owned[task.pk].user_ids]


def may_have_tasks(user: User, day: date) -> bool:
    """A cheap test that `user` could own some open task on `day`. Never says no to someone `my_tasks` would return
    tasks for. Worked out once per user object and day, so the My page and the Today item share it."""
    return _cached(user, f"may_have_tasks:{day.isoformat()}", lambda: _may_have_tasks(user, day))


def _may_have_tasks(user: User, day: date) -> bool:
    if not user.is_active:
        return False
    if _is_admin(user):
        return _open_tasks().exists()
    if _open_tasks().filter(group__in=user.groups.values("pk")).exists():
        return True
    linked = EmployeeExt.objects.filter(user=user).values("employee_id")
    # A row that starts later counts too: a hire with a future start is owned on its start day (`resolution_day`).
    in_force_or_ahead = Q(period__contains=day) | Q(period__startswith__gt=day)
    if not JobRecord.objects.filter(in_force_or_ahead, manager__in=linked).exists():
        return False
    return _open_tasks().filter(manager=True).exists()


def _open_tasks() -> QuerySet[ChecklistTask]:
    return ChecklistTask.objects.filter(done_at__isnull=True, checklist__state=ChecklistState.OPEN)


def _candidate_filter(user: User) -> Q:
    """Narrows the open tasks in SQL to those `user` might own. Admin may own any task (the fallback), so no narrowing.
    The exact owners are worked out afterwards by `owners_many`."""
    if _is_admin(user):
        return Q()
    return Q(group__in=user.groups.values("pk")) | Q(manager=True)


def _is_admin(user: User) -> bool:
    return user.is_superuser or user.groups.filter(name=roles.ADMIN).exists()


def _is_manager_task(task: ChecklistTask) -> bool:
    return task.group_id is None and task.manager


def _facts(tasks: list[ChecklistTask]) -> dict[int, tuple[int, str, date]]:
    """Task id -> (employee id, checklist kind, checklist anchor day). Reads the checklist of each task without a query
    when it is already loaded."""
    if all(ChecklistTask.checklist.is_cached(task) for task in tasks):
        return {task.pk: (task.checklist.employee_id, task.checklist.kind, task.checklist.anchor_day) for task in tasks}
    rows = ChecklistTask.objects.filter(pk__in=[task.pk for task in tasks]).values_list(
        "pk", "checklist__employee_id", "checklist__kind", "checklist__anchor_day"
    )
    return {pk: (employee_id, kind, anchor) for pk, employee_id, kind, anchor in rows}


def _linked_logins(employee_ids: set[int]) -> dict[int, int]:
    """Employee id -> the login linked to that employee. One query."""
    return dict(
        EmployeeExt.objects.filter(employee_id__in=employee_ids, user_id__isnull=False).values_list(
            "employee_id", "user_id"
        )
    )


def _sees(admitted: dict[int, set[int] | None], user_id: int, employee_id: int) -> bool:
    if user_id not in admitted:
        return False
    allowed = admitted[user_id]
    return allowed is None or employee_id in allowed


def _cached[T](user: User, key: str, compute: Callable[[], T]) -> T:
    """`compute()` once per user object (kept in its __dict__, like the data-scope cache)."""
    cache: dict[str, Any] = user.__dict__.setdefault("_checklist_flags", {})
    if key not in cache:
        cache[key] = compute()
    return cast(T, cache[key])
