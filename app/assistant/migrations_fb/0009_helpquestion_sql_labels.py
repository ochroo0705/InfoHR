"""The Mongolian column headings the model gave for a governed SQL answer, kept so the workspace tab opens with them (Firebird set)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0008_savedtable"),
    ]

    operations = [
        migrations.AddField(
            model_name="helpquestion",
            name="sql_labels",
            field=models.TextField(blank=True, default="", verbose_name="Баганын нэр"),
        ),
    ]
