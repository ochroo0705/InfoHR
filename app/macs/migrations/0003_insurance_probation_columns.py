import django.db.models.deletion
from django.db import migrations, models

import macs.fields


class Migration(migrations.Migration):
    """Salary/insurance fields and probation months become production employee columns
    (unmanaged table: state only, no SQL)."""

    dependencies = [
        ("macs", "0002_employee_bank"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="social_insurance_no",
            field=models.CharField(
                blank=True, db_column="ndno", max_length=14, null=True, verbose_name="НДД-ийн дугаар"
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="health_insurance_no",
            field=models.CharField(
                blank=True, db_column="emdno", max_length=14, null=True, verbose_name="ЭМДД-ийн дугаар"
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="insured_category",
            field=models.ForeignKey(
                blank=True,
                db_column="insur_ident",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="macs.insuredcategory",
                verbose_name="Даатгуулагчийн төрөл",
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="taxpayer_no",
            field=models.CharField(
                blank=True, db_column="etax_code", max_length=30, null=True, verbose_name="Татвар төлөгчийн дугаар"
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="has_disability",
            field=macs.fields.SmallintFlagField(
                db_column="disabled_emp", default=False, verbose_name="Хөгжлийн бэрхшээлтэй"
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="probation_months",
            field=models.SmallIntegerField(blank=True, db_column="test_month", null=True, verbose_name="Туршилтын сар"),
        ),
    ]
