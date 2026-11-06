"""Conditional unique rules on Firebird are emulated (checklists, plan Task 6).

Firebird cannot create a partial (conditional) unique index, so Django skips the two checklist rules
and warns models.W036. infohr_firebird.emulated creates each one as a UNIQUE index over a COMPUTED BY
expression: a row that fails the condition gets NULL as its key, and a unique index allows many NULLs.
The SQL tests run on the cloned template database (fb_alias) with raw SQL. The subprocess test runs
the real project in Firebird mode, and the rest use synthetic models.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import IntegrityError, connections, models
from django.db.models import Q
from django.test.utils import isolate_apps

from infohr_firebird.emulated import EMULATED, EmulatedUnique, create_sql, drop_sql
from infohr_firebird.tests.test_settings_seam import result_of, run_django

OPEN_RULE = EMULATED["checklist_one_open_emp_kind"]
DEFAULT_RULE = EMULATED["checklist_tpl_one_default"]
OPEN_TABLE = "IHR_T_EMU_OPEN"  # scratch copies of the checklist columns, never the real tables
DEFAULT_TABLE = "IHR_T_EMU_DEF"

W036_CODE = """
import json
import django
django.setup()
from django.conf import settings
from django.core.checks import run_checks
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from io import StringIO

issues = run_checks(databases=["default"])
raised = False
try:
    call_command("check", databases=["default"], stdout=StringIO(), stderr=StringIO())
except SystemCheckError:
    raised = True
print("RESULT " + json.dumps({
    "ids": sorted({i.id for i in issues if i.id}),
    "visible": sorted({i.id for i in issues if i.id and i.id not in settings.SILENCED_SYSTEM_CHECKS}),
    "silenced_setting": list(settings.SILENCED_SYSTEM_CHECKS),
    "raised": raised,
}))
"""


@pytest.fixture
def open_table(fb_alias: str) -> Iterator[Any]:
    connection: Any = connections[fb_alias]
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE TABLE {OPEN_TABLE} (ID INTEGER NOT NULL PRIMARY KEY, EMPLOYEE_ID INTEGER, "
            "KIND VARCHAR(20), STATE VARCHAR(20) NOT NULL)"
        )
        cursor.execute(create_sql(OPEN_TABLE, OPEN_RULE))
    try:
        yield connection
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE {OPEN_TABLE}")


@pytest.fixture
def default_table(fb_alias: str) -> Iterator[Any]:
    connection: Any = connections[fb_alias]
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE TABLE {DEFAULT_TABLE} (ID INTEGER NOT NULL PRIMARY KEY, KIND VARCHAR(20) NOT NULL, "
            "IS_DEFAULT BOOLEAN NOT NULL)"
        )
        cursor.execute(create_sql(DEFAULT_TABLE, DEFAULT_RULE))
    try:
        yield connection
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE {DEFAULT_TABLE}")


def _insert_open(connection: Any, row_id: int, employee_id: int | None, kind: str | None, state: str = "open") -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {OPEN_TABLE} (ID, EMPLOYEE_ID, KIND, STATE) VALUES (%s, %s, %s, %s)",  # noqa: S608 (fixed table)
            [row_id, employee_id, kind, state],
        )


def _insert_default(connection: Any, row_id: int, kind: str, is_default: bool) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {DEFAULT_TABLE} (ID, KIND, IS_DEFAULT) VALUES (%s, %s, %s)",  # noqa: S608 (fixed table)
            [row_id, kind, is_default],
        )


def _count_open_rows(connection: Any, employee_id: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {OPEN_TABLE} WHERE EMPLOYEE_ID = %s", [employee_id])  # noqa: S608
        return int(cursor.fetchone()[0])


def test_second_open_row_for_same_key_is_refused(open_table: Any) -> None:
    _insert_open(open_table, 1, 7, "offboarding")
    with pytest.raises(IntegrityError):
        _insert_open(open_table, 2, 7, "offboarding")
    assert _count_open_rows(open_table, 7) == 1


def test_many_closed_rows_are_allowed(open_table: Any) -> None:
    _insert_open(open_table, 1, 7, "offboarding", state="completed")
    _insert_open(open_table, 2, 7, "offboarding", state="completed")
    _insert_open(open_table, 3, 7, "offboarding", state="cancelled")
    _insert_open(open_table, 4, 7, "offboarding", state="open")
    assert _count_open_rows(open_table, 7) == 4


def test_different_employee_allowed(open_table: Any) -> None:
    _insert_open(open_table, 1, 7, "offboarding")
    _insert_open(open_table, 2, 8, "offboarding")
    _insert_open(open_table, 3, 7, "onboarding")
    assert _count_open_rows(open_table, 7) == 2
    assert _count_open_rows(open_table, 8) == 1


def test_null_key_rows_do_not_collide(open_table: Any) -> None:
    # A NULL employee or kind makes the key NULL, and NULLs never collide in a unique index.
    _insert_open(open_table, 1, None, "offboarding")
    _insert_open(open_table, 2, None, "offboarding")
    _insert_open(open_table, 3, 9, None)
    _insert_open(open_table, 4, 9, None)
    with open_table.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {OPEN_TABLE} WHERE STATE = 'open'")  # noqa: S608 (fixed table)
        assert int(cursor.fetchone()[0]) == 4


def test_one_default_per_kind_is_refused(default_table: Any) -> None:
    _insert_default(default_table, 1, "offboarding", True)
    with pytest.raises(IntegrityError):
        _insert_default(default_table, 2, "offboarding", True)
    _insert_default(default_table, 3, "onboarding", True)
    _insert_default(default_table, 4, "offboarding", False)
    _insert_default(default_table, 5, "offboarding", False)


def test_drop_sql_removes_the_index(open_table: Any) -> None:
    _insert_open(open_table, 1, 7, "offboarding")
    with open_table.cursor() as cursor:
        cursor.execute(drop_sql(OPEN_RULE))
    _insert_open(open_table, 2, 7, "offboarding")
    assert _count_open_rows(open_table, 7) == 2


def test_emulated_names_and_index_names_fit_firebird() -> None:
    assert set(EMULATED) == {"checklist_tpl_one_default", "checklist_one_open_emp_kind"}
    for name, spec in EMULATED.items():
        assert spec.name == name
        assert len(spec.index_name) <= 31
    with pytest.raises(ValueError):
        EmulatedUnique(name="x", model_label="a.B", columns=("a",), condition_sql="a = 1", index_name="X" * 32)


def test_w036_silenced_only_for_emulated(fb_clone: str) -> None:
    # Real project, Firebird mode: Django still finds the conditional constraints (W036 is in the list
    # of found ids), but it is silenced, and E010 does not fire because both constraints are emulated.
    # W036 only runs with a database alias, and E011 then connects, so this uses a real copy (fb_clone).
    data = result_of(run_django(W036_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=fb_clone))
    assert "models.W036" in data["ids"], data["ids"]
    assert "models.W036" in data["silenced_setting"]
    assert "models.W036" not in data["visible"]
    assert "infohr_firebird.E010" not in data["ids"]
    assert data["raised"] is False


@isolate_apps("infohr_firebird")
def test_unknown_conditional_unique_is_an_error() -> None:
    from infohr_firebird.checks import unknown_conditional_unique_messages

    class Unknown(models.Model):  # noqa: DJ008 (test model, no __str__ needed)
        code = models.CharField(max_length=10)
        active = models.BooleanField(default=True)

        class Meta:
            app_label = "leave"
            constraints = [
                models.UniqueConstraint(fields=["code"], condition=Q(active=True), name="unknown_one_active_code")
            ]

    class Emulated(models.Model):  # noqa: DJ008
        employee = models.IntegerField()
        kind = models.CharField(max_length=20)
        state = models.CharField(max_length=20)

        class Meta:
            app_label = "leave"
            constraints = [
                models.UniqueConstraint(
                    fields=["employee", "kind"],
                    condition=Q(state="open"),
                    name="checklist_one_open_emp_kind",
                )
            ]

    class Plain(models.Model):  # noqa: DJ008
        code = models.CharField(max_length=10)

        class Meta:
            app_label = "leave"
            constraints = [models.UniqueConstraint(fields=["code"], name="plain_unique_code")]

    class MacsUnknown(models.Model):  # noqa: DJ008
        code = models.CharField(max_length=10)
        active = models.BooleanField(default=True)

        class Meta:
            app_label = "macs"
            constraints = [
                models.UniqueConstraint(fields=["code"], condition=Q(active=True), name="macs_one_active_code")
            ]

    messages = unknown_conditional_unique_messages([Unknown, Emulated, Plain, MacsUnknown])
    assert [m.id for m in messages] == ["infohr_firebird.E010"]
    assert "unknown_one_active_code" in messages[0].msg
    assert "EMULATED" in str(messages[0].hint)
