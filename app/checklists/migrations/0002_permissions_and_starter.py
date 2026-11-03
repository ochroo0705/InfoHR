import warnings
from typing import Any

from django.db import migrations

# Frozen copies at the time of this migration (accounts.roles.DEFAULT_CHECKLIST_PERMS[ADMIN]).
NAMES = {
    "manage_checklists": "Жагсаалтын загвар засах",
    "override_offboarding": "Жагсаалт дуусаагүй байхад ажлаас гаргах",
}
STARTER_NAME = "Ажлаас гарах (үндсэн)"
# title, owner (role group name; None = the direct manager), due offset in days, required
STARTER_TASKS: list[tuple[str, str | None, int, bool]] = [
    ("Ажлаа хүлээлгэн өгөх", None, -3, True),
    ("Эд хөрөнгө, тоног төхөөрөмж буцаах", "HR", 0, True),
    ("Нэвтрэх эрх хаах", "Admin", 0, True),
    ("Эцсийн тооцоо шалгах", "Accountant", 0, True),
    ("Ажлаас гарах ярилцлага", "HR", 0, False),
]


def missing_starter_groups(group_model: Any) -> list[str]:
    """Role groups that a starter task needs and this database does not have, in task order."""
    missing: list[str] = []
    for _title, owner, _offset, _required in STARTER_TASKS:
        if owner is not None and owner not in missing and not group_model.objects.filter(name=owner).exists():
            missing.append(owner)
    return missing


def grant_admin_and_seed(apps: Any, schema_editor: Any) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="checklists", model="checklisttemplate")
    # Permission rows of new Meta permissions are created after all migrations; create them here too.
    perms = [
        Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
        for code, name in NAMES.items()
    ]
    admin = Group.objects.filter(name="Admin").first()
    if admin is not None:  # no Admin group (fresh or edited database): nothing to grant
        admin.permissions.add(*perms)

    Template = apps.get_model("checklists", "ChecklistTemplate")
    Task = apps.get_model("checklists", "ChecklistTemplateTask")
    if Template.objects.filter(kind="offboarding", is_default=True).exists():
        return
    # All or nothing: a starter task without its owner group would be wrong, so when any group is missing the
    # whole starter template is left out and the database operator is told which group to create.
    missing = missing_starter_groups(Group)
    if missing:
        warnings.warn(
            f"checklists 0002: role group(s) {', '.join(missing)} missing; the starter offboarding template "
            f"was not created. Create the group(s), then add the template by hand in the admin.",
            UserWarning,
            stacklevel=2,
        )
        return
    template = Template.objects.create(kind="offboarding", name=STARTER_NAME, is_default=True, reasons=[], active=True)
    for position, (title, owner, offset, required) in enumerate(STARTER_TASKS, start=1):
        Task.objects.create(
            template=template,
            position=position,
            title=title,
            group=Group.objects.get(name=owner) if owner is not None else None,
            manager=owner is None,
            due_offset_days=offset,
            required=required,
        )


def revoke_admin_and_unseed(apps: Any, schema_editor: Any) -> None:
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    perms = Permission.objects.filter(codename__in=NAMES, content_type__app_label="checklists")
    for admin in Group.objects.filter(name="Admin"):
        admin.permissions.remove(*perms)
    apps.get_model("checklists", "ChecklistTemplate").objects.filter(
        kind="offboarding", is_default=True, name=STARTER_NAME
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("checklists", "0001_initial"),
        ("accounts", "0002_role_groups"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(grant_admin_and_seed, revoke_admin_and_unseed)]
