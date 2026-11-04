from typing import Any

from django.db import migrations

# Frozen copies of the model's default permission names at the time of this migration.
CODENAMES = ("view_helpexample", "add_helpexample", "change_helpexample")
NAMES = {
    "view_helpexample": "Can view Сурсан жишээ, тест",
    "add_helpexample": "Can add Сурсан жишээ, тест",
    "change_helpexample": "Can change Сурсан жишээ, тест",
}


def grant_admin(apps: Any, schema_editor: Any) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="assistant", model="helpexample")
    # Permission rows of a new model are created after all migrations; create them here too.
    perms = [
        Permission.objects.get_or_create(codename=codename, content_type=ct, defaults={"name": NAMES[codename]})[0]
        for codename in CODENAMES
    ]
    admin = Group.objects.filter(name="Admin").first()
    if admin is not None:  # no Admin group (fresh or edited database): nothing to grant
        admin.permissions.add(*perms)


def revoke_admin(apps: Any, schema_editor: Any) -> None:
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    perms = Permission.objects.filter(codename__in=CODENAMES, content_type__app_label="assistant")
    for admin in Group.objects.filter(name="Admin"):
        admin.permissions.remove(*perms)


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0003_helpexample_allowed_entries"),
        ("accounts", "0002_role_groups"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(grant_admin, revoke_admin)]
