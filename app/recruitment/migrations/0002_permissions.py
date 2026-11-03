from typing import Any

from django.db import migrations

# Frozen copies at the time of this migration (accounts.roles.DEFAULT_RECRUITMENT_PERMS).
CODENAME = "manage_recruitment"
NAME = "Ажилд авах ажил удирдах"
GROUPS = ("HR", "Admin")


def grant(apps: Any, schema_editor: Any) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="recruitment", model="vacancy")
    # Permission rows of new Meta permissions are created after all migrations; create it here too.
    perm, _ = Permission.objects.get_or_create(codename=CODENAME, content_type=ct, defaults={"name": NAME})
    for group in Group.objects.filter(name__in=GROUPS):  # a missing group (edited database) is skipped
        group.permissions.add(perm)


def revoke(apps: Any, schema_editor: Any) -> None:
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    perms = Permission.objects.filter(codename=CODENAME, content_type__app_label="recruitment")
    for group in Group.objects.filter(name__in=GROUPS):
        group.permissions.remove(*perms)


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0001_initial"),
        ("accounts", "0002_role_groups"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(grant, revoke)]
