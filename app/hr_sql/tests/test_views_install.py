"""Firebird checks for the governed objects: the scope table GOV_SCOPE and the views GOV_EMPLOYEES, GOV_CHILDREN.

Firebird only. The objects are installed into the session's scratch copy (INFOHR_TEST_DB=firebird, FB_TEMPLATE_FDB)
and dropped again after each test. The `governed` alias points at the same copy as `default` (app/conftest.py).

GOV_SCOPE is a global temporary table: its rows belong to one transaction of one connection. So every test inserts
into and reads from GOV_SCOPE on the governed connection inside one atomic block. Employees are committed rows made
through the ORM on `default` (autocommit), because another connection cannot see uncommitted rows.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from django.core.management import call_command
from django.db import connections, transaction
from macs.models import Employee
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.connection import GOVERNED_ALIAS, governed_connection
from hr_sql.views import _col, _table


def _firebird_only() -> None:
    if connections["default"].vendor != "firebird":
        pytest.skip("the governed views are Firebird objects")


def _count(connection: Any, table: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 (fixed object names)
        return int(cursor.fetchone()[0])


def _fill_scope(connection: Any, ids: list[int]) -> None:
    with connection.cursor() as cursor:
        for emp_id in ids:
            cursor.execute("INSERT INTO GOV_SCOPE (EMP_ID, WORKING) VALUES (%s, 1)", [emp_id])


def _drop_objects() -> None:
    with connections["default"].cursor() as cursor:
        cursor.execute("DROP VIEW GOV_LOANS")
        cursor.execute("DROP VIEW GOV_SALARY")
        cursor.execute("DROP VIEW GOV_ORDERS")
        cursor.execute("DROP VIEW GOV_LEAVE")
        cursor.execute("DROP VIEW GOV_CHILDREN")
        cursor.execute("DROP VIEW GOV_EMPLOYEES")
        cursor.execute("DROP TABLE GOV_SCOPE")


@pytest.fixture
def governed(django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
    """Installs the governed objects (committed, autocommit) and drops them after the test."""
    _firebird_only()
    with django_db_blocker.unblock():
        call_command("governed_views", "install")
        try:
            yield
        finally:
            governed_connection().close()  # a connection that has read the objects must let go before DROP
            _drop_objects()


@pytest.fixture
def employees(django_db_blocker: DjangoDbBlocker) -> Iterator[list[int]]:
    """Three committed employees, deleted again after the test."""
    _firebird_only()
    with django_db_blocker.unblock():
        rows = [Employee.objects.create(given_name=f"Тест{i}", family_name="Тест", gender="M") for i in range(3)]
        ids = [row.pk for row in rows]
        try:
            yield ids
        finally:
            Employee.objects.filter(pk__in=ids).delete()


def test_install_twice_leaves_one_set_of_objects(governed: None) -> None:
    call_command("governed_views", "install")  # the fixture ran it once already
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT TRIM(RDB$RELATION_NAME), RDB$RELATION_TYPE FROM RDB$RELATIONS"
            " WHERE TRIM(RDB$RELATION_NAME) IN"
            " ('GOV_SCOPE', 'GOV_EMPLOYEES', 'GOV_CHILDREN', 'GOV_LEAVE', 'GOV_ORDERS', 'GOV_SALARY', 'GOV_LOANS')"
        )
        found = {str(name): int(kind) for name, kind in cursor.fetchall()}
    assert sorted(found) == [
        "GOV_CHILDREN",
        "GOV_EMPLOYEES",
        "GOV_LEAVE",
        "GOV_LOANS",
        "GOV_ORDERS",
        "GOV_SALARY",
        "GOV_SCOPE",
    ]
    assert found["GOV_SCOPE"] == 5  # global temporary table, ON COMMIT DELETE ROWS
    assert found["GOV_EMPLOYEES"] == 1  # view
    assert found["GOV_CHILDREN"] == 1  # view
    assert found["GOV_LEAVE"] == 1  # view
    assert found["GOV_ORDERS"] == 1  # view
    assert found["GOV_SALARY"] == 1  # view
    assert found["GOV_LOANS"] == 1  # view


def test_empty_scope_shows_no_employees(governed: None, employees: list[int]) -> None:
    connection = governed_connection()
    with transaction.atomic(using=GOVERNED_ALIAS):
        assert _count(connection, "GOV_EMPLOYEES") == 0
        assert _count(connection, "GOV_CHILDREN") == 0


def test_scope_shows_exactly_the_scoped_employees_that_exist(governed: None, employees: list[int]) -> None:
    connection = governed_connection()
    missing = max(employees) + 100000  # an id that is not an employee
    with transaction.atomic(using=GOVERNED_ALIAS):
        _fill_scope(connection, [employees[0], employees[1], missing])
        assert _count(connection, "GOV_EMPLOYEES") == 2
        with connection.cursor() as cursor:
            cursor.execute("SELECT EMP_ID FROM GOV_EMPLOYEES")
            assert sorted(row[0] for row in cursor.fetchall()) == sorted(employees[:2])


def test_scope_is_empty_in_a_new_transaction_after_commit(governed: None, employees: list[int]) -> None:
    connection = governed_connection()
    with transaction.atomic(using=GOVERNED_ALIAS):
        _fill_scope(connection, employees)
        assert _count(connection, "GOV_SCOPE") == len(employees)
    with transaction.atomic(using=GOVERNED_ALIAS):
        assert _count(connection, "GOV_SCOPE") == 0
        assert _count(connection, "GOV_EMPLOYEES") == 0


GOV_VIEWS = ["GOV_EMPLOYEES", "GOV_CHILDREN", "GOV_LEAVE", "GOV_ORDERS", "GOV_SALARY", "GOV_LOANS"]


def _field_names(relation: str) -> list[str]:
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT TRIM(RDB$FIELD_NAME) FROM RDB$RELATION_FIELDS WHERE TRIM(RDB$RELATION_NAME) = %s"
            " ORDER BY RDB$FIELD_POSITION",
            [relation],
        )
        return [str(row[0]) for row in cursor.fetchall()]


def test_install_upgrades_an_old_scope_table(governed: None, employees: list[int]) -> None:
    """A database installed before the WORKING column existed: install replaces the old table and views, and a second
    run changes nothing."""
    governed_connection().close()  # let go of the new objects before they are dropped
    _drop_objects()
    old_scope = "CREATE GLOBAL TEMPORARY TABLE GOV_SCOPE (EMP_ID INTEGER NOT NULL PRIMARY KEY) ON COMMIT DELETE ROWS"
    # The old GOV_EMPLOYEES, shortened to two columns: it reads GOV_SCOPE on EMP_ID only, as the old view did.
    old_view = (
        f"CREATE VIEW GOV_EMPLOYEES (EMP_ID, FIRST_NAME) AS"  # noqa: S608 (names from the models)
        f" SELECT e.{_col(Employee, 'id')}, e.{_col(Employee, 'given_name')} FROM {_table(Employee)} e"
        f" WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = e.{_col(Employee, 'id')})"
    )
    with connections["default"].cursor() as cursor:
        cursor.execute(old_scope)
        cursor.execute(old_view)
    assert _field_names("GOV_SCOPE") == ["EMP_ID"]

    call_command("governed_views", "install")

    assert _field_names("GOV_SCOPE") == ["EMP_ID", "WORKING"]
    employee_columns = _field_names("GOV_EMPLOYEES")
    assert len(employee_columns) == 10
    assert employee_columns[-1] == "WORKING"
    connection = governed_connection()
    with transaction.atomic(using=GOVERNED_ALIAS):
        _fill_scope(connection, employees[:1])
        assert _count(connection, "GOV_EMPLOYEES") == 1
        with connection.cursor() as cursor:
            cursor.execute("SELECT EMP_ID, WORKING FROM GOV_EMPLOYEES")
            rows = cursor.fetchall()
        assert [int(row[0]) for row in rows] == employees[:1]
        assert [int(row[1]) for row in rows] == [1]
    with transaction.atomic(using=GOVERNED_ALIAS):
        for view in GOV_VIEWS:
            assert _count(connection, view) == 0  # every view exists again and can be read

    before = (_field_names("GOV_SCOPE"), _field_names("GOV_EMPLOYEES"))
    call_command("governed_views", "install")  # a second run: nothing changes
    assert (_field_names("GOV_SCOPE"), _field_names("GOV_EMPLOYEES")) == before
