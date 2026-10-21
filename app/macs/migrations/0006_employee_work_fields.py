import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """QC 4c: branch lookup (production branch), last order number and text, and the labels/choices of
    sector years, foreign flag and leave type. Unmanaged tables: state only, no SQL (check with sqlmigrate)."""

    dependencies = [
        ("macs", "0005_employee_screen_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="Branch",
            fields=[
                ("id", models.AutoField(db_column="branch_id", primary_key=True, serialize=False)),
                ("name", models.CharField(db_column="description", max_length=25, verbose_name="Салбар")),
                ("status", models.SmallIntegerField(db_column="status", default=1)),
            ],
            options={
                "verbose_name": "Салбар",
                "db_table": "branch",
                "ordering": ["name"],
                "abstract": False,
                "managed": False,
            },
        ),
        migrations.AlterField(
            model_name="employee",
            name="sector_years",
            field=models.SmallIntegerField(
                db_column="workyear_sector", default=0, verbose_name="Салбарт ажилласан жил"
            ),
        ),
        migrations.AlterField(
            model_name="employee",
            name="foreign_emp",
            field=models.SmallIntegerField(blank=True, db_column="foreign_emp", null=True, verbose_name="Гадаад иргэн"),
        ),
        migrations.AlterField(
            model_name="employee",
            name="leave_type",
            field=models.SmallIntegerField(
                blank=True,
                choices=[(1, "Цалингүй"), (2, "Хүүхэд асрах"), (3, "Жирэмсний амралт")],
                db_column="leave_type",
                null=True,
                verbose_name="Амралтын төрөл",
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="branch",
            field=models.ForeignKey(
                blank=True,
                db_column="branch_ident",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="macs.branch",
                verbose_name="Салбар",
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="last_order_no",
            field=models.CharField(
                blank=True, db_column="command_no", max_length=10, null=True, verbose_name="Сүүлийн тушаалын дугаар"
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="last_order_text",
            field=models.CharField(
                blank=True,
                db_column="command_description",
                max_length=100,
                null=True,
                verbose_name="Сүүлийн тушаалын агуулга",
            ),
        ),
    ]
