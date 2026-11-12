"""The saved workspace tables, for the Firebird set: a table saved from the workspace, shared or private."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0007_workspaceversion_labels"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedTable",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, verbose_name="Нэр")),
                ("sql", models.TextField(verbose_name="SQL")),
                ("labels", models.TextField(blank=True, default="", verbose_name="Баганын нэр")),
                (
                    "author",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Зохиогч",
                    ),
                ),
                ("settings", models.TextField(blank=True, default="", verbose_name="Тохиргоо")),
                (
                    "visibility",
                    models.CharField(
                        choices=[("shared", "Хамтын"), ("private", "Хувийн")],
                        default="shared",
                        max_length=10,
                        verbose_name="Харагдах байдал",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Үүсгэсэн")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Өөрчилсөн")),
            ],
            options={
                "verbose_name": "Хадгалсан хүснэгт",
                "verbose_name_plural": "Хадгалсан хүснэгтүүд",
                "ordering": ["name"],
                "permissions": [("manage_saved_tables", "Хадгалсан хүснэгтийг устгах")],
            },
        ),
    ]
