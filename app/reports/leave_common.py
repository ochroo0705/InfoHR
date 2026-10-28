"""The people a leave report lists, with the department and state each one has on the report's day (spec §6).

Leave reports never read the job, salary or history tables directly: the department and state come only from
`employees.listing.row_for`, the same rule the staff reports use."""

from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.urls import reverse
from employees import access, listing
from employees.models import Employee

from reports.filters import Filters

# the leave module's own right, shared by every C report: HR, Admin and Accountant have it; Employee does not
LEAVE_NEEDS = ("leave.view_leave",)


@dataclass(frozen=True)
class Person:
    employee: Employee
    department: str | None  # the job's department name on the day; None when the job has none
    department_id: int | None
    state: str  # listing.Row.state on the day: active / long_leave / left / upcoming


def people(user: User, f: Filters, day: date) -> list[Person]:
    """The people the user may see who ever worked here. The branch is today's; the department is the one on `day`."""
    qs = access.visible_employees(user).exclude(emptype__in=listing.NEVER_WORKED)
    if f.branch is not None:
        qs = qs.filter(branch_id=f.branch)
    found: list[Person] = []
    for employee in qs.order_by("family_name", "given_name"):
        row = listing.row_for(employee, day)
        job = row.job
        department_id = job.department_id if job is not None else None
        if f.department is not None and department_id != f.department:
            continue
        name = job.department.name if job is not None and department_id is not None else None
        found.append(Person(employee=employee, department=name, department_id=department_id, state=row.state))
    return found


def sort_key(person: Person, start: date) -> tuple[int, str, str]:
    """Start date descending, then the person's name. Used by the leave reports' row order."""
    employee = person.employee
    return (-start.toordinal(), employee.family_name or "", employee.given_name or "")


def detail_url(employee: Employee) -> str:
    return reverse("employees:detail", args=[employee.pk])
