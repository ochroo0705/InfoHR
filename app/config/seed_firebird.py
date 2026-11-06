"""Starter data for the Firebird migration sets: the state the PostgreSQL migrations leave behind.

A Firebird database built from migrations_fb has tables only. Each seed_<app> function below creates
the final state that the PostgreSQL data migrations (the source of truth) produce once they have all
run in order. Each function takes the migration `apps` registry, so it runs inside RunPython of
migrations_fb/0002_seed.py (or 0003_seed.py where the app already has a second migration), and the
same code is used by the seed tests.

Rules (same as the sources): ORM only (apps.get_model), get_or_create, add-only (no grant or row is
removed, and an existing permission keeps its name), a grant to a missing group is skipped.

Final-state decisions (the PostgreSQL history changed these after the first migration that set them):
- accounts.view_salary is not created: employees 0002 moved its grants to macs.employee.view_salary and
  deleted the accounts row. On a fresh database there is no old row to move, so seed_employees grants
  view_salary to the groups that held the old switch (Admin and Accountant, accounts 0002).
- employees 0002 never grants view_salary directly (its DEFAULTS loop skips it); the moved grant is the only one.
- leave.LeaveType is not seeded: leave 0003 deleted that model and its rows with it. The leave types
  live in the MACS table (macs.LeaveTypeRow) with leave.LeaveTypeExt settings.
- leave permissions sit on content type leave.leaveext (leave 0003 repointed them from leave.leave).
- leave.manage_leave_settings is granted to Admin only (leave 0004).
- AnnualLeaveRule.brackets is a JSON field, so the bracket values are stored in the row, not in rows.
- checklists: the two starter templates are created only when every owner group they name exists, as in
  the sources (all or nothing).
"""

import warnings
from datetime import date
from decimal import Decimal
from typing import Any

# --- accounts (accounts 0002, 0003 names, 0008 view_audit, 0009 Auditor) -------------------------
ACCOUNT_PERMISSIONS = {
    "approve_leave": "Чөлөө, амралт батлах",
    "issue_orders": "Тушаал гаргах / баталгаажуулах",
    "export_lists": "Жагсаалтыг Excel рүү гаргах",
    "view_audit": "Үйл ажиллагааны бүртгэл харах",
}
ACCOUNT_GROUPS = {
    "Admin": tuple(ACCOUNT_PERMISSIONS),
    "HR": ("approve_leave", "issue_orders", "export_lists"),
    "Accountant": ("export_lists",),
    "Employee": (),
    "Auditor": ("view_audit",),
}

# --- lists (lists 0002) ------------------------------------------------------------------------
LIST_PERMISSIONS = {"manage_lists": "Жагсаалт засах"}
LIST_GROUPS = {"Admin": ("manage_lists",), "HR": ("manage_lists",)}

# --- leave (leave 0002, 0003, 0004, 0005) ------------------------------------------------------
LEAVE_PERMISSIONS = {
    "view_leave": "Чөлөө харах",
    "record_leave": "Чөлөө бүртгэх",
    "manage_leave_settings": "Чөлөөний тохиргоо",
}
LEAVE_GROUPS = {
    "Admin": tuple(LEAVE_PERMISSIONS),
    "HR": ("view_leave", "record_leave"),
    "Accountant": ("view_leave",),
}
REQUEST_PERMISSIONS = {"request_own_leave": "Өөрийн чөлөө хүсэх"}  # on leave.leaverequest, granted to Employee
ANNUAL_RULE = {
    "effective_from": date(2022, 1, 1),
    "base_days": Decimal(15),
    "base_days_minor_or_disabled": Decimal(20),
    "brackets": [
        {"from_month": 61, "extra_days": 3},
        {"from_month": 121, "extra_days": 5},
        {"from_month": 181, "extra_days": 7},
        {"from_month": 241, "extra_days": 9},
        {"from_month": 301, "extra_days": 11},
        {"from_month": 373, "extra_days": 14},
    ],
}

# --- recruitment (recruitment 0002) ------------------------------------------------------------
RECRUITMENT_PERMISSIONS = {"manage_recruitment": "Ажилд авах ажил удирдах"}
RECRUITMENT_GROUPS = ("HR", "Admin")

# --- reports (reports 0002) --------------------------------------------------------------------
REPORT_PERMISSIONS = {
    "view_reports": "Тайлан харах",
    "manage_saved_views": "Хадгалсан харагдацыг засах, устгах",
}
REPORT_GROUPS = {
    "Admin": tuple(REPORT_PERMISSIONS),
    "HR": ("view_reports",),
    "Accountant": ("view_reports",),
}

# --- employees (employees 0002 permissions, 0022 position slots) -------------------------------
# The employee permissions sit on the macs.employee content type (employees 0002), not on an employees model.
EMPLOYEE_CONTENT_TYPE = ("macs", "employee")
# Frozen copy of employees 0002 NAMES. view_salary is left out of the direct grants
# because employees 0002 never grants it directly (its loop skips it); see VIEW_SALARY_GROUPS.
EMPLOYEE_PERMISSIONS = {
    "view_employees": "Бүх ажилтныг харах",
    "manage_employees": "Ажилтан нэмэх, засах, засвар хийх",
    "view_personal": "Хувийн мэдээллийг харах",
    "view_salary": "Цалин, даатгалын мэдээллийг харах",
    "manage_salary": "Цалин, даатгалын мэдээллийг засах",
}
EMPLOYEE_GROUPS = {
    "Admin": ("view_employees", "manage_employees", "view_personal", "manage_salary"),
    "HR": ("view_employees", "manage_employees", "view_personal"),
    "Accountant": ("view_employees", "manage_salary"),
}
# accounts 0002 gave the old accounts.view_salary to Admin and Accountant; employees 0002 moved those grants
# to macs.employee.view_salary. A fresh database has no old row, so the moved grants are written here.
VIEW_SALARY_GROUPS = ("Admin", "Accountant")
# On employees.companysettings (employees 0022). Frozen copy of its NAMES.
POSITION_SLOT_PERMISSIONS = {
    "manage_position_slots": "Орон тооны төлөвлөгөө засах",
    "override_position_slots": "Орон тоо дүүрсэн үед ажилд авахыг зөвшөөрөх",
}
POSITION_SLOT_GROUPS = {
    "Admin": ("manage_position_slots", "override_position_slots"),
    "HR": ("manage_position_slots",),
}

# --- checklists (checklists 0002 permissions and offboarding starter, 0005 onboarding starter) ---
CHECKLIST_PERMISSIONS = {
    "manage_checklists": "Жагсаалтын загвар засах",
    "override_offboarding": "Жагсаалт дуусаагүй байхад ажлаас гаргах",
}
CHECKLIST_GROUPS = {"Admin": tuple(CHECKLIST_PERMISSIONS)}
# title, owner (role group name; None = the direct manager), due offset in days, required
OFFBOARDING_NAME = "Ажлаас гарах (үндсэн)"
OFFBOARDING_TASKS: list[tuple[str, str | None, int, bool]] = [
    ("Ажлаа хүлээлгэн өгөх", None, -3, True),
    ("Эд хөрөнгө, тоног төхөөрөмж буцаах", "HR", 0, True),
    ("Нэвтрэх эрх хаах", "Admin", 0, True),
    ("Эцсийн тооцоо шалгах", "Accountant", 0, True),
    ("Ажлаас гарах ярилцлага", "HR", 0, False),
]
ONBOARDING_NAME = "Ажилд орох (үндсэн)"
ONBOARDING_TASKS: list[tuple[str, str | None, int, bool]] = [
    ("Ажлын байр бэлтгэх", None, -3, True),
    ("Бүртгэл, и-мэйл үүсгэх", "Admin", -1, True),
    ("Бичиг баримт цуглуулж, гэрээ болон тушаалыг баталгаажуулах", "HR", 0, True),
    ("Угтан авч, ажлын үүргийг танилцуулах", None, 0, True),
    ("Дотоод журмыг тайлбарлах", "HR", 1, True),
    ("Цалингийн банкны дансны мэдээлэл авах", "Accountant", 0, True),
    ("Эхний сарын зорилгыг тохиролцох", None, 7, False),
]

# --- assistant (assistant 0002, 0004, 0006: Admin only) ----------------------------------------
ASSISTANT_PERMISSIONS = {
    "helpquestion": {"view_helpquestion": "Can view Туслахын асуулт"},
    "helpexample": {
        "view_helpexample": "Can view Сурсан жишээ, тест",
        "add_helpexample": "Can add Сурсан жишээ, тест",
        "change_helpexample": "Can change Сурсан жишээ, тест",
    },
    "assistantsettings": {
        "view_assistantsettings": "Can view Туслахын тохиргоо",
        "change_assistantsettings": "Can change Туслахын тохиргоо",
    },
}


def _content_type(apps: Any, app_label: str, model: str) -> Any:
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct, _ = ContentType.objects.get_or_create(app_label=app_label, model=model)
    return ct


def _permissions(apps: Any, content_type: Any, names: dict[str, str]) -> dict[str, Any]:
    Permission = apps.get_model("auth", "Permission")
    return {
        codename: Permission.objects.get_or_create(
            codename=codename, content_type=content_type, defaults={"name": name}
        )[0]
        for codename, name in names.items()
    }


def _grant_to_existing_groups(apps: Any, grants: dict[str, tuple[str, ...]], perms: dict[str, Any]) -> None:
    """Grant only to groups that exist; a missing group (edited database) is skipped, as in the sources."""
    Group = apps.get_model("auth", "Group")
    for group_name, codenames in grants.items():
        group = Group.objects.filter(name=group_name).first()
        if group is not None:
            group.permissions.add(*(perms[c] for c in codenames))


def seed_accounts(apps: Any) -> None:
    Group = apps.get_model("auth", "Group")
    ct = _content_type(apps, "accounts", "user")
    perms = _permissions(apps, ct, ACCOUNT_PERMISSIONS)
    for group_name, codenames in ACCOUNT_GROUPS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.add(*(perms[c] for c in codenames))


def seed_lists(apps: Any) -> None:
    ct = _content_type(apps, "lists", "meaningfulentry")
    perms = _permissions(apps, ct, LIST_PERMISSIONS)
    _grant_to_existing_groups(apps, LIST_GROUPS, perms)


def seed_leave(apps: Any) -> None:
    AnnualLeaveRule = apps.get_model("leave", "AnnualLeaveRule")
    AnnualLeaveRule.objects.get_or_create(
        effective_from=ANNUAL_RULE["effective_from"],
        defaults={key: value for key, value in ANNUAL_RULE.items() if key != "effective_from"},
    )
    perms = _permissions(apps, _content_type(apps, "leave", "leaveext"), LEAVE_PERMISSIONS)
    _grant_to_existing_groups(apps, LEAVE_GROUPS, perms)

    request_perms = _permissions(apps, _content_type(apps, "leave", "leaverequest"), REQUEST_PERMISSIONS)
    Group = apps.get_model("auth", "Group")
    employee = Group.objects.filter(name="Employee").first()
    if employee is not None:
        employee.permissions.add(*request_perms.values())


def seed_recruitment(apps: Any) -> None:
    Group = apps.get_model("auth", "Group")
    perms = _permissions(apps, _content_type(apps, "recruitment", "vacancy"), RECRUITMENT_PERMISSIONS)
    for group in Group.objects.filter(name__in=RECRUITMENT_GROUPS):  # a missing group is skipped
        group.permissions.add(*perms.values())


def seed_reports(apps: Any) -> None:
    ct = _content_type(apps, "reports", "savedview")
    perms = _permissions(apps, ct, REPORT_PERMISSIONS)
    _grant_to_existing_groups(apps, REPORT_GROUPS, perms)


def seed_employees(apps: Any) -> None:
    perms = _permissions(apps, _content_type(apps, *EMPLOYEE_CONTENT_TYPE), EMPLOYEE_PERMISSIONS)
    _grant_to_existing_groups(apps, EMPLOYEE_GROUPS, perms)
    _grant_to_existing_groups(apps, {group: ("view_salary",) for group in VIEW_SALARY_GROUPS}, perms)

    slot_perms = _permissions(apps, _content_type(apps, "employees", "companysettings"), POSITION_SLOT_PERMISSIONS)
    _grant_to_existing_groups(apps, POSITION_SLOT_GROUPS, slot_perms)


def _missing_groups(Group: Any, tasks: list[tuple[str, str | None, int, bool]]) -> list[str]:
    """Role groups that the starter tasks need and this database does not have, in task order."""
    missing: list[str] = []
    for _title, owner, _offset, _required in tasks:
        if owner is not None and owner not in missing and not Group.objects.filter(name=owner).exists():
            missing.append(owner)
    return missing


def _seed_starter_template(
    apps: Any, kind: str, name: str, tasks: list[tuple[str, str | None, int, bool]], source: str
) -> None:
    """The default template of one kind, with its tasks. All or nothing: any missing owner group skips it."""
    Group = apps.get_model("auth", "Group")
    Template = apps.get_model("checklists", "ChecklistTemplate")
    Task = apps.get_model("checklists", "ChecklistTemplateTask")
    if Template.objects.filter(kind=kind, is_default=True).exists():
        return
    missing = _missing_groups(Group, tasks)
    if missing:
        warnings.warn(
            f"{source}: role group(s) {', '.join(missing)} missing; the starter {kind} template was not "
            f"created. Create the group(s), then add the template by hand in the admin.",
            UserWarning,
            stacklevel=3,
        )
        return
    template = Template.objects.create(kind=kind, name=name, is_default=True, reasons=[], active=True)
    for position, (title, owner, offset, required) in enumerate(tasks, start=1):
        Task.objects.create(
            template=template,
            position=position,
            title=title,
            group=Group.objects.get(name=owner) if owner is not None else None,
            manager=owner is None,
            due_offset_days=offset,
            required=required,
        )


def seed_checklists(apps: Any) -> None:
    perms = _permissions(apps, _content_type(apps, "checklists", "checklisttemplate"), CHECKLIST_PERMISSIONS)
    _grant_to_existing_groups(apps, CHECKLIST_GROUPS, perms)
    _seed_starter_template(apps, "offboarding", OFFBOARDING_NAME, OFFBOARDING_TASKS, "checklists 0002")
    _seed_starter_template(apps, "onboarding", ONBOARDING_NAME, ONBOARDING_TASKS, "checklists 0005")


def seed_assistant(apps: Any) -> None:
    for model, names in ASSISTANT_PERMISSIONS.items():
        perms = _permissions(apps, _content_type(apps, "assistant", model), names)
        _grant_to_existing_groups(apps, {"Admin": tuple(names)}, perms)


def seed_all(apps: Any) -> None:
    """Every seed, in dependency order: accounts creates the role groups the others grant to."""
    seed_accounts(apps)
    seed_lists(apps)
    seed_leave(apps)
    seed_recruitment(apps)
    seed_reports(apps)
    seed_employees(apps)
    seed_checklists(apps)
    seed_assistant(apps)
