"""SystemLogEntry.change_text on Firebird (plan 5, task 5b): the folded plain-text copy of the changes, for search.

Same shape as employees 0004_activityentry_change_text: the column is added, then logs.foldtext.backfill fills the
older rows, 500 per transaction. The migration is not atomic, so each batch commits on its own (Firebird refuses a
waiting writer after 3 s). The reverse of the backfill is a no-op; reversing the migration drops the column.

Recovery, if the backfill was interrupted (the column exists but the migration is not recorded as applied). Run
these from the app folder, with DB_ENGINE=firebird and the Firebird settings in place (in .env, or in PowerShell
`$env:DB_ENGINE='firebird'`):
  1. Fill the rows that are still blank. It prints the number of rows it wrote, and running it again is safe: it
     only touches rows whose change_text is blank.
       ..\\.venv\\Scripts\\python manage.py shell -c "from accounts.models import SystemLogEntry; from logs.foldtext import backfill; print(backfill(SystemLogEntry))"
  2. Record the migration as applied, without running its operations again:
       ..\\.venv\\Scripts\\python manage.py migrate accounts 0003 --fake
Do not run `migrate accounts` from the top in that state: the AddField would fail because the column exists.
"""

from django.apps.registry import Apps
from django.db import migrations, models
from logs.foldtext import backfill


def fill_change_text(apps: Apps, schema_editor: object) -> None:
    backfill(apps.get_model("accounts", "SystemLogEntry"))


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("accounts", "0002_seed"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemlogentry",
            name="change_text",
            field=models.TextField(blank=True, default="", editable=False),
        ),
        migrations.RunPython(fill_change_text, migrations.RunPython.noop),
    ]
