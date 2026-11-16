"""CompanySettings: the letterhead (бланк) logo, text lines and layout presets.

The same operations as the PostgreSQL 0035_letterhead_company_fields, written for the Firebird initial set.
"""

from django.db import migrations, models

import employees.models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0010_staffimportdraft_list_results"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="letterhead_logo",
            field=models.FileField(
                blank=True,
                help_text="PNG эсвэл JPG, 2 МБ-аас ихгүй.",
                storage=employees.models.order_storage,
                upload_to="letterhead/",
                verbose_name="Бланкны лого",
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="letterhead_lines",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Хаяг, утас, имэйл, регистрийн дугаар гэх мэт. Нэг мөрөнд нэг мэдээлэл. "
                    "{company_name} гэж бичвэл байгууллагын нэр, {director_name} гэж бичвэл захирлын нэр орно."
                ),
                verbose_name="Бланкны мөрүүд",
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="letterhead_logo_place",
            field=models.CharField(
                choices=[
                    ("left", "Логоны зүүн талд, текст баруун талд"),
                    ("right", "Логоны баруун талд, текст зүүн талд"),
                    ("top", "Лого дээр, текст доор"),
                    ("logo_only", "Зөвхөн лого"),
                ],
                default="left",
                max_length=10,
                verbose_name="Логоны байрлал",
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="letterhead_text_align",
            field=models.CharField(
                choices=[("left", "Зүүн"), ("center", "Голлуулах"), ("right", "Баруун")],
                default="left",
                max_length=6,
                verbose_name="Текстийн байрлал",
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="letterhead_logo_size",
            field=models.CharField(
                choices=[("small", "Жижиг"), ("medium", "Дунд"), ("large", "Том")],
                default="medium",
                max_length=6,
                verbose_name="Логоны хэмжээ",
            ),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="letterhead_rule",
            field=models.BooleanField(default=True, verbose_name="Бланкны доор зураас зурах"),
        ),
        migrations.AddField(
            model_name="companysettings",
            name="letterhead_every_page",
            field=models.BooleanField(
                default=False,
                help_text="Үгүй бол бланк зөвхөн эхний хуудсанд гарна.",
                verbose_name="Хуудас бүрт давтах",
            ),
        ),
    ]
