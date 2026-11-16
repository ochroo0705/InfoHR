"""The chart spec the model gave for a workspace version, kept with the version (JSON text) (Firebird set)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0009_helpquestion_sql_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspaceversion",
            name="chart",
            field=models.TextField(blank=True, default="", verbose_name="График"),
        ),
    ]
