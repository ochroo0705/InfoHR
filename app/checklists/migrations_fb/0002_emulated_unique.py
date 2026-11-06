"""Firebird emulation of the two conditional unique rules of checklists (plan Task 7b).

Firebird cannot create a partial unique index, so the 0001 initial leaves both rules out. Each rule in
infohr_firebird.emulated.EMULATED becomes a UNIQUE index over a COMPUTED BY expression here. Firebird only;
PostgreSQL creates the real partial constraints in its own migrations.
"""

from django.db import migrations
from infohr_firebird.emulated import EMULATED, create_sql, drop_sql


def create_emulated(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "firebird":
        return
    for spec in EMULATED.values():
        app_label, model_name = spec.model_label.split(".")
        model = apps.get_model(app_label, model_name)
        table = connection.ops.quote_name(model._meta.db_table)
        schema_editor.execute(create_sql(table, spec))


def drop_emulated(apps, schema_editor):
    if schema_editor.connection.vendor != "firebird":
        return
    for spec in EMULATED.values():
        schema_editor.execute(drop_sql(spec))


class Migration(migrations.Migration):
    dependencies = [
        ("checklists", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_emulated, drop_emulated),
    ]
