from typing import Any

from django.db import migrations

# Frozen copies at the time of this migration (accounts.roles.DEFAULT_SLOT_PERMS).
NAMES = {
    "manage_position_slots": "Орон тооны төлөвлөгөө засах",
    "override_position_slots": "Орон тоо дүүрсэн үед ажилд авахыг зөвшөөрөх",
}
DEFAULTS = {
    "Admin": ("manage_position_slots", "override_position_slots"),
    "HR": ("manage_position_slots",),
}


def _permissions(apps: Any) -> dict[str, Any]:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    ct, _ = ContentType.objects.get_or_create(app_label="employees", model="companysettings")
    # Permission rows of new Meta permissions are created after all migrations; create them here too.
    return {
        code: Permission.objects.get_or_create(codename=code, content_type=ct, defaults={"name": name})[0]
        for code, name in NAMES.items()
    }


def grant(apps: Any, schema_editor: Any) -> None:
    Group = apps.get_model("auth", "Group")
    perms = _permissions(apps)
    for group_name, codes in DEFAULTS.items():
        group = Group.objects.filter(name=group_name).first()
        if group is not None:  # a missing or renamed group is skipped
            group.permissions.add(*(perms[c] for c in codes))


def revoke(apps: Any, schema_editor: Any) -> None:
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    found = Permission.objects.filter(codename__in=NAMES, content_type__app_label="employees")
    for group in Group.objects.filter(name__in=DEFAULTS):
        group.permissions.remove(*found)


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0021_position_slots"),
        ("accounts", "0002_role_groups"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(grant, revoke)]
