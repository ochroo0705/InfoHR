"""SavedView visibility, default flag and longer query on Firebird (reports part 1, task 8).

Same schema change as the PostgreSQL migration reports 0003. Firebird needs no special handling here: there is no
backfill, so the migration stays atomic (unlike accounts 0003 and employees 0004, which fill old rows). The two new
columns get their defaults ('shared' and false) on the existing rows when they are added. The query column grows
from VARCHAR(2000) to VARCHAR(4000), which Firebird does as an ALTER COLUMN TYPE. Reversing the migration drops the
two new columns and shrinks the query column back to 2000 characters; a stored query longer than 2000 characters
would then fail that reverse step, so back up before reversing on a database that holds such rows.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0002_seed"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedview",
            name="is_default",
            field=models.BooleanField(default=False, verbose_name="Үндсэн"),
        ),
        migrations.AddField(
            model_name="savedview",
            name="visibility",
            field=models.CharField(
                choices=[("shared", "Хамтын"), ("private", "Хувийн")],
                default="shared",
                max_length=10,
                verbose_name="Харагдах байдал",
            ),
        ),
        migrations.AlterField(
            model_name="savedview",
            name="query",
            field=models.CharField(blank=True, max_length=4000),
        ),
    ]
