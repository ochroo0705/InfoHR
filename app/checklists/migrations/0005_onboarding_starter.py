import warnings
from typing import Any

from django.db import migrations

STARTER_NAME = "Ажилд орох (үндсэн)"
# title, owner (role group name; None = the direct manager), due offset in days from the start date, required
STARTER_TASKS: list[tuple[str, str | None, int, bool]] = [
    ("Ажлын байр бэлтгэх", None, -3, True),
    ("Бүртгэл, и-мэйл үүсгэх", "Admin", -1, True),
    ("Бичиг баримт цуглуулж, гэрээ болон тушаалыг баталгаажуулах", "HR", 0, True),
    ("Угтан авч, ажлын үүргийг танилцуулах", None, 0, True),
    ("Дотоод журмыг тайлбарлах", "HR", 1, True),
    ("Цалингийн банкны дансны мэдээлэл авах", "Accountant", 0, True),
    ("Эхний сарын зорилгыг тохиролцох", None, 7, False),
]


def missing_starter_groups(group_model: Any) -> list[str]:
    """Role groups that a starter task needs and this database does not have, in task order."""
    missing: list[str] = []
    for _title, owner, _offset, _required in STARTER_TASKS:
        if owner is not None and owner not in missing and not group_model.objects.filter(name=owner).exists():
            missing.append(owner)
    return missing


def seed_onboarding(apps: Any, schema_editor: Any) -> None:
    Group = apps.get_model("auth", "Group")
    Template = apps.get_model("checklists", "ChecklistTemplate")
    Task = apps.get_model("checklists", "ChecklistTemplateTask")
    if Template.objects.filter(kind="onboarding", is_default=True).exists():
        return
    # All or nothing, as in 0002: a task without its owner group would be wrong, so any missing group skips the
    # whole starter template and the database operator is told which group to create.
    missing = missing_starter_groups(Group)
    if missing:
        warnings.warn(
            f"checklists 0005: role group(s) {', '.join(missing)} missing; the starter onboarding template "
            f"was not created. Create the group(s), then add the template by hand in the admin.",
            UserWarning,
            stacklevel=2,
        )
        return
    template = Template.objects.create(kind="onboarding", name=STARTER_NAME, is_default=True, reasons=[], active=True)
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


def unseed_onboarding(apps: Any, schema_editor: Any) -> None:
    apps.get_model("checklists", "ChecklistTemplate").objects.filter(
        kind="onboarding", is_default=True, name=STARTER_NAME
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("checklists", "0004_anchor_day"),
        ("accounts", "0002_role_groups"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(seed_onboarding, unseed_onboarding)]
