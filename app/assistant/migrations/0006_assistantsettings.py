from typing import Any

import django.core.validators
from django.db import migrations, models

# Frozen copies of the model's default permission names at the time of this migration.
CODENAMES = ("view_assistantsettings", "change_assistantsettings")
NAMES = {
    "view_assistantsettings": "Can view Туслахын тохиргоо",
    "change_assistantsettings": "Can change Туслахын тохиргоо",
}


def grant_admin(apps: Any, schema_editor: Any) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="assistant", model="assistantsettings")
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
        ("assistant", "0005_alter_helpquestion_allowed"),
        ("accounts", "0002_role_groups"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "provider",
                    models.CharField(
                        blank=True,
                        choices=[("claude", "Claude (Anthropic)"), ("gemini", "Gemini (Google)"), ("groq", "Groq")],
                        max_length=20,
                        verbose_name="Үйлчилгээ үзүүлэгч",
                    ),
                ),
                ("api_key", models.CharField(blank=True, max_length=300, verbose_name="API түлхүүр")),
                ("model", models.CharField(blank=True, max_length=60, verbose_name="Загвар")),
                (
                    "timeout",
                    models.PositiveSmallIntegerField(
                        default=15,
                        validators=[
                            django.core.validators.MinValueValidator(3),
                            django.core.validators.MaxValueValidator(60),
                        ],
                        verbose_name="Хугацааны хязгаар (секунд)",
                    ),
                ),
            ],
            options={"verbose_name": "Туслахын тохиргоо", "verbose_name_plural": "Туслахын тохиргоо"},
        ),
        migrations.RunPython(grant_admin, revoke_admin),
    ]
