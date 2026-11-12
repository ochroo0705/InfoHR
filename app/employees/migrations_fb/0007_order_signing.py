"""On-screen order signing on Firebird (order-signing board, Task 3): the SavedSignature and OrderSigning tables.

The same operations as the PostgreSQL 0031_order_signing, written for the Firebird initial set. Column names are
checked against infohr_firebird.reserved (ORDER and USER are reserved words, but the columns here are order_id and
user_id, which are not). The migration is atomic: it has no data step.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import employees.models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0006_companysettings_modules"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedSignature",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "image",
                    models.FileField(
                        storage=employees.models.order_storage,
                        upload_to="signatures/",
                        verbose_name="Гарын үсгийн зураг",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Шинэчилсэн")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saved_signature",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Хэрэглэгч",
                    ),
                ),
            ],
            options={
                "verbose_name": "Хадгалсан гарын үсэг",
                "verbose_name_plural": "Хадгалсан гарын үсгүүд",
                "default_permissions": (),
            },
        ),
        migrations.CreateModel(
            name="OrderSigning",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("signer_name", models.CharField(max_length=100, verbose_name="Гарын үсэг зурсан нэр")),
                ("signed_at", models.DateTimeField(verbose_name="Гарын үсэг зурсан огноо")),
                (
                    "method",
                    models.CharField(
                        choices=[("saved", "Хадгалсан гарын үсэг"), ("drawn", "Шинээр зурсан гарын үсэг")],
                        max_length=8,
                        verbose_name="Арга",
                    ),
                ),
                (
                    "image",
                    models.FileField(
                        storage=employees.models.order_storage,
                        upload_to="signing/%Y/",
                        verbose_name="Гарын үсгийн зураг",
                    ),
                ),
                ("pdf_sha256", models.CharField(max_length=64, verbose_name="Тушаалын PDF-ийн хэш")),
                (
                    "order",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="signing",
                        to="employees.hrorder",
                        verbose_name="Тушаал",
                    ),
                ),
                (
                    "signer",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Гарын үсэг зурсан хэрэглэгч",
                    ),
                ),
            ],
            options={
                "verbose_name": "Тушаалын гарын үсэг",
                "verbose_name_plural": "Тушаалын гарын үсгүүд",
                "default_permissions": (),
            },
        ),
    ]
