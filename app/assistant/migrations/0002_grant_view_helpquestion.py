from typing import Any

from django.db import migrations

# Frozen copy of the model's default permission name at the time of this migration.
CODENAME = "view_helpquestion"
NAME = "Can view Туслахын асуулт"


def grant_admin(apps: Any, schema_editor: Any) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="assistant", model="helpquestion")
    # Permission rows of a new model are created after all migrations; create it here too.
    perm, _ = Permission.objects.get_or_create(codename=CODENAME, content_type=ct, defaults={"name": NAME})
    admin = Group.objects.filter(name="Admin").first()
    if admin is not None:  # no Admin group (fresh or edited database): nothing to grant
        admin.permissions.add(perm)


def revoke_admin(apps: Any, schema_editor: Any) -> None:
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    perm = Permission.objects.filter(codename=CODENAME, content_type__app_label="assistant").first()
    for admin in Group.objects.filter(name="Admin"):
        if perm is not None:
            admin.permissions.remove(perm)


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0001_initial"),
        ("accounts", "0002_role_groups"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(grant_admin, revoke_admin)]
