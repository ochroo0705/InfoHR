"""The governed education view (Task 2): GOV_EDUCATION, on Firebird, through run_question.

Firebird only. Education rows are committed (autocommit on `default`), because the governed connection is another
connection and sees only committed rows. The rows are removed again after each test.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from macs.models import EducRow, EduType
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.tests.conftest import World
from hr_sql.tests.expected import PERSONAL_VIEWS
from hr_sql.tests.govhelpers import columns, id_list, refusal, rows

EDUCATION_COLUMNS = ["EDUCATION_ID", "EMP_ID", "EDUCATION_TYPE_NAME", "START_DATE", "START_YEAR"]


@dataclass(frozen=True)
class Made:
    world: World
    emp_a_ids: list[int]  # education rows of emp_a (branch A)
    emp_b_ids: list[int]  # education rows of emp_b (branch B)


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Committed education rows for emp_a (branch A) and emp_b (branch B). Removed after the test."""
    tag = uuid.uuid4().hex[:6]
    row_ids: list[int] = []
    type_ids: list[int] = []
    with django_db_blocker.unblock():
        try:
            type_one = EduType.objects.create(name=f"Тест боловсрол 1 {tag}")
            type_two = EduType.objects.create(name=f"Тест боловсрол 2 {tag}")
            type_ids = [type_one.pk, type_two.pk]
            emp_a_rows = [
                EducRow.objects.create(
                    employee=ready.emp_a, edu_type=type_one, startdate=date(2001, 9, 1), start_year=2001
                ),
                EducRow.objects.create(
                    employee=ready.emp_a, edu_type=type_two, startdate=date(2005, 9, 1), start_year=2005
                ),
                # no start date: the view shows the start year only
                EducRow.objects.create(employee=ready.emp_a, edu_type=type_one, startdate=None, start_year=2010),
            ]
            emp_b_rows = [
                EducRow.objects.create(
                    employee=ready.emp_b, edu_type=type_one, startdate=date(2003, 9, 1), start_year=2003
                ),
            ]
            row_ids = [row.pk for row in [*emp_a_rows, *emp_b_rows]]
            yield Made(
                world=ready,
                emp_a_ids=[row.pk for row in emp_a_rows],
                emp_b_ids=[row.pk for row in emp_b_rows],
            )
        finally:
            EducRow.objects.filter(pk__in=row_ids).delete()
            EduType.objects.filter(pk__in=type_ids).delete()


def test_education_scope(made: Made) -> None:
    world = made.world
    ids = [*made.emp_a_ids, *made.emp_b_ids]
    sql = f"SELECT EDUCATION_ID FROM GOV_EDUCATION WHERE EDUCATION_ID IN ({id_list(ids)})"  # noqa: S608 (ids are ints)

    hr_ids = {int(str(row[0])) for row in rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in rows(world.limited, sql)}
    own_ids = {int(str(row[0])) for row in rows(world.own, sql)}

    assert hr_ids == set(ids)
    assert set(made.emp_a_ids) <= limited_ids  # branch A rows
    assert not set(made.emp_b_ids) & limited_ids  # branch B rows are outside the branch limit
    assert own_ids == set(made.emp_a_ids)  # own record only

    # many rows per person: three education rows for emp_a and one for emp_b, so two people
    people = rows(
        world.hr,
        f"SELECT COUNT(DISTINCT EMP_ID) FROM GOV_EDUCATION WHERE EDUCATION_ID IN ({id_list(ids)})",  # noqa: S608
    )
    assert int(str(people[0][0])) == 2


def test_education_columns(ready: World) -> None:
    assert columns("GOV_EDUCATION") == EDUCATION_COLUMNS


def test_education_has_no_text_columns(ready: World) -> None:
    assert set(columns("GOV_EDUCATION")) == set(EDUCATION_COLUMNS)


def test_education_gate(made: Made) -> None:
    assert "GOV_EDUCATION" in PERSONAL_VIEWS
    sql = "SELECT EDUCATION_ID FROM GOV_EDUCATION"
    assert rows(made.world.hr, sql)
    assert rows(made.world.own, sql)
    # the accountant holds no personal right, and a user with no record and no right is outside the catalogue
    assert "not a governed view" in refusal(made.world.accountant, sql)
    assert "not a governed view" in refusal(made.world.nobody, sql)
