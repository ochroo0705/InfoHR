"""NULL bound parameters reach Firebird as a literal NULL (plan 3, Task 1).

Firebird checks a bound NULL against CHECK constraints by its text length, so a parameter bound as NULL into a column
such as EMPLOYEE.BLOOD_TYPE fails with "string right truncation". A literal NULL in the SQL text does not fail.
``FirebirdCursorWrapper.execute`` therefore writes ``NULL`` into the SQL at every None placeholder.
"""

from typing import Any

import pytest

from infohr_firebird.base import FirebirdCursorWrapper
from infohr_firebird.tests.test_settings_seam import result_of, run_django


class _FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def execute(self, query: str, params: Any) -> None:
        self.calls.append((query, params))


def _wrapper() -> tuple[FirebirdCursorWrapper, _FakeCursor]:
    cursor = _FakeCursor()
    return FirebirdCursorWrapper(cursor, "UTF8", autocommit=False), cursor


def test_none_parameter_becomes_literal_null() -> None:
    wrapper, cursor = _wrapper()
    wrapper.execute("a=%s AND b=%s AND c=%s", [1, None, "x"])
    assert cursor.calls == [("a=? AND b=NULL AND c=?", [1, "x"])]


def test_all_none_parameters_leave_no_placeholders() -> None:
    wrapper, cursor = _wrapper()
    wrapper.execute("INSERT INTO t (a, b) VALUES (%s, %s)", [None, None])
    assert cursor.calls == [("INSERT INTO t (a, b) VALUES (NULL, NULL)", [])]


def test_question_mark_inside_string_literal_is_not_a_placeholder() -> None:
    wrapper, cursor = _wrapper()
    wrapper.execute("SELECT 'why?' AS q, %s AS a, %s AS b FROM rdb$database", [None, 2])
    assert cursor.calls == [("SELECT 'why?' AS q, NULL AS a, ? AS b FROM rdb$database", [2])]


def test_escaped_quote_inside_string_literal_is_handled() -> None:
    wrapper, cursor = _wrapper()
    wrapper.execute("SELECT 'it''s ?' , %s FROM rdb$database", [None])
    assert cursor.calls == [("SELECT 'it''s ?' , NULL FROM rdb$database", [])]


def test_percent_escape_is_untouched() -> None:
    wrapper, cursor = _wrapper()
    wrapper.execute("SELECT '%%s' AS lit, %s AS a FROM rdb$database", [None])
    assert cursor.calls == [("SELECT '%s' AS lit, NULL AS a FROM rdb$database", [])]


def test_query_without_none_is_unchanged() -> None:
    wrapper, cursor = _wrapper()
    wrapper.execute("a=%s AND b=%s", [1, "x"])
    assert cursor.calls == [("a=? AND b=?", [1, "x"])]


def test_placeholder_count_mismatch_still_raises() -> None:
    wrapper, _cursor = _wrapper()
    with pytest.raises(TypeError):
        wrapper.execute("a=%s", [1, None])


INSERT_CODE = """
import json
import django
django.setup()
from macs.models import Employee
employee = Employee(
    family_name="Т", given_name="Б", gender="M", hr_flag="no", sector_years=0, emptype=1,
    status="active", contract_flag="no",
)
employee.save(force_insert=True)
fresh = Employee.objects.get(pk=employee.pk)
print("RESULT " + json.dumps({
    "pk": employee.pk,
    "blood_type": fresh.blood_type,
    "military_service": fresh.military_service,
}))
"""


def test_insert_employee_with_unset_check_columns(migrated_clone: str) -> None:
    data = result_of(run_django(INSERT_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    assert data["pk"] is not None
    assert data["blood_type"] is None
    assert data["military_service"] is None
