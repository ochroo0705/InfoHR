"""The TransactionTestCase flush on Firebird deletes parents only after their children (plan 6, group I).

Django's flush deletes every table of its list in one go. Firebird checks foreign keys on each DELETE, so a parent
row can be deleted only after the rows that reference it are gone. The list must hold every Django-owned table,
and the tables must be ordered children first.

The bug this guards: a table whose name is longer than 31 characters is stored shortened (with a hash) on Firebird,
and django_table_names() compared the full name with the shortened names of the database, so the table was left out
of the flush. Its rows then blocked the delete of the auth group they reference.

The flush also resets the generators (reset_sequences, Django's default): only a table with an automatic key has one,
so the reset skips the others. The flush call below runs both steps.

Each test runs the flush in a subprocess on the module's migrated copy (migrated_clone), like the other ORM tests.
"""

from typing import Any

from infohr_firebird.tests.test_settings_seam import result_of, run_django

FLUSH_CODE = """
import json
import django
django.setup()
from django.apps import apps
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.color import no_style
from django.db import connection
from checklists.models import ChecklistKind, ChecklistTemplate, ChecklistTemplateTask

child = ChecklistTemplateTask._meta.db_table
parent = Group._meta.db_table
group = Group.objects.create(name="flush_probe_group")
template = ChecklistTemplate.objects.create(kind=ChecklistKind.ONBOARDING, name="flush probe")
ChecklistTemplateTask.objects.create(template=template, title="flush probe task", group=group)

tables = connection.introspection.django_table_names(only_existing=True, include_views=False)
statements = connection.ops.sql_flush(no_style(), tables, reset_sequences=True)
delete_sql = [s for s in statements if s.startswith("DELETE FROM")]


def delete_index(name):
    # Exact match on the table name: "IHR_AUTH_GROUP" is also a prefix of IHR_AUTH_GROUP_PERMISSIONS.
    target = connection.ops.quote_name(name)
    return next((i for i, s in enumerate(delete_sql) if s.rstrip(";").split()[-1] == target), -1)


child_at = delete_index(child)
parent_at = delete_index(parent)

error = ""
try:
    call_command("flush", interactive=False, verbosity=0, inhibit_post_migrate=True)
except Exception as exc:  # the test reports the message, it does not hide it
    error = f"{exc} | cause: {exc.__context__!r}"

left = {}
for model in apps.get_models(include_auto_created=True):
    if model._meta.managed and model._meta.app_label != "macs":
        count = model.objects.count()
        if count:
            left[model._meta.db_table] = count

print("RESULT " + json.dumps({
    "child_deleted_by_flush": child_at >= 0,
    "child_before_parent": 0 <= child_at < parent_at,
    "error": error,
    "left": left,
    "deletes": delete_sql,
}))
"""


def _firebird(migrated_clone: str, code: str) -> dict[str, Any]:
    return result_of(run_django(code, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_flush_lists_a_long_named_child_table_and_deletes_it_first(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, FLUSH_CODE)
    assert data["child_deleted_by_flush"] is True, data["deletes"]
    assert data["child_before_parent"] is True, data["deletes"]
    assert data["error"] == "", data["error"]
    assert data["left"] == {}
