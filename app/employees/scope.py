"""Team and department helpers for the data scope (who an actor may see). Read-only queries."""

from collections import defaultdict, deque
from collections.abc import Iterable
from datetime import date

from accounts import roles
from accounts.models import AccessScope, User
from django.db.models import Q
from django.utils import timezone
from macs.models import Department

from employees import history_range
from employees.models import EmployeeExt, JobRecord


def team_ids(employee_id: int, day: date) -> set[int]:
    """Every employee below `employee_id` in the manager chain on `day`, direct and indirect.
    Excludes `employee_id` itself; a loop in the data cannot make the walk run forever."""
    reports: dict[int, list[int]] = defaultdict(list)
    rows = JobRecord.objects.filter(history_range.on(day), manager__isnull=False).values_list(
        "manager_id", "employee_id"
    )
    for manager, employee in rows:
        reports[manager].append(employee)
    team: set[int] = set()
    visited = {employee_id}
    queue = deque([employee_id])
    while queue:
        current = queue.popleft()
        for report in reports[current]:
            if report not in visited:
                visited.add(report)
                team.add(report)
                queue.append(report)
    return team


def department_ids(roots: Iterable[int], *, include_sub: bool) -> set[int]:
    """The given departments, plus (when `include_sub`) every department below them in the parent tree.
    Unknown ids are returned as given."""
    result = set(roots)
    if not result:
        return set()
    if not include_sub:
        return result
    children: dict[int, list[int]] = defaultdict(list)
    for dep_id, parent_id in Department.objects.values_list("pk", "parent_id_value"):
        if parent_id is not None:
            children[parent_id].append(dep_id)
    queue = deque(result)
    while queue:
        for child in children[queue.popleft()]:
            if child not in result:
                result.add(child)
                queue.append(child)
    return result


def creates_loop(employee_id: int, manager_id: int | None, day: date) -> bool:
    """True when making `manager_id` the manager of `employee_id` on `day` would close a manager loop."""
    if manager_id is None:
        return False
    return manager_id == employee_id or manager_id in team_ids(employee_id, day)


LOOP_MESSAGE = "Энэ ажилтан өөрийн доорх хүнд харъяалагдах боломжгүй."
SELF_MANAGER_MESSAGE = "Ажилтан өөрийн удирдлага байж болохгүй."


def manager_error(employee_id: int, manager_id: int | None, day: date) -> str | None:
    """The message for a refused manager on `day` (self or loop), or None when the manager is allowed."""
    if not creates_loop(employee_id, manager_id, day):
        return None
    return SELF_MANAGER_MESSAGE if manager_id == employee_id else LOOP_MESSAGE


def restriction(user: User, day: date | None = None) -> Q | None:
    """Whom a limited user may see on `day` (default: today). None = no limit.

    The union of: listed branches, listed departments (+ subs), own team, and the own record.
    Admin group, superusers and users without a limited AccessScope row are never limited.
    The result is cached on the `user` object per day, so one request runs these queries once.
    The cache lives in `user.__dict__["_scope_cache"]`, per user object and per day, so a copy of the user carries it.
    The team set can be stale within ONE request if a job change is made after the first `visible_employees`
    call (accepted by spec §4).
    """
    day = day or timezone.localdate()
    cache: dict[date, Q | None] = user.__dict__.setdefault("_scope_cache", {})
    if day not in cache:
        cache[day] = _compute_restriction(user, day)
    return cache[day]


def _compute_restriction(user: User, day: date) -> Q | None:
    scope = AccessScope.objects.filter(user=user).first()
    if scope is None or not scope.limited:
        return None
    if user.is_superuser or user.groups.filter(name=roles.ADMIN).exists():
        return None
    result = Q(ext__user_id=user.pk)  # own record; matches nothing when the login has no employee row
    if scope.own_team:
        employee_id = EmployeeExt.objects.filter(user_id=user.pk).values_list("employee_id", flat=True).first()
        if employee_id is not None:
            team = team_ids(employee_id, day)
            if team:
                result |= Q(pk__in=team)
    if scope.branch_ids:
        result |= Q(branch_id__in=scope.branch_ids)
    departments = department_ids(scope.department_ids, include_sub=scope.include_sub_departments)
    if departments:
        result |= Q(department_id__in=departments)
    return result
