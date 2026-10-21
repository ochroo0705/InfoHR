import django.db.models.deletion
from django.db import migrations, models

import macs.fields


class Migration(migrations.Migration):
    """Leaving reason list (fired_reason), leave flags and death flag on employee, and the leaving date and
    reason on employee_history (unmanaged tables: state only, no SQL)."""

    dependencies = [
        ("macs", "0003_insurance_probation_columns"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="FiredReason",
                    fields=[
                        ("id", models.AutoField(db_column="firedreason_id", primary_key=True, serialize=False)),
                        ("name", models.CharField(db_column="description", max_length=100, verbose_name="Нэр")),
                    ],
                    options={
                        "verbose_name": "Ажлаас гарсан шалтгаан",
                        "db_table": "fired_reason",
                        "ordering": ["name"],
                        "managed": False,
                    },
                ),
                migrations.AddField(
                    model_name="employee",
                    name="fired_reason",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="firedreason_ident",
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="macs.firedreason",
                        verbose_name="Ажлаас гарсан шалтгаан",
                    ),
                ),
                migrations.AddField(
                    model_name="employee",
                    name="taken_leave",
                    field=models.SmallIntegerField(
                        blank=True, db_column="taken_leave", null=True, verbose_name="Урт амралттай"
                    ),
                ),
                migrations.AddField(
                    model_name="employee",
                    name="leave_type",
                    field=models.SmallIntegerField(
                        blank=True, db_column="leave_type", null=True, verbose_name="Амралтын төрөл"
                    ),
                ),
                migrations.AddField(
                    model_name="employee",
                    name="died",
                    field=models.CharField(db_column="died", default="no", max_length=12),
                ),
                migrations.AddField(
                    model_name="employeehistory",
                    name="fired_date",
                    field=macs.fields.TimestampDateField(db_column="fired_date", null=True),
                ),
                migrations.AddField(
                    model_name="employeehistory",
                    name="fired_reason_id_value",
                    field=models.IntegerField(db_column="firedreason_ident", null=True),
                ),
            ],
            database_operations=[],
        ),
    ]
