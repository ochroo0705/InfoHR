from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0037_companysettings_report_corrections"),
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
