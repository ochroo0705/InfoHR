"""The governed departments view (Task 11): GOV_DEPARTMENTS, on Firebird, through run_question.

Firebird only. The two test departments are committed (autocommit on `default`), because the governed connection is
another connection and sees only committed rows. The department of emp_a and emp_b is set for the test and put back
in `finally`; the departments are removed there too.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from macs.models import Department, Employee
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.tests.conftest import World
from hr_sql.tests.expected import OPEN_VIEWS
from hr_sql.tests.govhelpers import columns, id_list, refusal, rows

DEPARTMENT_COLUMNS = ["DEPARTMENT_ID", "DEPARTMENT_NAME", "HEADCOUNT"]
DISMISSED = 3  # a MACS emptype the employee list counts as not working (LEGACY_NOT_WORKING)


@dataclass(frozen=True)
class Made:
    world: World
    dept_id: int  # emp_a (branch A) and emp_b (branch B) are both in this department, both working
    empty_dept_id: int  # no employee at all


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Two committed departments; emp_a and emp_b are moved into the first. Everything is put back after the test."""
    with django_db_blocker.unblock():
        tag = uuid.uuid4().hex[:6]
        dept = Department.objects.create(name=f"Тест А {tag}")
        empty = Department.objects.create(name=f"Тест Б {tag}")
        people = [ready.emp_a.pk, ready.emp_b.pk]
        before = dict(Employee.objects.filter(pk__in=people).values_list("pk", "department_id"))
        try:
            Employee.objects.filter(pk__in=people).update(department=dept)
            yield Made(world=ready, dept_id=dept.pk, empty_dept_id=empty.pk)
        finally:
            for pk, dep_id in before.items():
                Employee.objects.filter(pk=pk).update(department=dep_id)
            Department.objects.filter(pk__in=[dept.pk, empty.pk]).delete()


def _headcount(user_rows: list[tuple[object, ...]]) -> list[int]:
    return [int(str(row[0])) for row in user_rows]


def test_departments_headcount_scope(made: Made) -> None:
    world = made.world
    sql = f"SELECT HEADCOUNT FROM GOV_DEPARTMENTS WHERE DEPARTMENT_ID = {made.dept_id}"  # noqa: S608 (ids are ints)

    assert _headcount(rows(world.hr, sql)) == [2]  # HR sees both working employees
    assert _headcount(rows(world.limited, sql)) == [1]  # branch A only: emp_b is not counted
    assert _headcount(rows(world.own, sql)) == [1]  # own record only: emp_a


def test_departments_headcount_excludes_not_working(made: Made) -> None:
    """A person who is not working (legacy dismissed code, no job record) is not counted, so HR sees one less."""
    world = made.world
    sql = f"SELECT HEADCOUNT FROM GOV_DEPARTMENTS WHERE DEPARTMENT_ID = {made.dept_id}"  # noqa: S608 (ids are ints)
    before = dict(Employee.objects.filter(pk=world.emp_b.pk).values_list("pk", "emptype"))
    try:
        Employee.objects.filter(pk=world.emp_b.pk).update(emptype=DISMISSED)
        assert _headcount(rows(world.hr, sql)) == [1]  # emp_b has left: only emp_a is counted
    finally:
        for pk, emptype in before.items():
            Employee.objects.filter(pk=pk).update(emptype=emptype)


def test_departments_columns(ready: World) -> None:
    assert columns("GOV_DEPARTMENTS") == DEPARTMENT_COLUMNS


def test_departments_every_department_listed(made: Made) -> None:
    ids = id_list([made.dept_id, made.empty_dept_id])
    sql = f"SELECT DEPARTMENT_ID, HEADCOUNT FROM GOV_DEPARTMENTS WHERE DEPARTMENT_ID IN ({ids})"  # noqa: S608 (ids are ints)
    listed = {int(str(dep)): int(str(count)) for dep, count in rows(made.world.hr, sql)}
    assert listed == {made.dept_id: 2, made.empty_dept_id: 0}  # a department with no staff in scope counts 0


def test_departments_gate(made: Made) -> None:
    assert "GOV_DEPARTMENTS" in OPEN_VIEWS
    sql = f"SELECT DEPARTMENT_ID FROM GOV_DEPARTMENTS WHERE DEPARTMENT_ID = {made.dept_id}"  # noqa: S608 (id is an int)
    assert rows(made.world.hr, sql)
    assert rows(made.world.own, sql)
    assert rows(made.world.accountant, sql)
    # a user with no record and no right, and an inactive user, are outside the catalogue
    assert "not a governed view" in refusal(made.world.nobody, sql)
    assert "not a governed view" in refusal(made.world.inactive, sql)
