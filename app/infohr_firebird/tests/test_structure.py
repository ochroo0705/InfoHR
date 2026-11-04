"""Structure fingerprint, pre-flight collision check and the fb_guard command (plan Task 8).

Tests run on a throwaway copy of the template database. EMPLOYEE is an existing MACS table in
that copy; every object the tests create uses the IHR_ prefix and is dropped in a finally block.
"""

import io
import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.db import connections, models
from django.test.utils import isolate_apps
from firebird.driver import connect, driver_config  # type: ignore[import-untyped]
from pytest_django.fixtures import SettingsWrapper

from infohr_firebird.base import DEFAULT_FB_CLIENT_LIBRARY
from infohr_firebird.management.commands.fb_guard import Command, _snapshot_problem
from infohr_firebird.structure import CATEGORIES, existing_tables, fingerprint, preflight
from infohr_firebird.tests.copies import remove_copy

PREFIX = "IHR_"


def _fp(connection: Any, prefixes: tuple[str, ...] = (PREFIX,)) -> dict[str, tuple[int, str]]:
    with connection.cursor() as cursor:
        return fingerprint(cursor, prefixes)


def _exec(connection: Any, sql: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql)


def _table_names(connection: Any) -> set[str]:
    with connection.cursor() as cursor:
        return existing_tables(cursor)


def _exists(connection: Any, sql: str, params: list[str]) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone() is not None


def _drop_model_if_exists(connection: Any, model: type[models.Model]) -> None:
    if connection.ops.quote_name(model._meta.db_table) in _table_names(connection):
        with connection.schema_editor() as editor:
            editor.delete_model(model)


def _column_exists(connection: Any, table: str, column: str) -> bool:
    return _exists(
        connection,
        "select 1 from rdb$relation_fields where rdb$relation_name = %s and rdb$field_name = %s",
        [table, column],
    )


def _trigger_exists(connection: Any, name: str) -> bool:
    return _exists(connection, "select 1 from rdb$triggers where rdb$trigger_name = %s", [name])


def _index_exists(connection: Any, name: str) -> bool:
    return _exists(connection, "select 1 from rdb$indices where rdb$index_name = %s", [name])


def _procedure_exists(connection: Any, name: str) -> bool:
    return _exists(connection, "select 1 from rdb$procedures where rdb$procedure_name = %s", [name])


@isolate_apps("infohr_firebird")
def test_fingerprint_unchanged_by_new_table(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = PREFIX
    connection = connections[fb_alias]
    before = _fp(connection)

    class Parent(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)
        code = models.CharField(max_length=20, unique=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_PROBE_P"

    class Probe(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)
        name = models.CharField(max_length=50, unique=True)
        qty = models.IntegerField(null=True, db_index=True)
        parent = models.ForeignKey(Parent, on_delete=models.DO_NOTHING)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_PROBE"

    try:
        with connection.schema_editor() as editor:
            editor.create_model(Parent)
            editor.create_model(Probe)
        assert _fp(connection) == before
        # Sanity: without the HR filter the new tables do show up.
        assert _fp(connection, ()) != before
    finally:
        _drop_model_if_exists(connection, Probe)
        _drop_model_if_exists(connection, Parent)


def test_fingerprint_detects_alter_of_existing_table(fb_alias: str) -> None:
    connection = connections[fb_alias]
    before = _fp(connection)
    try:
        _exec(connection, "ALTER TABLE EMPLOYEE ADD ZZ_TEST integer")
        after = _fp(connection)
        assert after["fields"] != before["fields"]
        assert after["relations"] == before["relations"]
    finally:
        if _column_exists(connection, "EMPLOYEE", "ZZ_TEST"):
            _exec(connection, "ALTER TABLE EMPLOYEE DROP ZZ_TEST")


def test_fingerprint_detects_new_trigger(fb_alias: str) -> None:
    connection = connections[fb_alias]
    before = _fp(connection)
    try:
        _exec(connection, "CREATE TRIGGER ZZ_TEST_TRG FOR EMPLOYEE ACTIVE BEFORE INSERT AS BEGIN END")
        after = _fp(connection)
        assert after["triggers"] != before["triggers"]
        assert after["fields"] == before["fields"]
    finally:
        if _trigger_exists(connection, "ZZ_TEST_TRG"):
            _exec(connection, "DROP TRIGGER ZZ_TEST_TRG")


@isolate_apps("infohr_firebird")
def test_preflight_reports_collision(fb_alias: str, settings: SettingsWrapper, monkeypatch: pytest.MonkeyPatch) -> None:
    # Define the model BEFORE setting the prefix: the class_prepared receiver would otherwise
    # prefix EMPLOYEE to IHR_EMPLOYEE and the collision would disappear.
    class Clash(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "EMPLOYEE"

    settings.HR_TABLE_PREFIX = PREFIX
    command = Command()
    monkeypatch.setattr(command, "models_to_check", lambda: [Clash])
    out = io.StringIO()
    with pytest.raises(CommandError, match="EMPLOYEE"):
        call_command(command, "preflight", database=fb_alias, stdout=out)
    assert "EMPLOYEE" in out.getvalue()


@isolate_apps("infohr_firebird")
def test_preflight_clean(fb_alias: str, settings: SettingsWrapper, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.HR_TABLE_PREFIX = PREFIX
    connection = connections[fb_alias]

    class Alpha(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_ALPHA"

    class Beta(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_BETA"

    command = Command()
    monkeypatch.setattr(command, "models_to_check", lambda: [Alpha, Beta])
    out = io.StringIO()
    call_command(command, "preflight", database=fb_alias, stdout=out)
    assert "pre-flight ok: 2 model tables" in out.getvalue()

    try:
        with connection.schema_editor() as editor:
            editor.create_model(Alpha)
            editor.create_model(Beta)
        # Re-running over HR's own tables is fine.
        out = io.StringIO()
        call_command(command, "preflight", database=fb_alias, stdout=out)
        assert "pre-flight ok" in out.getvalue()
    finally:
        _drop_model_if_exists(connection, Beta)
        _drop_model_if_exists(connection, Alpha)


@isolate_apps("infohr_firebird")
def test_verify_roundtrip(fb_alias: str, settings: SettingsWrapper, tmp_path: Path) -> None:
    settings.HR_TABLE_PREFIX = PREFIX
    connection = connections[fb_alias]
    snapshot = tmp_path / "snapshot.json"
    call_command(Command(), "snapshot", str(snapshot), database=fb_alias, stdout=io.StringIO())
    assert snapshot.is_file()

    class Probe(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_VERIFY"

    try:
        with connection.schema_editor() as editor:
            editor.create_model(Probe)
        # Creating an HR table must not make verify fail.
        out = io.StringIO()
        call_command(Command(), "verify", str(snapshot), database=fb_alias, stdout=out)
        assert "verify ok: existing objects unchanged" in out.getvalue()

        _exec(connection, "ALTER TABLE EMPLOYEE ADD ZZ_TEST integer")
        with pytest.raises(CommandError, match="existing MACS objects changed"):
            call_command(Command(), "verify", str(snapshot), database=fb_alias, stdout=io.StringIO())
    finally:
        _drop_model_if_exists(connection, Probe)
        if _column_exists(connection, "EMPLOYEE", "ZZ_TEST"):
            _exec(connection, "ALTER TABLE EMPLOYEE DROP ZZ_TEST")


def test_snapshot_needs_prefix(fb_alias: str, settings: SettingsWrapper, tmp_path: Path) -> None:
    settings.HR_TABLE_PREFIX = ""
    with pytest.raises(CommandError, match="HR_TABLE_PREFIX"):
        call_command(Command(), "snapshot", str(tmp_path / "s.json"), database=fb_alias, stdout=io.StringIO())


@isolate_apps("infohr_firebird")
def test_long_names_do_not_collide(fb_alias: str) -> None:
    """Names that differ only after character 31 do not collide.

    quote_name cuts a long name to 31 characters and puts a hash of the whole name in the
    last four, so the two tables below get different names in the database. The check uses
    the same names Django creates, so it reports no collision here.
    """
    connection = connections[fb_alias]

    class LongOne(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_" + "L" * 40 + "1"

    class LongTwo(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_" + "L" * 40 + "2"

    names = {connection.ops.quote_name(model._meta.db_table) for model in (LongOne, LongTwo)}
    assert len(names) == 2
    assert all(len(name) == 31 for name in names)
    assert preflight(connection, [LongOne, LongTwo], PREFIX) == []


@isolate_apps("infohr_firebird")
def test_duplicate_table_names_report(fb_alias: str) -> None:
    connection = connections[fb_alias]

    class Upper(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_SAME"

    class Lower(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "ihr_t_same"

    problems = preflight(connection, [Upper, Lower], PREFIX)
    assert len(problems) == 1
    assert "IHR_T_SAME" in problems[0]


@isolate_apps("infohr_firebird")
def test_django_migrations_table_is_not_a_collision(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = PREFIX
    connection = connections[fb_alias]

    class Migrations(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_django_migrations"

    try:
        with connection.schema_editor() as editor:
            editor.create_model(Migrations)
        assert "IHR_DJANGO_MIGRATIONS" in _table_names(connection)
        assert preflight(connection, [Migrations], PREFIX) == []
    finally:
        _drop_model_if_exists(connection, Migrations)


def test_preflight_command_uses_real_models(fb_alias: str, settings: SettingsWrapper) -> None:
    """Wiring check with the project's real model list.

    The receiver ran with an empty prefix at startup, so real HR table names are not prefixed in
    this process. The command must report exactly what the pure function reports.
    """
    settings.HR_TABLE_PREFIX = PREFIX
    connection = connections[fb_alias]
    command = Command()
    expected = preflight(connection, command.models_to_check(), PREFIX)
    out = io.StringIO()
    if expected:
        with pytest.raises(CommandError, match="pre-flight failed"):
            call_command(command, "preflight", database=fb_alias, stdout=out)
    else:
        call_command(command, "preflight", database=fb_alias, stdout=out)
        assert "pre-flight ok" in out.getvalue()


@contextmanager
def _dialect_one_driver() -> Iterator[None]:
    """The driver options base.py sets (client library, dialect 1). The previous values come back afterwards."""
    previous_library = driver_config.fb_client_library.value
    previous_dialect = driver_config.db_defaults.sql_dialect.value
    driver_config.fb_client_library.value = DEFAULT_FB_CLIENT_LIBRARY
    driver_config.db_defaults.sql_dialect.value = 1
    try:
        yield
    finally:
        driver_config.fb_client_library.value = previous_library
        driver_config.db_defaults.sql_dialect.value = previous_dialect


def _fp_after_ddl(source: str, work: Path, ddl: list[str]) -> dict[str, tuple[int, str]]:
    """Copy source to work, run ddl on that copy, return its fingerprint, then delete the copy.

    One copy exists at a time. Source is never opened or changed. Two calls with the same DDL
    sequence get the same system names (RDB$nnn, CHECK_nnn), so only the statement that differs
    can change the fingerprint.
    """
    shutil.copyfile(source, work)
    try:
        with _dialect_one_driver():
            # Same connect arguments as the backend (base.py): no empty password, UTF8 charset.
            password = os.environ.get("FIREBIRD_PASSWORD", "")
            conn = connect(str(work), user="SYSDBA", charset="UTF8", **({"password": password} if password else {}))
            try:
                cursor = conn.cursor()
                for statement in ddl:
                    cursor.execute(statement)
                conn.commit()
                return fingerprint(cursor, (PREFIX,))
            finally:
                conn.close()
    finally:
        remove_copy(work)


def test_prefixed_trigger_on_existing_table_is_detected(fb_alias: str) -> None:
    connection = connections[fb_alias]
    before = _fp(connection)
    _exec(connection, "CREATE TRIGGER IHR_ZZ_TRG FOR EMPLOYEE ACTIVE BEFORE INSERT AS BEGIN END")
    try:
        after = _fp(connection)
        assert after["triggers"] != before["triggers"]
    finally:
        if _trigger_exists(connection, "IHR_ZZ_TRG"):
            _exec(connection, "DROP TRIGGER IHR_ZZ_TRG")


def test_index_columns_change_is_detected(fb_alias: str) -> None:
    connection = connections[fb_alias]
    try:
        _exec(connection, "CREATE INDEX ZZ_IDX ON EMPLOYEE (NAME)")
        before = _fp(connection)
        _exec(connection, "DROP INDEX ZZ_IDX")
        _exec(connection, "CREATE INDEX ZZ_IDX ON EMPLOYEE (SURNAME)")
        after = _fp(connection)
        assert after["indices"] != before["indices"]
        assert after["relations"] == before["relations"]
    finally:
        if _index_exists(connection, "ZZ_IDX"):
            _exec(connection, "DROP INDEX ZZ_IDX")


def test_fk_rule_change_is_detected(fb_clone: str, tmp_path: Path) -> None:
    work = tmp_path / "work.fdb"
    base = "ALTER TABLE EMPLOYEE ADD CONSTRAINT ZZ_FK FOREIGN KEY (ZZ_REF) REFERENCES EMPLOYEE (EMPLOYEE_ID)"
    add_column = "ALTER TABLE EMPLOYEE ADD ZZ_REF integer"
    before = _fp_after_ddl(fb_clone, work, [add_column, base])
    after = _fp_after_ddl(fb_clone, work, [add_column, base + " ON DELETE CASCADE"])
    assert after["constraints"] != before["constraints"]


def test_check_body_change_is_detected(fb_clone: str, tmp_path: Path) -> None:
    work = tmp_path / "work.fdb"
    before = _fp_after_ddl(fb_clone, work, ["ALTER TABLE EMPLOYEE ADD CONSTRAINT ZZ_CHK CHECK (EMPLOYEE_ID > 0)"])
    after = _fp_after_ddl(fb_clone, work, ["ALTER TABLE EMPLOYEE ADD CONSTRAINT ZZ_CHK CHECK (EMPLOYEE_ID > 1)"])
    assert after["checks"] != before["checks"]


def test_field_collation_change_is_detected(fb_clone: str, tmp_path: Path) -> None:
    """Dialect 1 keeps no precision for NUMERIC(10,2) vs NUMERIC(12,2) (rdb$field_precision is NULL),
    so the observable column attribute that differs here is the collation (rdb$collation_id)."""
    work = tmp_path / "work.fdb"
    before = _fp_after_ddl(fb_clone, work, ["ALTER TABLE EMPLOYEE ADD ZZ_NAME VARCHAR(10) CHARACTER SET UTF8"])
    after = _fp_after_ddl(
        fb_clone, work, ["ALTER TABLE EMPLOYEE ADD ZZ_NAME VARCHAR(10) CHARACTER SET UTF8 COLLATE UNICODE_CI"]
    )
    assert after["fields"] != before["fields"]


def test_blob_segment_size_change_is_detected(fb_clone: str, tmp_path: Path) -> None:
    """rdb$segment_length is stored only for BLOB columns; VARCHAR and CHAR lengths are in rdb$field_length."""
    work = tmp_path / "work.fdb"
    before = _fp_after_ddl(fb_clone, work, ["ALTER TABLE EMPLOYEE ADD ZZ_NOTE BLOB SUB_TYPE TEXT SEGMENT SIZE 80"])
    after = _fp_after_ddl(fb_clone, work, ["ALTER TABLE EMPLOYEE ADD ZZ_NOTE BLOB SUB_TYPE TEXT SEGMENT SIZE 200"])
    assert after["fields"] != before["fields"]


@isolate_apps("infohr_firebird")
def test_fingerprint_unchanged_by_hr_table_with_fk_to_employee(fb_alias: str, settings: SettingsWrapper) -> None:
    """An HR table referencing the MACS table EMPLOYEE, both ways: HR's own FK creation (skipped by
    the schema editor under the HR prefix) and a constraint added by raw DDL, as another builder would."""
    settings.HR_TABLE_PREFIX = PREFIX
    connection = connections[fb_alias]
    before = _fp(connection)

    class MacsEmployee(models.Model):  # noqa: DJ008 - unmanaged stub of the existing MACS table
        id = models.AutoField(primary_key=True, db_column="EMPLOYEE_ID")

        class Meta:
            app_label = "infohr_firebird"
            managed = False
            db_table = "EMPLOYEE"

    class RefByHr(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        emp = models.ForeignKey(MacsEmployee, on_delete=models.DO_NOTHING, db_column="EMP")

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_REF_HR"

    class RefRaw(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        emp = models.IntegerField(db_column="EMP")

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_REF_RAW"

    try:
        with connection.schema_editor() as editor:
            editor.create_model(RefByHr)
        assert _fk_count(connection, "IHR_T_REF_HR") == 0  # the schema editor skips HR-to-MACS constraints
        assert _fp(connection) == before

        with connection.schema_editor() as editor:
            editor.create_model(RefRaw)
        _exec(
            connection,
            "ALTER TABLE IHR_T_REF_RAW ADD CONSTRAINT IHR_FK_REF_RAW "
            "FOREIGN KEY (EMP) REFERENCES EMPLOYEE (EMPLOYEE_ID)",
        )
        assert _fk_count(connection, "IHR_T_REF_RAW") == 1  # the raw constraint really exists
        assert _fp(connection) == before
    finally:
        _drop_model_if_exists(connection, RefRaw)
        _drop_model_if_exists(connection, RefByHr)


def _fk_count(connection: Any, table: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "select count(*) from rdb$relation_constraints "
            "where rdb$relation_name = %s and rdb$constraint_type = 'FOREIGN KEY'",
            [table],
        )
        return int(cursor.fetchone()[0])


def test_procedure_parameter_change_is_detected(fb_alias: str) -> None:
    connection = connections[fb_alias]
    try:
        _exec(connection, "CREATE PROCEDURE ZZ_PROC (A INTEGER) RETURNS (R INTEGER) AS BEGIN R = 1; END")
        before = _fp(connection)
        _exec(connection, "ALTER PROCEDURE ZZ_PROC (A VARCHAR(10)) RETURNS (R INTEGER) AS BEGIN R = 1; END")
        after = _fp(connection)
        assert after["procedures"] != before["procedures"]
    finally:
        if _procedure_exists(connection, "ZZ_PROC"):
            _exec(connection, "DROP PROCEDURE ZZ_PROC")


def test_verify_rejects_empty_prefix_snapshot(fb_alias: str, settings: SettingsWrapper, tmp_path: Path) -> None:
    settings.HR_TABLE_PREFIX = PREFIX
    snapshot = tmp_path / "snapshot.json"
    call_command(Command(), "snapshot", str(snapshot), database=fb_alias, stdout=io.StringIO())
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    data["ignore_prefixes"] = [""]
    snapshot.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CommandError, match="invalid fb_guard snapshot"):
        call_command(Command(), "verify", str(snapshot), database=fb_alias, stdout=io.StringIO())


@pytest.mark.parametrize(
    "content",
    [
        "not json at all",
        "[1, 2, 3]",
        '{"fingerprint": {}}',
        '{"ignore_prefixes": "IHR_", "fingerprint": {}}',
        '{"ignore_prefixes": [], "fingerprint": {}}',
        '{"ignore_prefixes": [""], "fingerprint": {}}',
        '{"ignore_prefixes": ["IHR_"], "fingerprint": []}',
        '{"ignore_prefixes": ["IHR_"], "fingerprint": {"relations": [1, "ab"]}}',
        '{"ignore_prefixes": ["IHR_"], "fingerprint": {"relations": ["x", "ab"]}}',
    ],
)
def test_verify_rejects_malformed_snapshot(fb_alias: str, tmp_path: Path, content: str) -> None:
    snapshot = tmp_path / "bad.json"
    snapshot.write_text(content, encoding="utf-8")
    with pytest.raises(CommandError, match="snapshot"):
        call_command(Command(), "verify", str(snapshot), database=fb_alias, stdout=io.StringIO())


def _full_snapshot(hash_value: object) -> dict[str, Any]:
    fingerprint_map: dict[str, Any] = {name: [0, "0123456789ab"] for name in CATEGORIES}
    fingerprint_map["relations"] = [0, hash_value]
    return {"ignore_prefixes": ["IHR_"], "fingerprint": fingerprint_map}


def test_snapshot_accepts_well_formed_hash() -> None:
    assert _snapshot_problem(_full_snapshot("0123456789ab")) == ""


@pytest.mark.parametrize("bad_hash", ["ABCDEF123456", "abc", "0123456789abcdef", "zzzzzzzzzzzz", "", 123, None])
def test_snapshot_rejects_bad_hash(bad_hash: object) -> None:
    assert "relations" in _snapshot_problem(_full_snapshot(bad_hash))
