"""The Firebird raw snapshot (creation.serialize_db_to_string / deserialize_db_from_string), plan 6 fix task.

TransactionTestCase with serialized_rollback=True restores the seeded rows (role groups, permissions, content types)
after its flush, from the snapshot that the test database keeps. Django's own serializer fails on Firebird, so the
Firebird backend keeps its own raw snapshot. These tests check that a flush followed by a restore gives back the same
rows, with the same ids and values, and that the generators are set above the restored ids.

Each test runs in a subprocess on the module's migrated copy (migrated_clone), like the other ORM tests.
"""

from typing import Any

from infohr_firebird.tests.test_settings_seam import result_of, run_django

# Raw rows of every managed HR table, read without the ORM so that values come back exactly as stored.
PRELUDE = """
import json
import uuid
import django
django.setup()
from django.apps import apps
from django.core.management import call_command
from django.db import connection


def hr_models():
    return [m for m in apps.get_models(include_auto_created=True) if m._meta.managed and m._meta.app_label != "macs"]


def raw_rows():
    out = {}
    with connection.cursor() as cursor:
        for model in hr_models():
            columns = [f.column for f in model._meta.local_concrete_fields]
            select = "SELECT %s FROM %s ORDER BY %s" % (
                ", ".join(connection.ops.quote_name(c) for c in columns),
                connection.ops.quote_name(model._meta.db_table),
                connection.ops.quote_name(model._meta.pk.column),
            )
            cursor.execute(select)
            out[model._meta.db_table] = [repr(tuple(row)) for row in cursor.fetchall()]
    return out


def flush():
    call_command("flush", interactive=False, verbosity=0, inhibit_post_migrate=True, reset_sequences=True)
"""

# Seeds are rows the migrations make; the snapshot must hold them too. Rows of several tables are made here: a long
# named child table (ChecklistTemplateTask is stored shortened on Firebird), Cyrillic text, a nullable foreign key,
# a datetime, a decimal, a boolean, and a binary value (StaffImportDraft.data).
ROUNDTRIP_CODE = (
    PRELUDE
    + """
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from django.contrib.auth.models import Group
from checklists.models import ChecklistKind, ChecklistTemplate, ChecklistTemplateTask
from employees.models import StaffImportDraft

tag = uuid.uuid4().hex[:8]
group = Group.objects.create(name=f"Сэргээх бүлэг {tag}")
template = ChecklistTemplate.objects.create(
    kind=ChecklistKind.ONBOARDING, name=f"Загвар {tag}", reasons=["1", "2"], active=False
)
ChecklistTemplateTask.objects.create(template=template, title="Даалгавар А", group=group, due_offset_days=-3)
ChecklistTemplateTask.objects.create(template=template, title="Удирдлага", group=None, manager=True)
draft = StaffImportDraft.objects.create(
    filename=f"import {tag}.xlsx",
    data=b"\\x00PK\\x03\\x04\\xff binary",
    header_rows=2,
    started_at=datetime(2026, 11, 7, 9, 30, 15, 123456),
)

before = raw_rows()
started_before = StaffImportDraft.objects.get(pk=draft.pk).started_at
max_group = Group.objects.order_by("-pk").values_list("pk", flat=True).first()
serialized = connection.creation.serialize_db_to_string()
flush()
emptied = {
    "groups": Group.objects.count(),
    "tasks": ChecklistTemplateTask.objects.count(),
    "drafts": StaffImportDraft.objects.count(),
}
connection.creation.deserialize_db_from_string(serialized)
after = raw_rows()
restored_draft = StaffImportDraft.objects.get(pk=draft.pk)
restored_tasks = list(
    ChecklistTemplateTask.objects.filter(template_id=template.pk)
    .order_by("pk")
    .values_list("title", "group_id", "manager")
)
print("RESULT " + json.dumps({
    "emptied": emptied,
    "same_rows": before == after,
    "differs": sorted(t for t in before if before[t] != after.get(t)),
    "tables_before": len(before),
    "tables_after": len(after),
    "binary_ok": bytes(restored_draft.data) == b"\\x00PK\\x03\\x04\\xff binary",
    "started_ok": restored_draft.started_at == started_before,
    "tasks": [list(row) for row in restored_tasks],
    "group_id": group.pk,
    "max_group": max_group,
    "group_restored": Group.objects.filter(pk=group.pk, name=f"Сэргээх бүлэг {tag}").exists(),
    "seeded_roles_back": Group.objects.filter(name="HR").exists(),
}))
"""
)

NEXT_ID_CODE = (
    PRELUDE
    + """
from django.contrib.auth.models import Group

tag = uuid.uuid4().hex[:8]
Group.objects.create(name=f"Дараагийн {tag}")
top = Group.objects.order_by("-pk").values_list("pk", flat=True).first()
serialized = connection.creation.serialize_db_to_string()
flush()
connection.creation.deserialize_db_from_string(serialized)
restored_top = Group.objects.order_by("-pk").values_list("pk", flat=True).first()
fresh = Group.objects.create(name=f"Шинэ {tag}")
print("RESULT " + json.dumps({"top": top, "restored_top": restored_top, "fresh": fresh.pk}))
"""
)


def _firebird(migrated_clone: str, code: str) -> dict[str, Any]:
    return result_of(run_django(code, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_snapshot_restores_every_row_after_a_flush(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, ROUNDTRIP_CODE)
    assert data["emptied"] == {"groups": 0, "tasks": 0, "drafts": 0}, "the flush did not empty the tables"
    assert data["tables_after"] == data["tables_before"]
    assert data["differs"] == [], "rows differ after restore"
    assert data["same_rows"] is True
    assert data["group_restored"] is True
    assert data["seeded_roles_back"] is True, "the seeded HR role group did not come back"
    assert data["binary_ok"] is True
    assert data["started_ok"] is True
    assert data["tasks"] == [["Даалгавар А", data["group_id"], False], ["Удирдлага", None, True]]


def test_generator_is_set_above_the_restored_ids(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, NEXT_ID_CODE)
    assert data["restored_top"] == data["top"]
    assert data["fresh"] > data["restored_top"]
