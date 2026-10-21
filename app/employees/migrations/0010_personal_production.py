import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0009_dailysync"),
        ("macs", "0008_personal_tabs_mirrors"),
    ]

    operations = [
        migrations.DeleteModel(name="FamilyMember"),
        migrations.DeleteModel(name="Education"),
        migrations.DeleteModel(name="Talent"),
        migrations.DeleteModel(name="Gift"),
        migrations.RemoveField(model_name="employeeext", name="address"),
        migrations.RemoveField(model_name="employeeext", name="emergency_name"),
        migrations.RemoveField(model_name="employeeext", name="emergency_phone"),
        migrations.CreateModel(
            name="EducationExt",
            fields=[
                (
                    "educ",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        primary_key=True,
                        related_name="ext",
                        serialize=False,
                        to="macs.educrow",
                    ),
                ),
                ("school", models.CharField(blank=True, max_length=200, verbose_name="Сургууль")),
                ("field", models.CharField(blank=True, max_length=150, verbose_name="Мэргэжил")),
                (
                    "graduation_year",
                    models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Төгссөн он"),
                ),
            ],
            options={
                "db_table": "employees_educationext",
            },
        ),
        migrations.CreateModel(
            name="GiftExt",
            fields=[
                (
                    "present",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        primary_key=True,
                        related_name="ext",
                        serialize=False,
                        to="macs.presentrow",
                    ),
                ),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="Тайлбар")),
            ],
            options={
                "db_table": "employees_giftext",
            },
        ),
    ]
