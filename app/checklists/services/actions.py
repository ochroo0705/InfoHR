"""The checklist actions the Django views and the API share: untick, cancel, start offboarding, «my tasks» rows.

The rules live here, in Python, in the order the views always checked them. A user who may not see or do something
gets Http404, so the answer never says that a task or checklist exists. A refused change raises
`lifecycle.ChecklistError`. A bad input or a missing template raises `ActionError`, which carries the text the Django
page shows as its 400.
"""

from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.http import Http404
from django.shortcuts import get_object_or_404
from employees import access as employee_access
from employees.models import Employee

from checklists import access
from checklists.models import Checklist, ChecklistKind, ChecklistTask
from checklists.services import lifecycle, owners


class ActionError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def untick_for(user: User, pk: int, day: date) -> ChecklistTask:
    """Undo the tick of task `pk` as `user` on `day`. Http404 without the manage right, for an employee the user cannot
    see, or for a checklist the user cannot view."""
    task = get_object_or_404(ChecklistTask.objects.select_related("checklist__employee"), pk=pk)
    employee = task.checklist.employee
    if not access.can_untick(user) or not access.can_see_employee(user, employee):
        raise Http404
    if not access.can_view(user, task.checklist, day):
        raise Http404
    return lifecycle.untick(task, by=user)


def cancel_for(user: User, pk: int, day: date) -> Checklist:
    """Cancel the open checklist `pk` as `user` on `day`. Http404 without the manage right or when the checklist cannot
    be viewed."""
    checklist = get_object_or_404(Checklist.objects.select_related("employee"), pk=pk)
    if not access.can_cancel(user) or not access.can_view(user, checklist, day):
        raise Http404
    return lifecycle.cancel(checklist, by=user)


def start_offboarding(user: User, employee_id: int, anchor_day_text: str) -> Employee:
    """Start the offboarding checklist of a visible employee, anchored on the ISO date `anchor_day_text`. Returns the
    employee. Http404 for an employee the user cannot see or without the start right; ActionError for a bad date or
    when no template applies."""
    employee = get_object_or_404(employee_access.visible_employees(user), pk=employee_id)
    if not access.can_start(user):
        raise Http404
    try:
        anchor_day = date.fromisoformat(anchor_day_text)
    except ValueError:
        raise ActionError("Сүүлийн ажлын өдрийг оруулна уу.") from None
    if lifecycle.start(employee, ChecklistKind.OFFBOARDING, reason=None, anchor_day=anchor_day, by=user) is None:
        raise ActionError("Ажлаас гарах жагсаалтын загвар байхгүй байна.")
    return employee


@dataclass(frozen=True)
class MineRow:
    task_id: int
    title: str
    employee: str
    kind_label: str
    due_on: date
    overdue: bool


def mine_rows(user: User, day: date) -> list[MineRow]:
    """The user's own open tasks on `day`, earliest due date first, as rows for the API. Empty when the user may own no
    task (a user without an employee record works too)."""
    if not owners.may_have_tasks(user, day):
        return []
    return [
        MineRow(
            task_id=task.pk,
            title=task.title,
            employee=task.checklist.employee.full_name,
            kind_label=task.checklist.get_kind_display(),
            due_on=task.due_on,
            overdue=task.due_on < day,
        )
        for task in owners.my_tasks(user, day)
    ]
