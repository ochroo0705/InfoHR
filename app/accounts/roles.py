"""Role groups and their default switches (docs/phase1/core-hr-scope.md §1)."""

ADMIN = "Admin"
HR = "HR"
ACCOUNTANT = "Accountant"
EMPLOYEE = "Employee"
AUDITOR = "Auditor"  # sees the system log only: no employee data, no export (decided 2026-10-29)

# Display names only (screens, dropdowns). The group names above stay the database keys; never store these.
ROLE_LABELS: dict[str, str] = {
    ACCOUNTANT: "Нягтлан",
    ADMIN: "Админ",
    AUDITOR: "Аудитор",
    EMPLOYEE: "Ажилтан",
    HR: "Хүний нөөц",
}

SWITCHES = ("approve_leave", "issue_orders", "export_lists", "view_audit")

DEFAULT_SWITCHES: dict[str, tuple[str, ...]] = {
    ADMIN: SWITCHES,
    HR: ("approve_leave", "issue_orders", "export_lists"),
    ACCOUNTANT: ("export_lists",),
    EMPLOYEE: (),
    AUDITOR: ("view_audit",),
}

# Employee-module permissions per role (employees app, spec §6).
DEFAULT_EMPLOYEE_PERMS: dict[str, tuple[str, ...]] = {
    ADMIN: ("view_employees", "manage_employees", "view_personal", "view_salary", "manage_salary"),
    HR: ("view_employees", "manage_employees", "view_personal"),
    ACCOUNTANT: ("view_employees", "view_salary", "manage_salary"),
    EMPLOYEE: (),
    AUDITOR: (),
}

# Lists-module permissions per role (lists app; the Lists screen is for HR admins).
DEFAULT_LIST_PERMS: dict[str, tuple[str, ...]] = {
    ADMIN: ("manage_lists",),
    HR: ("manage_lists",),
    ACCOUNTANT: (),
    EMPLOYEE: (),
    AUDITOR: (),
}

# Reports-module permissions per role (reports app, docs/superpowers/specs/2026-10-23-reports-design.md §8).
DEFAULT_REPORT_PERMS: dict[str, tuple[str, ...]] = {
    ADMIN: ("view_reports", "manage_saved_views"),
    HR: ("view_reports",),
    ACCOUNTANT: ("view_reports",),
    EMPLOYEE: (),
    AUDITOR: (),
}

# Leave-module permissions per role (leave app, spec §6).
DEFAULT_LEAVE_PERMS: dict[str, tuple[str, ...]] = {
    ADMIN: ("view_leave", "record_leave", "manage_leave_settings"),
    HR: ("view_leave", "record_leave"),  # leave settings (auto grants, types, holidays) are Admin only
    ACCOUNTANT: ("view_leave",),
    EMPLOYEE: ("request_own_leave",),
    AUDITOR: (),
}

# Checklist-module permissions per role (checklists app, offboarding checklist spec 2026-11-02).
DEFAULT_CHECKLIST_PERMS: dict[str, tuple[str, ...]] = {
    ADMIN: ("manage_checklists", "override_offboarding"),
    HR: (),
    ACCOUNTANT: (),
    EMPLOYEE: (),
    AUDITOR: (),
}

# Recruitment-module permissions per role (recruitment app, spec 2026-11-02). Hiring managers need no permission.
DEFAULT_RECRUITMENT_PERMS: dict[str, tuple[str, ...]] = {
    ADMIN: ("manage_recruitment",),
    HR: ("manage_recruitment",),
    ACCOUNTANT: (),
    EMPLOYEE: (),
    AUDITOR: (),
}

# Position-slot permissions per role (employees app, spec 2026-11-02). Only Admin may override a full position.
DEFAULT_SLOT_PERMS: dict[str, tuple[str, ...]] = {
    ADMIN: ("manage_position_slots", "override_position_slots"),
    HR: ("manage_position_slots",),
    ACCOUNTANT: (),
    EMPLOYEE: (),
    AUDITOR: (),
}
