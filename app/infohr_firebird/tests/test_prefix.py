import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from django.db import connections, models
from django.test.utils import isolate_apps
from pytest_django.fixtures import SettingsWrapper

from infohr_firebird.prefix import apply_prefix

APP_DIR = Path(__file__).resolve().parents[2]  # <repo>/app


def test_prefix_applied_once(settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = ""  # the class_prepared receiver must not touch this test model

    with isolate_apps():

        class Leave(models.Model):  # noqa: DJ008 (test model, no __str__ needed)
            class Meta:
                app_label = "leave"
                db_table = "leave_x"

        apply_prefix(Leave, "IHR_")
        assert Leave._meta.db_table == "ihr_leave_x"  # lower case: Django compares with table_names()
        apply_prefix(Leave, "IHR_")
        assert Leave._meta.db_table == "ihr_leave_x"  # lower case: Django compares with table_names()


def test_unmanaged_and_macs_untouched(settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = ""

    with isolate_apps():

        class Unmanaged(models.Model):  # noqa: DJ008 (test model)
            class Meta:
                app_label = "leave"
                managed = False
                db_table = "legacy_unmanaged"

        class MacsRow(models.Model):  # noqa: DJ008 (test model)
            class Meta:
                app_label = "macs"
                db_table = "macs_row"

        apply_prefix(Unmanaged, "IHR_")
        apply_prefix(MacsRow, "IHR_")
        assert Unmanaged._meta.db_table == "legacy_unmanaged"
        assert MacsRow._meta.db_table == "macs_row"


def test_empty_prefix_is_a_noop(settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = ""

    with isolate_apps():

        class Leave(models.Model):  # noqa: DJ008 (test model, no __str__ needed)
            class Meta:
                app_label = "leave"
                db_table = "leave_y"

        apply_prefix(Leave, "")
        assert Leave._meta.db_table == "leave_y"


CHECK_CODE = """
import django
django.setup()
from django.apps import apps

models = [
    m for m in apps.get_models(include_auto_created=True)
    if m._meta.managed and m._meta.app_label != "macs"
]
bad = [
    f"{m._meta.label} -> {m._meta.db_table}"
    for m in models
    if not m._meta.db_table.upper().startswith("IHR_") or "IHR_IHR_" in m._meta.db_table.upper()
]
print("checked", len(models))
from django.db.backends.utils import truncate_name
names = [m._meta.db_table for m in models]
short = [truncate_name(n, 31).upper() for n in names]
collisions = sorted({s for s in short if short.count(s) > 1})
print("over31", sum(1 for n in names if len(n) > 31))
print("collisions", collisions)
if collisions:
    raise SystemExit(1)
if bad:
    print("BAD", bad)
    raise SystemExit(1)
"""


def test_all_hr_models_prefixed() -> None:
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "PYTHONPATH": str(APP_DIR),
        "DJANGO_HR_TABLE_PREFIX": "IHR_",
        "DATABASE_URL": "postgres://x:x@127.0.0.1:1/x",  # parsed only; django.setup() does not connect
    }
    result = subprocess.run(  # noqa: S603 (fixed argv, our own code string)
        [sys.executable, "-B", "-c", CHECK_CODE],
        env=env,
        cwd=str(APP_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "checked " in result.stdout, result.stdout
    count = int(result.stdout.split("checked ")[1].split()[0])
    # 48 at the time of Task 6 (auth, accounts, HR apps): a sanity floor, not an exact count
    assert count > 40, result.stdout


@isolate_apps("infohr_firebird")
def test_long_prefixed_table_name_lifecycle(fb_alias: str) -> None:
    class LongPrefixed(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)
        name = models.CharField(max_length=20, db_index=True)
        qty = models.IntegerField(null=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_checklists_checklisttemplatetask"  # 36 characters, longer than 31

    connection = cast(Any, connections[fb_alias])  # backend introspection and ops are untyped
    # The DDL name is truncated to 31 characters by quote_name; introspection must report the same name.
    expected = connection.introspection.table_name_converter(LongPrefixed._meta.db_table)
    assert len(expected) == 31, expected
    with connection.schema_editor() as editor:
        editor.create_model(LongPrefixed)
    try:
        with connection.cursor() as cursor:
            assert expected in connection.introspection.table_names(cursor)
        row = cast(Any, LongPrefixed).objects.using(fb_alias).create(name="abc", qty=7)
        stored = cast(Any, LongPrefixed).objects.using(fb_alias).get(pk=row.pk)
        assert (stored.name, stored.qty) == ("abc", 7)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(LongPrefixed)
    with connection.cursor() as cursor:
        assert expected not in connection.introspection.table_names(cursor)


@isolate_apps("infohr_firebird")
def test_prefixed_name_is_found_by_table_names(fb_alias: str) -> None:
    # Django compares db_table with introspection.table_names(); Firebird reports lower-case names,
    # so a mixed-case prefixed name (IHR_django_migrations) was never found and the recorder
    # tried to create its table again ("already exists") during the first migrate.
    class Recorder(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "django_migrations"

    apply_prefix(Recorder, "IHR_")
    connection = cast(Any, connections[fb_alias])
    with connection.schema_editor() as editor:
        editor.create_model(Recorder)
    try:
        with connection.cursor() as cursor:
            assert Recorder._meta.db_table in connection.introspection.table_names(cursor)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Recorder)


@isolate_apps()
def test_proxy_shares_concrete_table(settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = ""

    with isolate_apps():

        class Leave(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
            class Meta:
                app_label = "leave"
                db_table = "leave_z"

        class LeaveProxy(Leave):  # noqa: DJ008 - throwaway model, no __str__ needed
            class Meta:
                app_label = "leave"
                proxy = True

        apply_prefix(LeaveProxy, "IHR_")  # a proxy has no table of its own: must be skipped
        assert LeaveProxy._meta.db_table == "leave_z"
        apply_prefix(Leave, "IHR_")
        assert Leave._meta.db_table == "ihr_leave_z"


@isolate_apps("infohr_firebird")
def test_long_name_constraints_and_alter(fb_alias: str) -> None:
    class LongParent(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_checklists_checklisttemplate"  # 32 characters

    class LongChild(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)
        code = models.CharField(max_length=10, unique=True)
        note = models.CharField(max_length=20, null=True, db_index=True)  # noqa: DJ001 - nullable on purpose
        parent = models.ForeignKey(LongParent, on_delete=models.CASCADE, null=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_checklists_checklisttemplatetask"  # 36 characters

    connection = cast(Any, connections[fb_alias])
    intro = connection.introspection
    table = LongChild._meta.db_table
    with connection.schema_editor() as editor:
        editor.create_model(LongParent)
        editor.create_model(LongChild)
    try:
        with connection.cursor() as cursor:
            columns = {f.name for f in intro.get_table_description(cursor, table)}
            assert {"id", "code", "note", "parent_id"} <= columns
            constraints = intro.get_constraints(cursor, table)
            assert ["code"] in [c["columns"] for c in constraints.values() if c["unique"]]
            assert ["note"] in [c["columns"] for c in constraints.values() if c["index"]]
            assert ["parent_id"] in [c["columns"] for c in constraints.values() if c["foreign_key"]]
            assert "parent_id" in [row[0] for row in intro.get_key_columns(cursor, table)]
            assert "parent_id" in intro.get_relations(cursor, table)

        with connection.schema_editor() as editor:
            assert editor._constraint_names(LongChild, column_names=["code"], unique=True)
            old_note = LongChild._meta.get_field("note")
            new_note: models.Field[Any, Any] = models.CharField(max_length=20, null=True)  # noqa: DJ001
            new_note.set_attributes_from_name("note")
            editor.alter_field(LongChild, old_note, new_note)  # drops the index on note
        with connection.cursor() as cursor:
            constraints = intro.get_constraints(cursor, table)
            assert ["note"] not in [c["columns"] for c in constraints.values() if c["index"]]

        with connection.schema_editor() as editor:
            editor.remove_field(LongChild, LongChild._meta.get_field("code"))  # drops unique and column
        with connection.cursor() as cursor:
            columns = {f.name for f in intro.get_table_description(cursor, table)}
            assert "code" not in columns
            constraints = intro.get_constraints(cursor, table)
            assert ["code"] not in [c["columns"] for c in constraints.values()]
            assert ["parent_id"] in [c["columns"] for c in constraints.values() if c["foreign_key"]]
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(LongChild)
            editor.delete_model(LongParent)
    with connection.cursor() as cursor:
        assert intro.table_name_converter(table) not in intro.table_names(cursor)
