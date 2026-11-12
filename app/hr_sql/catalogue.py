"""The governed views a signed-in user may ask about. The columns and their descriptions come from the reviewed files in
hr_sql/descriptions/ (see hr_sql/descriptions.py); the column names must match hr_sql/views.py (tests/test_scope.py
checks this against the Firebird views).

Access is not decided here beyond "may see employees, or has an own record". Which rows appear is decided by the
scope fill (hr_sql/scope.py), so a user who has a catalogue entry but no visible employee gets zero rows.

The personal data (birth date, gender, the children) is decided by employees/access.py::can_view_personal, the same
rule every other screen uses. A user without it gets GOV_EMPLOYEES without BIRTH_DATE and GENDER, and no GOV_CHILDREN.
"""

from dataclasses import replace

from accounts.models import User
from employees.access import can_view_personal, own_employee
from macs.models import Employee
from sqlcore.catalogue import Catalogue, View

from hr_sql.descriptions import load_view

PERSONAL_COLUMNS = frozenset({"BIRTH_DATE", "GENDER"})

EMPLOYEES: View = load_view("GOV_EMPLOYEES")
CHILDREN: View = load_view("GOV_CHILDREN")
LEAVE: View = load_view("GOV_LEAVE")
ORDERS: View = load_view("GOV_ORDERS")
SALARY: View = load_view("GOV_SALARY")
LOANS: View = load_view("GOV_LOANS")
EMPLOYEES_NO_PERSONAL: View = replace(
    EMPLOYEES, columns=tuple(column for column in EMPLOYEES.columns if column.name not in PERSONAL_COLUMNS)
)


def _may_view_personal(user: User) -> bool:
    """`can_view_personal`, asked for the people this user may see.

    With the employee right the user sees other people's records, so the question is asked for an employee who is not
    the user's own (an unsaved Employee: nobody's own record), which reduces to the view_personal right. Without the
    employee right the user sees only the own record (employees/access.py::visible_employees), and can_view_personal
    is asked for that record.
    """
    if user.has_perm("macs.view_employees"):
        return can_view_personal(user, Employee())
    own = own_employee(user)
    return own is not None and can_view_personal(user, own)


def catalogue_for(user: User) -> Catalogue:
    """The views for this user: the employee views when the user is active and may see employees or has an own
    record; the children view and the personal columns only when `_may_view_personal`; the salary and loan views in
    addition only when the user has macs.view_salary.

    An inactive user, or one with neither right nor own record, gets an empty catalogue. This function is the only
    place that decides which views and columns a user may ask about.
    """
    if not user.is_active:
        return Catalogue(views=())
    if not (user.has_perm("macs.view_employees") or own_employee(user) is not None):
        return Catalogue(views=())
    if _may_view_personal(user):
        views: tuple[View, ...] = (EMPLOYEES, CHILDREN, LEAVE, ORDERS)
    else:
        views = (EMPLOYEES_NO_PERSONAL, LEAVE, ORDERS)
    if user.has_perm("macs.view_salary"):
        views = (*views, SALARY, LOANS)
    return Catalogue(views=views)
