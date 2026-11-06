"""Firebird safety net for the history no-overlap rule (plan Task 7b).

The app's lock row (HistoryLock, taken first in every history write) is what serialises two writers.
Firebird 3 snapshot isolation cannot make a trigger see another transaction's uncommitted row, so the
trigger alone cannot hold the rule. See docs/migration/overlap-guard-spike.md.

This trigger only refuses an overlap that the application check missed: a write that skipped the lock
row, or a row committed before this insert started under READ COMMITTED.

Periods are half-open: [START_DATE, END_DATE). A NULL END_DATE is open-ended. Two rows overlap when each
starts before the other ends, so rows that only touch (one ends on the day the next starts) are allowed.
Firebird DATE is a TIMESTAMP in dialect 1, so the open-ended sentinel is a TIMESTAMP too.

Both steps run on Firebird only. PostgreSQL keeps its own exclusion constraint.
"""

from django.db import migrations

EXCEPTION_NAME = "IHR_HISTORY_OVERLAP"
FAR_FUTURE = "CAST('9999-12-31' AS TIMESTAMP)"
TRIGGERS = (
    ("JobRecord", "IHR_JOB_OVERLAP"),
    ("SalaryRecord", "IHR_SAL_OVERLAP"),
)


def _trigger_sql(table: str, trigger: str) -> str:
    # NEW.ID IS NULL: on an insert the generator may not have set the id yet, so no row is excluded.
    return f"""CREATE TRIGGER {trigger} FOR {table}
ACTIVE BEFORE INSERT OR UPDATE POSITION 0 AS
BEGIN
  IF (EXISTS (SELECT 1 FROM {table} OTHER_ROW
              WHERE OTHER_ROW.EMPLOYEE_ID = NEW.EMPLOYEE_ID
                AND (NEW.ID IS NULL OR OTHER_ROW.ID <> NEW.ID)
                AND OTHER_ROW.START_DATE < COALESCE(NEW.END_DATE, {FAR_FUTURE})
                AND COALESCE(OTHER_ROW.END_DATE, {FAR_FUTURE}) > NEW.START_DATE)) THEN
    EXCEPTION {EXCEPTION_NAME};
END"""  # noqa: S608 (identifiers come from model metadata, not user input)


def create_guard(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "firebird":
        return
    schema_editor.execute(f"CREATE EXCEPTION {EXCEPTION_NAME} 'Employee history periods overlap'")
    for model_name, trigger in TRIGGERS:
        model = apps.get_model("employees", model_name)
        table = connection.ops.quote_name(model._meta.db_table)
        schema_editor.execute(_trigger_sql(table, trigger))


def drop_guard(apps, schema_editor):
    if schema_editor.connection.vendor != "firebird":
        return
    for _model_name, trigger in reversed(TRIGGERS):
        schema_editor.execute(f"DROP TRIGGER {trigger}")
    schema_editor.execute(f"DROP EXCEPTION {EXCEPTION_NAME}")


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_guard, drop_guard),
    ]
