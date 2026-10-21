"""Leave moves onto the production MACS tables (D-017).

Adds the extension tables (schema hr) keyed by production rows, and drops the old
HR-owned leave tables. Leave permissions are re-pointed to the new LeaveExt content type
first, so group grants (Admin, HR, Accountant) survive.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def repoint_permissions(apps, schema_editor):  # type: ignore[no-untyped-def]
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    old = ContentType.objects.filter(app_label="leave", model="leave").first()
    if old is None:
        return
    new, _ = ContentType.objects.get_or_create(app_label="leave", model="leaveext")
    Permission.objects.filter(content_type=old).update(content_type=new)


class Migration(migrations.Migration):
    dependencies = [
        ("leave", "0002_seed"),
        ("macs", "0007_entitlement_leaveassign_leavetyperow_legalholiday"),
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LeaveTypeExt",
            fields=[
                (
                    "leave_type",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        primary_key=True,
                        related_name="+",
                        serialize=False,
                        to="macs.leavetyperow",
                        verbose_name="Амралтын төрөл",
                    ),
                ),
                ("is_paid", models.BooleanField(default=False, verbose_name="Цалинтай")),
                (
                    "uses_annual_balance",
                    models.BooleanField(default=False, verbose_name="Ээлжийн амралтаас хасна"),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="Идэвхтэй")),
                ("order", models.PositiveSmallIntegerField(default=0, verbose_name="Дараалал")),
            ],
            options={
                "verbose_name": "Чөлөөний төрлийн тохиргоо",
                "verbose_name_plural": "Чөлөөний төрлийн тохиргоо",
                "ordering": ["order"],
                "default_permissions": (),
            },
        ),
        migrations.CreateModel(
            name="LeaveExt",
            fields=[
                (
                    "assign",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        primary_key=True,
                        related_name="+",
                        serialize=False,
                        to="macs.leaveassign",
                        verbose_name="Ээлжийн амралт",
                    ),
                ),
                ("mistake", models.BooleanField(default=False, verbose_name="Буруу бүртгэсэн")),
                (
                    "override_reason",
                    models.CharField(blank=True, max_length=200, verbose_name="Үлдэгдэл хасах шалтгаан"),
                ),
                ("cancel_reason", models.CharField(blank=True, max_length=200, verbose_name="Цуцлах шалтгаан")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
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
                "verbose_name": "Чөлөөний нэмэлт мэдээлэл",
                "verbose_name_plural": "Чөлөөний нэмэлт мэдээлэл",
                "default_permissions": (),
                "permissions": [
                    ("view_leave", "Чөлөө харах"),
                    ("record_leave", "Чөлөө бүртгэх"),
                    ("manage_leave_settings", "Чөлөөний тохиргоо"),
                ],
            },
        ),
        migrations.CreateModel(
            name="LeaveGrantExt",
            fields=[
                (
                    "grant",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        primary_key=True,
                        related_name="+",
                        serialize=False,
                        to="macs.entitlement",
                        verbose_name="Амралтын эрх",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("auto", "Хуулийн дагуу"),
                            ("adjustment", "Гараар засвар"),
                            ("carry_over", "Шилжүүлсэн"),
                            ("manual", "Гараар оруулсан"),
                        ],
                        max_length=20,
                        verbose_name="Төрөл",
                    ),
                ),
                ("breakdown", models.CharField(blank=True, max_length=200, verbose_name="Тооцоо")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
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
                "verbose_name": "Амралтын эрхийн нэмэлт мэдээлэл",
                "verbose_name_plural": "Амралтын эрхийн нэмэлт мэдээлэл",
                "default_permissions": (),
            },
        ),
        migrations.CreateModel(
            name="LeaveSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "auto_annual_grant",
                    models.BooleanField(default=False, verbose_name="Ээлжийн амралтын эрхийг автоматаар нэмэх"),
                ),
            ],
            options={
                "verbose_name": "Чөлөөний тохиргоо",
                "verbose_name_plural": "Чөлөөний тохиргоо",
                "default_permissions": (),
            },
        ),
        migrations.RunPython(repoint_permissions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="annualleaverule",
            name="base_days",
            field=models.PositiveSmallIntegerField(verbose_name="Үндсэн амралт (ажлын өдөр)"),
        ),
        migrations.AlterField(
            model_name="annualleaverule",
            name="base_days_minor_or_disabled",
            field=models.PositiveSmallIntegerField(verbose_name="18-аас доош / хөгжлийн бэрхшээлтэй"),
        ),
        migrations.DeleteModel(name="Leave"),
        migrations.DeleteModel(name="LeaveGrant"),
        migrations.DeleteModel(name="LeaveType"),
        migrations.DeleteModel(name="Holiday"),
    ]
