"""The chart spec the model gave for a workspace version, kept with the version (JSON text)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0019_helpquestion_sql_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspaceversion",
            name="chart",
            field=models.TextField(blank=True, default="", verbose_name="График"),
        ),
    ]
