"""Firebird safety net for the history no-overlap rule, and the emulated checklist rules (plan Task 7b).

Every test runs on one clone of the template that is migrated through the Firebird migration set (module
fixture ``migrated_clone``): ``migrate`` runs once per app, in the order of the foundation acceptance, in a
subprocess in Firebird mode. The test process then talks to the clone through Django's own backend, so the
triggers and indexes are exercised exactly as the application meets them. Each test starts from empty history
and checklist tables. The template itself is never opened.

The app's lock row is what serialises two writers (docs/migration/overlap-guard-spike.md); the trigger only
refuses an overlap that gets past the application check. These tests cover the trigger on its own.
"""

import datetime as dt
import os
from collections.abc import Iterator
from typing import Any

import pytest
from django.db import DatabaseError, IntegrityError
from django.db.utils import ConnectionHandler

JOB_TABLE = "IHR_EMPLOYEES_JOBRECORD"
SALARY_TABLE = "IHR_EMPLOYEES_SALARYRECORD"
CHECKLIST_TABLE = "IHR_CHECKLISTS_CHECKLIST"
OVERLAP = "IHR_HISTORY_OVERLAP"
NOW = dt.datetime(2026, 11, 6, 9, 0, 0)  # NOT NULL created_at; any moment will do

FEB = dt.date(2026, 2, 1)
JAN = dt.date(2026, 1, 1)
MAR = dt.date(2026, 3, 1)
JUN = dt.date(2026, 6, 30)


@pytest.fixture
def fb(migrated_clone: str, django_db_blocker: Any) -> Iterator[Any]:
    """A Django connection to the migrated clone, with the history and checklist tables emptied first."""
    databases = {
        "default": {"ENGINE": "django.db.backends.dummy"},  # Django requires a default alias; never used
        "fb": {
            "ENGINE": "infohr_firebird",
            "NAME": migrated_clone,
            "USER": "SYSDBA",
            "PASSWORD": os.environ.get("FIREBIRD_PASSWORD", ""),  # secret: from the environment only
            "HOST": "",
            "PORT": "",
            "OPTIONS": {"charset": "UTF8"},
            "TIME_ZONE": "Asia/Ulaanbaatar",
        },
    }
    handler = ConnectionHandler(databases)
    with django_db_blocker.unblock():
        connection = handler["fb"]
        try:
            with connection.cursor() as cursor:
                for table in (JOB_TABLE, SALARY_TABLE, CHECKLIST_TABLE):
                    cursor.execute(f"DELETE FROM {table}")  # noqa: S608 (fixed table names)
            yield connection
        finally:
            connection.close()


def _insert_job(connection: Any, employee_id: int, start: dt.date, end: dt.date | None) -> None:
    # The id comes from the table's generator trigger; the foreign keys to MACS are not created on Firebird.
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {JOB_TABLE} (START_DATE, END_DATE, EMPLOYEE_ID, POSITION_ID, DEPARTMENT_ID, "  # noqa: S608
            "EMPLOYEE_TYPE, STATUS, CONTRACT_TYPE, CONTRACT_NO, CHANGE_TYPE, NOTE, CREATED_AT) "
            "VALUES (%s, %s, %s, 1, 1, 'full_time', 'active', 'open_ended', '', 'hire', '', %s)",
            [start, end, employee_id, NOW],
        )


def _insert_salary(connection: Any, employee_id: int, start: dt.date, end: dt.date | None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {SALARY_TABLE} (START_DATE, END_DATE, EMPLOYEE_ID, BASE_SALARY, CHANGE_TYPE, NOTE, "  # noqa: S608
            "CREATED_AT) VALUES (%s, %s, %s, 1000.0, 'hire', '', %s)",
            [start, end, employee_id, NOW],
        )


def _job_id(connection: Any, employee_id: int, start: dt.date) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT ID FROM {JOB_TABLE} WHERE EMPLOYEE_ID = %s AND START_DATE = %s",  # noqa: S608
            [employee_id, start],
        )
        return int(cursor.fetchone()[0])


def _job_count(connection: Any, employee_id: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {JOB_TABLE} WHERE EMPLOYEE_ID = %s", [employee_id])  # noqa: S608
        return int(cursor.fetchone()[0])


def _insert_checklist(connection: Any, employee_id: int, kind: str, state: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {CHECKLIST_TABLE} (EMPLOYEE_ID, KIND, TEMPLATE_NAME, ANCHOR_DAY, STATE, CREATED_AT) "  # noqa: S608
            "VALUES (%s, %s, 'test', %s, %s, %s)",
            [employee_id, kind, JAN, state, NOW],
        )


def test_guard_objects_exist_after_migrate(fb: Any) -> None:
    with fb.cursor() as cursor:
        cursor.execute("SELECT TRIM(RDB$TRIGGER_NAME) FROM RDB$TRIGGERS WHERE RDB$TRIGGER_NAME STARTING WITH 'IHR_'")
        triggers = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT TRIM(RDB$EXCEPTION_NAME) FROM RDB$EXCEPTIONS WHERE RDB$EXCEPTION_NAME = %s", [OVERLAP])
        exceptions = [row[0] for row in cursor.fetchall()]
    assert {"IHR_JOB_OVERLAP", "IHR_SAL_OVERLAP"} <= triggers
    assert exceptions == [OVERLAP]


def test_trigger_refuses_overlap_on_insert(fb: Any) -> None:
    _insert_job(fb, 1, JAN, JUN)
    with pytest.raises(DatabaseError) as raised:
        _insert_job(fb, 1, MAR, None)
    assert OVERLAP in str(raised.value)
    assert _job_count(fb, 1) == 1


def test_trigger_allows_adjacent_rows(fb: Any) -> None:
    # End is exclusive: a period ending on 2026-03-01 does not overlap one starting that day.
    _insert_job(fb, 1, JAN, MAR)
    _insert_job(fb, 1, MAR, None)
    assert _job_count(fb, 1) == 2


def test_trigger_refuses_second_open_ended_row(fb: Any) -> None:
    _insert_job(fb, 1, JAN, None)
    with pytest.raises(DatabaseError) as raised:
        _insert_job(fb, 1, MAR, None)
    assert OVERLAP in str(raised.value)
    assert _job_count(fb, 1) == 1


def test_trigger_refuses_overlap_on_update(fb: Any) -> None:
    _insert_job(fb, 1, JAN, MAR)
    _insert_job(fb, 1, MAR, None)
    row_id = _job_id(fb, 1, MAR)
    with pytest.raises(DatabaseError) as raised, fb.cursor() as cursor:
        # Moving the open-ended row's start into the first period must be refused.
        cursor.execute(f"UPDATE {JOB_TABLE} SET START_DATE = %s WHERE ID = %s", [FEB, row_id])  # noqa: S608
    assert OVERLAP in str(raised.value)
    assert _job_id(fb, 1, MAR) == row_id  # unchanged


def test_trigger_allows_update_that_does_not_overlap(fb: Any) -> None:
    # The row is compared with itself (ID <> NEW.ID), so changing only its own end is fine.
    _insert_job(fb, 1, JAN, MAR)
    _insert_job(fb, 1, MAR, None)
    row_id = _job_id(fb, 1, JAN)
    with fb.cursor() as cursor:
        cursor.execute(f"UPDATE {JOB_TABLE} SET END_DATE = %s WHERE ID = %s", [FEB, row_id])  # noqa: S608
    with fb.cursor() as cursor:
        cursor.execute(f"SELECT END_DATE FROM {JOB_TABLE} WHERE ID = %s", [row_id])  # noqa: S608
        assert cursor.fetchone()[0] == dt.datetime(2026, 2, 1, 0, 0, 0)


def test_trigger_ignores_other_employees(fb: Any) -> None:
    _insert_job(fb, 1, JAN, None)
    _insert_job(fb, 2, MAR, None)
    assert _job_count(fb, 1) == 1
    assert _job_count(fb, 2) == 1


def test_salary_trigger_refuses_overlap_on_insert(fb: Any) -> None:
    _insert_salary(fb, 1, JAN, JUN)
    with pytest.raises(DatabaseError) as raised:
        _insert_salary(fb, 1, MAR, None)
    assert OVERLAP in str(raised.value)
    with fb.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {SALARY_TABLE} WHERE EMPLOYEE_ID = 1")  # noqa: S608
        assert int(cursor.fetchone()[0]) == 1


def test_salary_trigger_allows_adjacent_rows(fb: Any) -> None:
    _insert_salary(fb, 1, JAN, MAR)
    _insert_salary(fb, 1, MAR, None)
    with fb.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {SALARY_TABLE} WHERE EMPLOYEE_ID = 1")  # noqa: S608
        assert int(cursor.fetchone()[0]) == 2


def test_unique_index_refuses_second_open_checklist(fb: Any) -> None:
    _insert_checklist(fb, 7, "offboarding", "open")
    with pytest.raises(IntegrityError):
        _insert_checklist(fb, 7, "offboarding", "open")
    _insert_checklist(fb, 7, "onboarding", "open")  # another kind for the same employee is fine
    _insert_checklist(fb, 8, "offboarding", "open")  # and the same kind for another employee


def test_many_closed_checklists_allowed(fb: Any) -> None:
    _insert_checklist(fb, 7, "offboarding", "completed")
    _insert_checklist(fb, 7, "offboarding", "completed")
    _insert_checklist(fb, 7, "offboarding", "cancelled")
    _insert_checklist(fb, 7, "offboarding", "open")
    with fb.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {CHECKLIST_TABLE} WHERE EMPLOYEE_ID = 7")  # noqa: S608
        assert int(cursor.fetchone()[0]) == 4
