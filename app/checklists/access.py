"""Who may do what with a checklist. Every checklist view and the employee-page panel ask this module.

Seeing a checklist is decided by data scope first: the employee must be in `visible_employees`. A task owner gains no
access to employee data by owning a task (D-055), so an owner outside that scope sees nothing of the employee.
"""

from datetime import date

from accounts.models import User
from employees import access as employee_access
from employees.models import EventType
from macs.models import Employee

from checklists.models import Checklist
from checklists.services import owners


def can_view(user: User, checklist: Checklist, day: date) -> bool:
    """The user may see the employee and holds `macs.view_employees`, or owns an open task on this checklist."""
    if not user.is_active:
        return False
    if not employee_access.visible_employees(user).filter(pk=checklist.employee_id).exists():
        return False
    return user.has_perm("macs.view_employees") or _owns_open_task(user, checklist, day)


def can_untick(user: User) -> bool:
    return user.is_active and employee_access.can_manage(user)


def can_cancel(user: User) -> bool:
    return user.is_active and employee_access.can_manage(user)


def can_start(user: User) -> bool:
    return user.is_active and employee_access.can_record_event(user, EventType.TERMINATION.value)


def can_see_employee(user: User, employee: Employee) -> bool:
    return employee_access.visible_employees(user).filter(pk=employee.pk).exists()


def _owns_open_task(user: User, checklist: Checklist, day: date) -> bool:
    tasks = list(checklist.tasks.filter(done_at__isnull=True).select_related("checklist"))
    if not tasks:
        return False
    resolved = owners.owners_many(tasks, day)
    return any(user.pk in owner.user_ids for owner in resolved.values())
