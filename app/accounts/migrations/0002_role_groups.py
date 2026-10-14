from typing import Any

from django.db import migrations

# Frozen copy of accounts.roles at the time of this migration.
SWITCH_NAMES = {
    "view_salary": "Can see the Salary & insurance tab",
    "approve_leave": "Can approve leave",
    "issue_orders": "Can issue / sign HR orders",
    "export_lists": "Can export lists to Excel",
}
DEFAULT_SWITCHES = {
    "Admin": tuple(SWITCH_NAMES),
    "HR": ("approve_leave", "issue_orders", "export_lists"),
    "Accountant": ("view_salary", "export_lists"),
    "Employee": (),
}


def create_groups(apps: Any, schema_editor: Any) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="accounts", model="user")
    perms = {
        code: Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
        for code, name in SWITCH_NAMES.items()
    }
    for group_name, codes in DEFAULT_SWITCHES.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.add(*(perms[c] for c in codes))


def remove_groups(apps: Any, schema_editor: Any) -> None:
    apps.get_model("auth", "Group").objects.filter(name__in=DEFAULT_SWITCHES).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial"), ("contenttypes", "0002_remove_content_type_name")]
    operations = [migrations.RunPython(create_groups, remove_groups)]
