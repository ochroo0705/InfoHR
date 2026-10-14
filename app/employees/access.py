"""Who sees what (spec §6). Every view asks this module; nothing else checks permissions."""

from accounts.models import User
from django.db.models import QuerySet

from employees.models import ActivityEntry, ActivityKind, Employee


def is_own(user: User, employee: Employee) -> bool:
    return user.is_active and employee.user_id is not None and employee.user_id == user.pk


def visible_employees(user: User) -> QuerySet[Employee]:
    if not user.is_active:
        return Employee.objects.none()
    if user.has_perm("employees.view_employees"):
        return Employee.objects.all()
    return Employee.objects.filter(user_id=user.pk)


def can_manage(user: User) -> bool:
    return user.has_perm("employees.manage_employees")


def can_view_salary(user: User) -> bool:
    return user.has_perm("employees.view_salary")


def can_manage_salary(user: User) -> bool:
    return user.has_perm("employees.manage_salary") and can_view_salary(user)


def can_view_personal(user: User, employee: Employee) -> bool:
    return user.has_perm("employees.view_personal") or is_own(user, employee)


def visible_activity(user: User, employee: Employee) -> QuerySet[ActivityEntry]:
    """Callers must have fetched `employee` via `visible_employees`; this does not re-check it."""
    if not user.is_active:
        return ActivityEntry.objects.none()
    entries = employee.activity.all()
    if not can_view_salary(user):
        entries = entries.filter(sensitive=False)
    if not can_view_personal(user, employee):
        entries = entries.filter(personal=False)
    if not user.has_perm("employees.view_employees"):  # own page only: no internal notes
        entries = entries.exclude(kind=ActivityKind.NOTE)
    return entries
