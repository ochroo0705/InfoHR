"""Unique and foreign-key violations on Firebird reach Django as IntegrityError.

The app's duplicate messages depend on the class (IntegrityError) and on the constraint name in the
message. This file checks the class for the two Firebird codes that matter: 335544665 (a unique or
primary key violation, sqlcode -803) and 335544466 (a foreign key violation, sqlcode -530). Both run as
raw SQL on a scratch table pair in the cloned template database (fb_alias).
"""

from typing import Any

import pytest
from django.db import IntegrityError, connections
from firebird.driver import DatabaseError as FbDatabaseError  # type: ignore[import-untyped]

PARENT = "IHR_T_INTEG_P"
CHILD = "IHR_T_INTEG_C"
UNIQUE_INDEX = "IHR_T_INTEG_CODE"
# A unique violation reports 335544665 ("violation of PRIMARY or UNIQUE KEY") when the row was committed by
# another transaction, and 335544349 ("duplicate value visible to active transactions") within one transaction.
FB_UNIQUE_VIOLATIONS = frozenset({335544665, 335544349})
FB_FOREIGN_KEY_VIOLATION = 335544466


@pytest.fixture
def integrity_tables(fb_alias: str) -> Any:
    connection: Any = connections[fb_alias]
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE TABLE {PARENT} (ID INTEGER NOT NULL PRIMARY KEY, CODE VARCHAR(20) NOT NULL)")
        cursor.execute(f"CREATE UNIQUE INDEX {UNIQUE_INDEX} ON {PARENT} (CODE)")
        cursor.execute(
            f"CREATE TABLE {CHILD} (ID INTEGER NOT NULL PRIMARY KEY, "
            f"PARENT_ID INTEGER NOT NULL REFERENCES {PARENT} (ID))"
        )
    try:
        yield connection
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE {CHILD}")
            cursor.execute(f"DROP TABLE {PARENT}")


def _firebird_error_of(excinfo: pytest.ExceptionInfo[IntegrityError]) -> FbDatabaseError:
    cause = excinfo.value.__context__
    assert isinstance(cause, FbDatabaseError), f"no Firebird error under the IntegrityError: {cause!r}"
    return cause


def test_unique_violation_is_integrity_error(integrity_tables: Any) -> None:
    with integrity_tables.cursor() as cursor:
        cursor.execute(f"INSERT INTO {PARENT} (ID, CODE) VALUES (1, 'A')")  # noqa: S608
        with pytest.raises(IntegrityError) as excinfo:
            cursor.execute(f"INSERT INTO {PARENT} (ID, CODE) VALUES (2, 'A')")  # noqa: S608
    assert FB_UNIQUE_VIOLATIONS.intersection(_firebird_error_of(excinfo).gds_codes)
    assert excinfo.value.args[1] == -803  # sqlcode
    assert UNIQUE_INDEX in str(excinfo.value).upper()


def test_foreign_key_violation_is_integrity_error(integrity_tables: Any) -> None:
    with integrity_tables.cursor() as cursor:
        with pytest.raises(IntegrityError) as excinfo:
            cursor.execute(f"INSERT INTO {CHILD} (ID, PARENT_ID) VALUES (1, 999)")  # noqa: S608
    assert FB_FOREIGN_KEY_VIOLATION in _firebird_error_of(excinfo).gds_codes
    assert excinfo.value.args[1] == -530  # sqlcode
