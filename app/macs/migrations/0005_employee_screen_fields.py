import django.db.models.deletion
from django.db import migrations, models


def _fk(to: str, column: str, label: str) -> models.ForeignKey:  # type: ignore[type-arg]
    return models.ForeignKey(
        blank=True,
        db_column=column,
        null=True,
        on_delete=django.db.models.deletion.DO_NOTHING,
        related_name="+",
        to=to,
        verbose_name=label,
    )


class Migration(migrations.Migration):
    """Old employee screen fields: second phone, job type/form, second position, office, section, and the
    birth place table (unmanaged tables: state only, no SQL)."""

    dependencies = [
        ("macs", "0004_history_events_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="Office",
            fields=[
                ("id", models.AutoField(db_column="office_id", primary_key=True, serialize=False)),
                ("name", models.CharField(db_column="name", max_length=100, verbose_name="Нэр")),
            ],
            options={
                "verbose_name": "Алба",
                "db_table": "hr_office",
                "ordering": ["name"],
                "abstract": False,
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="Section",
            fields=[
                ("id", models.AutoField(db_column="section_id", primary_key=True, serialize=False)),
                ("name", models.CharField(db_column="name", max_length=100, verbose_name="Нэр")),
            ],
            options={
                "verbose_name": "Хэсэг",
                "db_table": "hr_section",
                "ordering": ["name"],
                "abstract": False,
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="BirthPlace",
            fields=[
                ("id", models.AutoField(db_column="birth_place_id", primary_key=True, serialize=False)),
                (
                    "employee",
                    models.ForeignKey(
                        db_column="emp_id",
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="macs.employee",
                    ),
                ),
                (
                    "city",
                    models.ForeignKey(
                        db_column="city_id",
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="macs.city",
                    ),
                ),
                (
                    "district",
                    models.ForeignKey(
                        blank=True,
                        db_column="district_id",
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="macs.district",
                    ),
                ),
                ("description", models.CharField(blank=True, db_column="description", max_length=50, null=True)),
            ],
            options={
                "db_table": "birth_place",
                "abstract": False,
                "managed": False,
            },
        ),
        migrations.AddField(
            model_name="employee",
            name="phone2",
            field=models.CharField(blank=True, db_column="phone2", max_length=14, null=True, verbose_name="Утас #2"),
        ),
        migrations.AddField(
            model_name="employee",
            name="second_position",
            field=_fk("macs.position", "occupation_ident2", "Албан тушаал (хавсарсан)"),
        ),
        migrations.AddField(
            model_name="employee",
            name="office",
            field=_fk("macs.office", "office_ident", "Алба"),
        ),
        migrations.AddField(
            model_name="employee",
            name="section",
            field=_fk("macs.section", "section_ident", "Хэсэг"),
        ),
        migrations.AddField(
            model_name="employee",
            name="job_type",
            field=models.CharField(
                blank=True,
                choices=[("NonSesional", "Тогтмол"), ("Sesional", "Улирлын")],
                db_column="job_type",
                max_length=20,
                null=True,
                verbose_name="Ажлын төрөл",
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="job_figure",
            field=models.CharField(
                choices=[("Main", "Үндсэн"), ("Temporary", "Түр")],
                db_column="job_figure",
                default="Main",
                max_length=20,
                null=True,
                verbose_name="Ажлын хэлбэр",
            ),
        ),
    ]
