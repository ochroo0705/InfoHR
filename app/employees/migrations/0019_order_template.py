# Written by hand: `makemigrations` refuses on the dev database (inconsistent migration history, COWORK).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import employees.models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0018_order_requirements"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OrderTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "order_type",
                    models.IntegerField(
                        choices=[
                            (1, "Ажилд орсон"),
                            (2, "Хэлтэс, салбар шилжсэн"),
                            (3, "Албан тушаал сольсон"),
                            (4, "Ажлаас гарсан"),
                            (5, "Тэтгэвэрт гарсан"),
                            (6, "Төрөл солигдсон"),
                        ],
                        unique=True,
                        verbose_name="Тушаалын төрөл",
                    ),
                ),
                (
                    "file",
                    models.FileField(
                        blank=True,
                        storage=employees.models.order_storage,
                        upload_to="templates/",
                        verbose_name="Загварын файл (.docx)",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Шинэчилсэн")),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Тушаалын загвар",
                "verbose_name_plural": "Тушаалын загварууд",
                "ordering": ["order_type"],
                "default_permissions": ("change", "view"),
            },
        ),
    ]
