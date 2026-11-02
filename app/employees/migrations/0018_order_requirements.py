# Written by hand: `makemigrations` refuses on the dev database (inconsistent migration history, COWORK).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0017_staff_import"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="order_hired",
            field=models.BooleanField(
                default=True,
                verbose_name="Ажилд орсон",
                help_text="Хөдөлмөрийн практикт ажилд авах нь тушаалаар батлагддаг.",
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="order_department",
            field=models.BooleanField(default=True, verbose_name="Хэлтэс, салбар шилжсэн"),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="order_position",
            field=models.BooleanField(default=True, verbose_name="Албан тушаал сольсон"),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="order_fired",
            field=models.BooleanField(
                default=True,
                verbose_name="Ажлаас гарсан",
                help_text="Хөдөлмөрийн практикт ажлаас чөлөөлөх нь тушаалаар батлагддаг.",
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="order_pension",
            field=models.BooleanField(default=True, verbose_name="Тэтгэвэрт гарсан"),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="order_type_changed",
            field=models.BooleanField(default=True, verbose_name="Төрөл солигдсон"),
        ),
    ]
