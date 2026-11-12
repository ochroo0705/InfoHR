from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0031_order_signing"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="soon_days",
            field=models.PositiveSmallIntegerField(
                default=30,
                help_text="Гэрээ эсвэл туршилтын хугацаа дуусах хугацаанд хэдэн хоногийн өмнөөс «дөхсөн» гэж тооцохыг заана. 1-365 хоног.",
                verbose_name="«Дөхсөн» гэж тооцох хоног",
            ),
        ),
    ]
