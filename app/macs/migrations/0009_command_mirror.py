import django.db.models.deletion
from django.db import migrations, models

import macs.fields


class Migration(migrations.Migration):
    """HR orders: production `command` mirror, and the order columns of employee / employee_history.
    Unmanaged tables: state only, no SQL (check with sqlmigrate)."""

    dependencies = [
        ("macs", "0008_personal_tabs_mirrors"),
    ]

    operations = [
        migrations.CreateModel(
            name="Command",
            fields=[
                ("id", models.AutoField(db_column="command_id", primary_key=True, serialize=False)),
                ("summary", models.CharField(blank=True, db_column="command", max_length=50, null=True)),
                ("date", macs.fields.TimestampDateField(db_column="outdate", null=True)),
                ("issued_by", models.CharField(blank=True, db_column="human_command", max_length=25, null=True)),
                ("number", models.CharField(db_column="commandno", max_length=10)),
                ("path", models.CharField(blank=True, db_column="path", max_length=100, null=True)),
                ("order_type", models.SmallIntegerField(blank=True, db_column="command_type", null=True)),
            ],
            options={
                "verbose_name": "Тушаал",
                "verbose_name_plural": "Тушаалууд",
                "db_table": "command",
                "abstract": False,
                "managed": False,
            },
        ),
        migrations.AddField(
            model_name="command",
            name="employee",
            field=models.ForeignKey(
                db_column="employee_ident",
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="macs.employee",
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="command_id_value",
            field=models.IntegerField(blank=True, db_column="command_ident", null=True),
        ),
        migrations.AddField(
            model_name="employee",
            name="move_type",
            field=models.SmallIntegerField(blank=True, db_column="move_type", null=True),
        ),
        migrations.AddField(
            model_name="employeehistory",
            name="branch_id_value",
            field=models.IntegerField(blank=True, db_column="branch_ident", null=True),
        ),
        migrations.AddField(
            model_name="employeehistory",
            name="move_type",
            field=models.SmallIntegerField(blank=True, db_column="move_type", null=True),
        ),
        migrations.AddField(
            model_name="employeehistory",
            name="command_id_value",
            field=models.IntegerField(blank=True, db_column="command_ident", null=True),
        ),
    ]
