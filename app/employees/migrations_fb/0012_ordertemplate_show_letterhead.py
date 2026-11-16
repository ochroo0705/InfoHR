"""OrderTemplate.show_letterhead: the per-template letterhead switch, for the Firebird initial set.

The same operations as the PostgreSQL 0036_ordertemplate_show_letterhead.
"""

from django.apps.registry import Apps
from django.db import migrations, models


def turn_off_for_uploaded(apps: Apps, schema_editor: object) -> None:
    """Rows that already have their own .docx file get the switch off; rows on the starter keep it on."""
    apps.get_model("employees", "OrderTemplate").objects.exclude(file="").update(show_letterhead=False)


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0011_letterhead_company_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordertemplate",
            name="show_letterhead",
            field=models.BooleanField(default=True, verbose_name="Бланк дээр гаргах"),
        ),
        migrations.RunPython(turn_off_for_uploaded, migrations.RunPython.noop),
    ]
