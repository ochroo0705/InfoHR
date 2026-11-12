"""Fills GOV_SCOPE with the employee ids the asker may see, and whether each one still works here today.

The visible rule is employees/access.py::visible_employees. The working rule is the employee list's own: row_for and
is_working in employees/listing.py. Neither is copied here.

The fill runs inside the caller's transaction on the governed connection. GOV_SCOPE is a global temporary table
(ON COMMIT DELETE ROWS), so its rows live only until that transaction ends.
"""

from datetime import date

from accounts.models import User
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import QuerySet
from django.utils import timezone
from employees.access import visible_employees
from employees.listing import employee_rows, is_working
from employees.models import Employee

_CLEAR = "DELETE FROM GOV_SCOPE"
_ADD = "INSERT INTO GOV_SCOPE (EMP_ID, WORKING) VALUES (%s, %s)"


def working_flags(people: QuerySet[Employee], today: date) -> dict[int, int]:
    """Employee id -> 1 if the employee list counts the person as working on `today`, else 0.

    Uses listing.employee_rows (one query for the jobs of everyone) and listing.is_working, so it is the same answer
    the employee list gives, including people with no HR job history (their MACS emptype decides)."""
    return {row.employee.pk: 1 if is_working(row) else 0 for row in employee_rows(people, today)}


def fill_scope(connection: BaseDatabaseWrapper, user: User) -> int:
    """Replace the rows of GOV_SCOPE with the ids `user` may see, each with its WORKING flag. Returns how many ids were
    written.

    Call it inside the transaction that will run the governed query. A user with no visible employee gets an empty
    scope, so every governed view then returns zero rows.
    """
    flags = working_flags(visible_employees(user), timezone.localdate())
    ids = sorted(flags)
    with connection.cursor() as cursor:
        cursor.execute(_CLEAR)
        if ids:
            cursor.executemany(_ADD, [(pk, flags[pk]) for pk in ids])
    return len(ids)
