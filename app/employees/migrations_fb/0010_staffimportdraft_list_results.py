"""StaffImportDraft.list_results: how many rows each list sheet of a staff import added and refused."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0009_companysettings_governed_sql"),
    ]

    operations = [
        migrations.AddField(
            model_name="staffimportdraft",
            name="list_results",
            field=models.JSONField(blank=True, default=dict, verbose_name="Жагсаалтын хуудсын үр дүн"),
        ),
    ]
