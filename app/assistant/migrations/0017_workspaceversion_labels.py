"""The Mongolian column headings the model gave for a workspace version (ws_sql labels, Task 2)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0016_workspace"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspaceversion",
            name="labels",
            field=models.TextField(blank=True, default="", verbose_name="Баганын нэр"),
        ),
    ]
