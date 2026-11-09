"""Which optional modules are on or off (accounts/modules.py), for the Firebird initial set."""

import django.db.models.deletion  # noqa: F401
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0005_selfform"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="modules",
            field=models.TextField(blank=True, default="{}", verbose_name="Модулиуд"),
        ),
    ]
