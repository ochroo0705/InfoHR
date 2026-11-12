"""The assistant workspace: tabs, their saved SQL versions and chat messages (workspace Task 3)."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0015_verifiedquery"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkspaceTab",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=80, verbose_name="Гарчиг")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Үүсгэсэн")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Өөрчилсөн")),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_tabs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Эзэмшигч",
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="workspace_tabs",
                        to="assistant.helpquestion",
                        verbose_name="Эх асуулт",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ажлын хуудасны таб",
                "verbose_name_plural": "Ажлын хуудасны табууд",
                "ordering": ["created_at"],
            },
        ),
        migrations.CreateModel(
            name="WorkspaceVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.TextField(verbose_name="Асуулт")),
                ("sql", models.TextField(verbose_name="SQL")),
                ("settings", models.TextField(default="", verbose_name="Тохиргоо")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Үүсгэсэн")),
                (
                    "tab",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="versions",
                        to="assistant.workspacetab",
                        verbose_name="Таб",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ажлын хуудасны хувилбар",
                "verbose_name_plural": "Ажлын хуудасны хувилбарууд",
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="WorkspaceMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "role",
                    models.CharField(
                        choices=[("user", "Хэрэглэгч"), ("assistant", "Туслах")],
                        max_length=10,
                        verbose_name="Үүрэг",
                    ),
                ),
                ("text", models.TextField(verbose_name="Текст")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Үүсгэсэн")),
                (
                    "tab",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="assistant.workspacetab",
                        verbose_name="Таб",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ажлын хуудасны мессеж",
                "verbose_name_plural": "Ажлын хуудасны мессежүүд",
                "ordering": ["id"],
            },
        ),
    ]
