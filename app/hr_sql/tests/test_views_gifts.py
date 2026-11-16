"""The governed gifts view (Task 6): GOV_GIFTS, on Firebird, through run_question.

Firebird only. Gift rows and their gift type are committed (autocommit on `default`), because the governed connection
is another connection and sees only committed rows. The rows are removed again after each test.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from macs.models import PresentRow, PresentType
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.tests.conftest import World
from hr_sql.tests.expected import OPEN_VIEWS
from hr_sql.tests.govhelpers import columns, id_list, refusal, rows

GIFT_COLUMNS = [
    "GIFT_ID",
    "EMP_ID",
    "GIFT_TYPE_NAME",
    "GIFT_DATE",
    "GIFT_YEAR",
    "PRICE",
    "GIVEN",
    "CHILD_COUNT",
    "CHILD_AGE",
]


@dataclass(frozen=True)
class Made:
    world: World
    type_name: str
    emp_a_ids: list[int]  # gift rows of emp_a (branch A); two rows, so one person has two
    emp_b_ids: list[int]  # gift row of emp_b (branch B)
    first_a_id: int  # the emp_a row with the gift type set, to check the type name


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Committed gift rows for emp_a (branch A) and emp_b (branch B), and one gift type. Removed after the test."""
    tag = uuid.uuid4().hex[:6]
    row_ids: list[int] = []
    type_ids: list[int] = []
    with django_db_blocker.unblock():
        try:
            gift_type = PresentType.objects.create(name=f"Тест бэлэг {tag}")
            type_ids.append(gift_type.pk)
            first_a = PresentRow.objects.create(
                employee=ready.emp_a,
                childqty=2,
                price=50000,
                given_year=2019,
                pdate=date(2019, 12, 1),
                present_type=gift_type,
                child_age=5,
                given=1,
            )
            second_a = PresentRow.objects.create(
                employee=ready.emp_a,
                childqty=1,
                price=30000,
                given_year=2020,
                pdate=date(2020, 12, 1),
                present_type=gift_type,
                child_age=0,
                given=0,
            )
            row_b = PresentRow.objects.create(
                employee=ready.emp_b,
                childqty=1,
                price=20000,
                given_year=2021,
                pdate=date(2021, 6, 1),
                present_type=gift_type,
                child_age=3,
                given=1,
            )
            emp_a_rows = [first_a, second_a]
            row_ids = [row.pk for row in [*emp_a_rows, row_b]]
            yield Made(
                world=ready,
                type_name=str(gift_type.name),
                emp_a_ids=[row.pk for row in emp_a_rows],
                emp_b_ids=[row_b.pk],
                first_a_id=first_a.pk,
            )
        finally:
            PresentRow.objects.filter(pk__in=row_ids).delete()
            PresentType.objects.filter(pk__in=type_ids).delete()


def test_gifts_scope(made: Made) -> None:
    world = made.world
    ids = [*made.emp_a_ids, *made.emp_b_ids]
    sql = f"SELECT GIFT_ID FROM GOV_GIFTS WHERE GIFT_ID IN ({id_list(ids)})"  # noqa: S608 (ids are ints)

    hr_ids = {int(str(row[0])) for row in rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in rows(world.limited, sql)}
    own_ids = {int(str(row[0])) for row in rows(world.own, sql)}

    assert hr_ids == set(ids)  # HR sees both branches
    assert limited_ids == set(made.emp_a_ids)  # the branch limit keeps branch B out
    assert own_ids == set(made.emp_a_ids)  # own record only

    # the gift type name comes through the join to PresentType
    type_rows = rows(
        world.hr,
        f"SELECT GIFT_TYPE_NAME FROM GOV_GIFTS WHERE GIFT_ID = {made.first_a_id}",  # noqa: S608 (id is an int)
    )
    assert [str(row[0]).strip() for row in type_rows] == [made.type_name]

    # many rows per person: two gift rows for emp_a and one for emp_b, so two people
    people = rows(
        world.hr,
        f"SELECT COUNT(DISTINCT EMP_ID) FROM GOV_GIFTS WHERE GIFT_ID IN ({id_list(ids)})",  # noqa: S608
    )
    assert int(str(people[0][0])) == 2


def test_gifts_columns(ready: World) -> None:
    assert columns("GOV_GIFTS") == GIFT_COLUMNS


def test_gifts_gate(made: Made) -> None:
    assert "GOV_GIFTS" in OPEN_VIEWS
    sql = "SELECT GIFT_ID FROM GOV_GIFTS"
    assert rows(made.world.hr, sql)
    assert rows(made.world.own, sql)
    assert rows(made.world.accountant, sql)
    # a user with no record and no right, and an inactive user, are outside the catalogue
    assert "not a governed view" in refusal(made.world.nobody, sql)
    assert "not a governed view" in refusal(made.world.inactive, sql)
