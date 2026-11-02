from typing import Any

from django.db import migrations

# Frozen copies at the time of this migration (accounts.roles.AUDITOR, SWITCHES; 0008 holds the same permission).
ROLE = "Auditor"
CODENAME = "view_audit"
NAME = "Үйл ажиллагааны бүртгэл харах"


def grant_auditor(apps: Any, schema_editor: Any) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="accounts", model="user")
    perm, _ = Permission.objects.get_or_create(codename=CODENAME, content_type=ct, defaults={"name": NAME})
    # An existing Auditor group is kept as it is (same row, same users); only the view_audit grant is added.
    group, _ = Group.objects.get_or_create(name=ROLE)
    group.permissions.add(perm)


def revoke_auditor(apps: Any, schema_editor: Any) -> None:
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    group = Group.objects.filter(name=ROLE).first()
    if group is None:
        return
    perm = Permission.objects.filter(codename=CODENAME, content_type__app_label="accounts").first()
    if perm is not None:
        group.permissions.remove(perm)
    if not group.user_set.exists():  # a group someone still uses is kept
        group.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_grant_view_audit"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [migrations.RunPython(grant_auditor, revoke_auditor)]
