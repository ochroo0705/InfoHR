"""Constraints are never disabled on the shared MACS database (fix wave, finding 1).

Django calls disable_constraint_checking() from loaddata and from TransactionTestCase flushes.
The original django-firebird code dropped every foreign key, check and unique constraint in the
whole database (including MACS's) and rebuilt them later. HR shares the file with MACS, so that
path must be a no-op here. These tests run on the clone only and compare the whole database
fingerprint (no ignored prefix) before and after.
"""

from typing import Any

import pytest
from django.db import NotSupportedError, connections

from infohr_firebird.structure import existing_tables, fingerprint

NOT_SUPPORTED_MESSAGE = "Firebird constraints are never disabled: HR shares the database with MACS"


def _whole_database(connection: Any) -> dict[str, tuple[int, str]]:
    with connection.cursor() as cursor:
        return fingerprint(cursor, ())


def _table_names(connection: Any) -> set[str]:
    with connection.cursor() as cursor:
        return existing_tables(cursor)


def _count_employees(connection: Any) -> int:
    with connection.cursor() as cursor:
        cursor.execute("select count(*) from employee")
        row = cursor.fetchone()
    return int(row[0])


def test_constraint_checks_disabled_changes_nothing(fb_alias: str) -> None:
    connection: Any = connections[fb_alias]
    fingerprint_before = _whole_database(connection)
    tables_before = _table_names(connection)

    with connection.constraint_checks_disabled():
        _count_employees(connection)

    assert "DJANGO$CONSTRAINT" not in _table_names(connection)
    assert "DJANGO$CONSTRAINT_SEGMENT" not in _table_names(connection)
    assert _table_names(connection) == tables_before
    assert _whole_database(connection) == fingerprint_before


def test_constraint_checks_disabled_with_work_inside_changes_nothing(fb_alias: str) -> None:
    connection: Any = connections[fb_alias]
    fingerprint_before = _whole_database(connection)
    employees_before = _count_employees(connection)

    with connection.constraint_checks_disabled():
        assert _count_employees(connection) == employees_before

    assert _count_employees(connection) == employees_before
    assert "DJANGO$CONSTRAINT" not in _table_names(connection)
    assert _whole_database(connection) == fingerprint_before


def test_disable_constraint_checking_returns_false(fb_alias: str) -> None:
    connection: Any = connections[fb_alias]
    fingerprint_before = _whole_database(connection)

    assert connection.disable_constraint_checking() is False

    assert _whole_database(connection) == fingerprint_before


def test_enable_constraint_checking_does_nothing(fb_alias: str) -> None:
    connection: Any = connections[fb_alias]
    fingerprint_before = _whole_database(connection)

    connection.enable_constraint_checking()

    assert _whole_database(connection) == fingerprint_before


def test_disable_constraints_raises(fb_alias: str) -> None:
    connection: Any = connections[fb_alias]
    fingerprint_before = _whole_database(connection)

    with pytest.raises(NotSupportedError, match="never disabled") as raised:
        connection.disable_constraints()

    assert str(raised.value) == NOT_SUPPORTED_MESSAGE
    assert _whole_database(connection) == fingerprint_before


def test_enable_constraints_raises(fb_alias: str) -> None:
    connection: Any = connections[fb_alias]
    fingerprint_before = _whole_database(connection)

    with pytest.raises(NotSupportedError, match="never disabled"):
        connection.enable_constraints()

    assert _whole_database(connection) == fingerprint_before
