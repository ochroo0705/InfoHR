from typing import Any

from django.db import migrations

# Frozen copy of accounts.roles.DEFAULT_LIST_PERMS.
NAMES = {"manage_lists": "Жагсаалт засах"}
DEFAULTS = {"Admin": tuple(NAMES), "HR": tuple(NAMES)}


def forwards(apps: Any, schema_editor: Any) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="lists", model="meaningfulentry")
    perms = {
        c: Permission.objects.get_or_create(codename=c, content_type=ct, defaults={"name": n})[0]
        for c, n in NAMES.items()
    }
    for group_name, codes in DEFAULTS.items():
        group = Group.objects.filter(name=group_name).first()
        if group is not None:
            group.permissions.add(*(perms[c] for c in codes))


class Migration(migrations.Migration):
    dependencies = [("lists", "0001_initial"), ("accounts", "0002_role_groups")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
