from typing import Any

from django.db import migrations

NAMES = {
    "view_employees": "Бүх ажилтныг харах",
    "manage_employees": "Ажилтан нэмэх, засах, засвар хийх",
    "view_personal": "Хувийн мэдээллийг харах",
    "view_salary": "Цалин, даатгалын мэдээллийг харах",
    "manage_salary": "Цалин, даатгалын мэдээллийг засах",
}
# Frozen copy of accounts.roles.DEFAULT_EMPLOYEE_PERMS.
DEFAULTS = {
    "Admin": tuple(NAMES),
    "HR": ("view_employees", "manage_employees", "view_personal"),
    "Accountant": ("view_employees", "view_salary", "manage_salary"),
}


def forwards(apps: Any, schema_editor: Any) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="macs", model="employee")
    perms = {
        code: Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
        for code, name in NAMES.items()
    }
    # Keep whatever the admin switched on for the old accounts.view_salary.
    old = Permission.objects.filter(codename="view_salary", content_type__app_label="accounts").first()
    if old is not None:
        for group in Group.objects.filter(permissions=old):
            group.permissions.add(perms["view_salary"])
        for user in old.user_set.all():
            user.user_permissions.add(perms["view_salary"])
        old.delete()
    for group_name, codes in DEFAULTS.items():
        group = Group.objects.filter(name=group_name).first()
        if group is not None:
            group.permissions.add(*(perms[c] for c in codes if c != "view_salary"))


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0001_initial"),
        ("accounts", "0002_role_groups"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
