"""Who sees what (spec §6). Every view asks this module; nothing else checks permissions."""

from accounts.models import AccessScope, User
from django.db.models import Q, QuerySet
from django.utils import timezone
from macs.models import Branch

from employees.listing import LEGACY_NOT_WORKING, still_working
from employees.models import (
    ActivityEntry,
    ActivityKind,
    Employee,
    Event,
    EventType,
    HrOrder,
    JobRecord,
    OrderType,
)
from employees.scope import restriction


def is_own(user: User, employee: Employee) -> bool:
    ext = getattr(employee, "ext", None)  # EmployeeExt holds the login link (one-to-one, may be missing)
    return user.is_active and ext is not None and ext.user_id is not None and ext.user_id == user.pk


def own_employee(user: User) -> Employee | None:
    """The employee linked to this login (EmployeeExt.user), or None. No right needed: it is the user's own record."""
    if not user.is_active:
        return None
    return Employee.objects.filter(ext__user_id=user.pk).first()


def visible_employees(user: User) -> QuerySet[Employee]:
    if not user.is_active:
        return Employee.objects.none()
    if user.has_perm("macs.view_employees"):
        visible = Employee.objects.all()
    else:
        visible = Employee.objects.filter(ext__user_id=user.pk)
    limit = restriction(user)
    if limit is not None:
        visible = visible.filter(limit)
    return visible


def manager_choices(user: User, current: Employee | None = None) -> QuerySet[Employee]:
    """Whom `user` may pick as a manager: the people they may see who work here today, plus `current` (the
    employee's manager now), so an existing manager stays valid even when outside the scope or no longer working
    here. "Works here" is the employee list's own rule: `listing.still_working` for HR job history, and for people
    with no HR job history the MACS emptype (`LEGACY_NOT_WORKING`, as `listing.row_for` reads it)."""
    today = timezone.localdate()
    no_history = ~Q(pk__in=JobRecord.objects.values("employee_id"))
    working = still_working(visible_employees(user), today).exclude(Q(emptype__in=LEGACY_NOT_WORKING) & no_history)
    allowed = Q(pk__in=working.values("pk"))
    if current is not None:
        allowed |= Q(pk=current.pk)
    return Employee.objects.filter(allowed)


def _branch_limit(user: User) -> list[int] | None:
    """The branch ids a user may hire into when the data scope limits them by branch; None when it does not.
    Follows `restriction`: Admin, superusers and users without a limited scope are never limited."""
    if restriction(user) is None:
        return None
    scope = AccessScope.objects.filter(user=user).first()
    return list(scope.branch_ids) if scope is not None and scope.branch_ids else None


def branch_choices(user: User) -> QuerySet[Branch]:
    """The branches `user` may pick on a hire: only the listed ones for a branch-limited user, else all."""
    ids = _branch_limit(user)
    return Branch.objects.all() if ids is None else Branch.objects.filter(pk__in=ids)


def branch_required(user: User) -> bool:
    """A branch-limited user must pick a branch on a hire, so the new person lands inside their scope."""
    return _branch_limit(user) is not None


def default_branch(user: User) -> Branch | None:
    """The hirer's own branch when they may pick it; else, for a branch-limited user, the first listed branch."""
    choices = branch_choices(user)
    employee = user.employee
    if employee is not None and employee.branch_id is not None:
        own = choices.filter(pk=employee.branch_id).first()
        if own is not None:
            return own
    return choices.first() if branch_required(user) else None


def can_manage(user: User) -> bool:
    return user.has_perm("macs.manage_employees")


def can_view_salary(user: User) -> bool:
    return user.has_perm("macs.view_salary")


def can_open_order_scan(user: User, order: HrOrder) -> bool:
    """Per order type (user decision OQ-080): hire and rehire orders are treated as salary-bearing; a scan cannot be
    edited to leave the salary out. Transfer, promotion and demotion orders keep the old rule because the documents
    the system generates for them carry no salary. Hire orders are `is_hire`; rehire orders are OrderType.HIRED, so
    the test is either one. Other order types: True here; the caller has already checked the employee is visible."""
    if order.is_hire or order.order_type == OrderType.HIRED:
        return can_view_salary(user)
    return True


def can_manage_salary(user: User) -> bool:
    return user.has_perm("macs.manage_salary") and can_view_salary(user)


def can_view_personal(user: User, employee: Employee) -> bool:
    return user.has_perm("macs.view_personal") or is_own(user, employee)


def visible_activity(user: User, employee: Employee) -> QuerySet[ActivityEntry]:
    """Callers must have fetched `employee` via `visible_employees`; this does not re-check it."""
    if not user.is_active:
        return ActivityEntry.objects.none()
    entries = employee.activity.all()
    if not can_view_salary(user):
        entries = entries.filter(sensitive=False)
    if not can_view_personal(user, employee):
        entries = entries.filter(personal=False)
    if not user.has_perm("macs.view_employees"):  # own page only: no internal notes
        entries = entries.exclude(kind=ActivityKind.NOTE)
    return entries


def can_record_event(user: User, type: str) -> bool:
    """Salary changes need the salary switch; every other event needs manage_employees."""
    return can_manage_salary(user) if type == EventType.SALARY_CHANGE else can_manage(user)


def can_cancel(user: User, event: Event) -> bool:
    """A mixed (job + salary) event needs both rights, so it is never half-cancelled."""
    if event.applied_at is None:  # waiting: nothing written yet, so what it would change decides
        proposed = event.proposed or {}
        has_job = bool(proposed.get("job"))
        has_salary = proposed.get("salary") is not None
    else:
        has_job = event.job_records.exists()
        has_salary = event.salary_records.exists()
    if not has_job and not has_salary:
        return can_manage(user)
    return (not has_job or can_manage(user)) and (not has_salary or can_manage_salary(user))
