"""Which optional modules are on or off (accounts/modules.py): one JSON text on CompanySettings."""

import django.db.models.deletion  # noqa: F401
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0029_selfform"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="modules",
            field=models.TextField(blank=True, default="{}", verbose_name="Модулиуд"),
        ),
    ]
