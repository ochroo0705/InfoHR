"""Who sees what (spec §6). Every view asks this module; nothing else checks permissions."""

from accounts.models import User
from django.db.models import QuerySet

from employees.models import ActivityEntry, ActivityKind, Employee, Event, EventType


def is_own(user: User, employee: Employee) -> bool:
    ext = getattr(employee, "ext", None)  # EmployeeExt holds the login link (one-to-one, may be missing)
    return user.is_active and ext is not None and ext.user_id is not None and ext.user_id == user.pk


def visible_employees(user: User) -> QuerySet[Employee]:
    if not user.is_active:
        return Employee.objects.none()
    if user.has_perm("macs.view_employees"):
        return Employee.objects.all()
    return Employee.objects.filter(ext__user_id=user.pk)


def can_manage(user: User) -> bool:
    return user.has_perm("macs.manage_employees")


def can_view_salary(user: User) -> bool:
    return user.has_perm("macs.view_salary")


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
    has_job = event.job_records.exists()
    has_salary = event.salary_records.exists()
    if not has_job and not has_salary:
        return can_manage(user)
    return (not has_job or can_manage(user)) and (not has_salary or can_manage_salary(user))
