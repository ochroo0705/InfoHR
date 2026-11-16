"""The governed view names the tests expect, grouped by the gate that opens them (see hr_sql/catalogue.py).

GOV_EMPLOYEES is always present for a user who may see employees. The other groups are added by the personal right
and the salary right, so the tests can ask "which views does this user get" without repeating the lists.
"""

OPEN_VIEWS: tuple[str, ...] = (
    "GOV_LEAVE",
    "GOV_ORDERS",
    "GOV_AWARDS",
    "GOV_GIFTS",
    "GOV_JOB_HISTORY",
    "GOV_ENTITLEMENTS",
    "GOV_LEAVE_REQUESTS",
    "GOV_DEPARTMENTS",
    "GOV_POSITIONS",
)
# Needs macs.view_employees: pending and cancelled HR changes, which an own-record-only user must not see.
EMPLOYEE_RIGHT_VIEWS: tuple[str, ...] = ("GOV_EVENTS",)
PERSONAL_VIEWS: tuple[str, ...] = ("GOV_CHILDREN", "GOV_EDUCATION", "GOV_QUALIFICATIONS", "GOV_CERTIFICATES")
SALARY_VIEWS: tuple[str, ...] = ("GOV_SALARY", "GOV_LOANS")
# Views with no EMP_ID column: every department or position is a row, only HEADCOUNT depends on the asker's scope.
ORG_VIEWS: tuple[str, ...] = ("GOV_DEPARTMENTS", "GOV_POSITIONS")
ALL_VIEWS: tuple[str, ...] = (
    "GOV_EMPLOYEES",
    *PERSONAL_VIEWS,
    *OPEN_VIEWS,
    *EMPLOYEE_RIGHT_VIEWS,
    *SALARY_VIEWS,
)
