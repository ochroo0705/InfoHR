"""The verified query table: an answer the asker marked as correct, waiting for review (Task 15a), for the Firebird set."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0004_governed_sql_log"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VerifiedQuery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.CharField(max_length=300, verbose_name="Асуулт")),
                ("sql", models.TextField(verbose_name="SQL")),
                ("views", models.CharField(blank=True, max_length=200, verbose_name="Хүснэгтүүд")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("proposed", "Шалгагдаж буй"),
                            ("approved", "Зөвшөөрсөн"),
                            ("rejected", "Татгалзсан"),
                        ],
                        default="proposed",
                        max_length=10,
                        verbose_name="Төлөв",
                    ),
                ),
                ("reviewed_at", models.DateTimeField(blank=True, null=True, verbose_name="Шалгасан")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="Тэмдэглэл")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Санал болгосон"),
                ),
                (
                    "proposed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="verified_queries",
                        to="assistant.helpquestion",
                    ),
                ),
            ],
            options={
                "verbose_name": "Баталгаажуулсан асуулт",
                "verbose_name_plural": "Баталгаажуулсан асуултууд",
                "ordering": ["-created_at"],
            },
        ),
    ]
