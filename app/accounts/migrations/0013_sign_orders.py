from typing import Any

from django.db import migrations

# Frozen copy of the new switch (accounts.roles.SWITCHES / accounts.models.User.Meta) at the time of this migration.
CODENAME = "sign_orders"
NAME = "Тушаалд дэлгэц дээр гарын үсэг зурах"


def grant_admin(apps: Any, schema_editor: Any) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="accounts", model="user")
    # Permission rows of a new Meta permission are created after all migrations; create it here too.
    perm, _ = Permission.objects.get_or_create(codename=CODENAME, content_type=ct, defaults={"name": NAME})
    admin = Group.objects.filter(name="Admin").first()
    if admin is not None:  # no Admin group (fresh or edited database): nothing to grant
        admin.permissions.add(perm)


def revoke_admin(apps: Any, schema_editor: Any) -> None:
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    perm = Permission.objects.filter(codename=CODENAME, content_type__app_label="accounts").first()
    for admin in Group.objects.filter(name="Admin"):
        if perm is not None:
            admin.permissions.remove(perm)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0012_systemlogentry_change_text"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "permissions": [
                    ("approve_leave", "Чөлөө, амралт батлах"),
                    ("issue_orders", "Тушаал гаргах / баталгаажуулах"),
                    ("export_lists", "Жагсаалтыг Excel рүү гаргах"),
                    ("view_audit", "Үйл ажиллагааны бүртгэл харах"),
                    ("sign_orders", "Тушаалд дэлгэц дээр гарын үсэг зурах"),
                ],
                "verbose_name": "user",
                "verbose_name_plural": "users",
            },
        ),
        migrations.RunPython(grant_admin, revoke_admin),
    ]
