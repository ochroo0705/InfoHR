# Hand-written: Django's autodetector skips unmanaged models, so makemigrations emits nothing for this.
# AddField on an unmanaged model only updates migration state; no table is created or altered.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("macs", "0024_phase5_mirrors"),
    ]

    operations = [
        migrations.AddField(
            model_name="department",
            name="parent_id_value",
            field=models.SmallIntegerField(blank=True, db_column="parent_id", null=True),
        ),
    ]
