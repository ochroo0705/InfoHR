"""ActivityEntry.change_text on Firebird (plan 5, task 5b): the folded plain-text copy of the changes, for search.

The column is added, then the rows written before it existed are filled by logs.foldtext.backfill: 500 rows per
transaction. The migration is not atomic on purpose. Inside one transaction the backfill would hold the row locks of
the whole table until the end, and Firebird refuses a waiting writer after 3 s. Each batch commits on its own.
If the backfill is interrupted, the column already exists: the migration is then not recorded and must be finished
by hand rather than run again from the top. The reverse of the backfill is a no-op; reversing
the migration drops the column.

Recovery, if the backfill was interrupted (the column exists but the migration is not recorded as applied). Run
these from the app folder, with DB_ENGINE=firebird and the Firebird settings in place (in .env, or in PowerShell
`$env:DB_ENGINE='firebird'`):
  1. Fill the rows that are still blank. It prints the number of rows it wrote, and running it again is safe: it
     only touches rows whose change_text is blank.
       ..\\.venv\\Scripts\\python manage.py shell -c "from employees.models import ActivityEntry; from logs.foldtext import backfill; print(backfill(ActivityEntry))"
  2. Record the migration as applied, without running its operations again:
       ..\\.venv\\Scripts\\python manage.py migrate employees 0004 --fake
Do not run `migrate employees` from the top in that state: the AddField would fail because the column exists.
"""

from django.apps.registry import Apps
from django.db import migrations, models
from logs.foldtext import backfill


def fill_change_text(apps: Apps, schema_editor: object) -> None:
    backfill(apps.get_model("employees", "ActivityEntry"))


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("employees", "0003_seed"),
    ]

    operations = [
        migrations.AddField(
            model_name="activityentry",
            name="change_text",
            field=models.TextField(blank=True, default="", editable=False),
        ),
        migrations.RunPython(fill_change_text, migrations.RunPython.noop),
    ]
