"""HrOrder.state defaults to registered (D-083), for the Firebird initial set. Same as PostgreSQL 0038."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0013_companysettings_report_corrections"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hrorder",
            name="state",
            field=models.CharField(
                choices=[
                    ("pending", "Дугаар оруулаагүй"),
                    ("registered", "Бүртгэсэн"),
                    ("signed", "Гарын үсэгтэй"),
                    ("cancelled", "Цуцалсан"),
                ],
                default="registered",
                max_length=12,
                verbose_name="Төлөв",
            ),
        ),
    ]
