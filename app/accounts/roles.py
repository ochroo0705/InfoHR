"""Role groups and their default switches (docs/phase1/core-hr-scope.md §1)."""

ADMIN = "Admin"
HR = "HR"
ACCOUNTANT = "Accountant"
EMPLOYEE = "Employee"

SWITCHES = ("approve_leave", "issue_orders", "export_lists")

DEFAULT_SWITCHES: dict[str, tuple[str, ...]] = {
    ADMIN: SWITCHES,
    HR: ("approve_leave", "issue_orders", "export_lists"),
    ACCOUNTANT: ("export_lists",),
    EMPLOYEE: (),
}

# Employee-module permissions per role (employees app, spec §6).
DEFAULT_EMPLOYEE_PERMS: dict[str, tuple[str, ...]] = {
    ADMIN: ("view_employees", "manage_employees", "view_personal", "view_salary", "manage_salary"),
    HR: ("view_employees", "manage_employees", "view_personal"),
    ACCOUNTANT: ("view_employees", "view_salary", "manage_salary"),
    EMPLOYEE: (),
}

# Leave-module permissions per role (leave app, spec §6).
DEFAULT_LEAVE_PERMS: dict[str, tuple[str, ...]] = {
    ADMIN: ("view_leave", "record_leave", "manage_leave_settings"),
    HR: ("view_leave", "record_leave", "manage_leave_settings"),
    ACCOUNTANT: ("view_leave",),
    EMPLOYEE: (),
}
