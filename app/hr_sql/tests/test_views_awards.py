"""The governed awards view (Task 5): GOV_AWARDS, on Firebird, through run_question.

Firebird only. Award rows are committed (autocommit on `default`), because the governed connection is another
connection and sees only committed rows. The rows are removed again after each test.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from macs.models import AwardRow
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.tests.conftest import World
from hr_sql.tests.expected import OPEN_VIEWS
from hr_sql.tests.govhelpers import columns, id_list, refusal, rows

AWARD_COLUMNS = [
    "AWARD_ID",
    "EMP_ID",
    "AWARD_NAME",
    "GIVEN_BY",
    "AWARD_DATE",
]
PRIVATE_TEXT = "private award text"


@dataclass(frozen=True)
class Made:
    world: World
    emp_a_ids: list[int]  # award rows of emp_a (branch A); two rows, so one person has two
    emp_b_ids: list[int]  # award rows of emp_b (branch B)


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Committed award rows for emp_a (branch A) and emp_b (branch B). Removed after the test."""
    tag = uuid.uuid4().hex[:6]
    row_ids: list[int] = []
    with django_db_blocker.unblock():
        try:
            first_a = AwardRow.objects.create(
                employee=ready.emp_a,
                give_org=f"Тест {tag}",
                award_name="Гавьяат ажилтан",
                award_date=date(2015, 3, 1),
                description=PRIVATE_TEXT,
            )
            second_a = AwardRow.objects.create(
                employee=ready.emp_a,
                give_org=f"Тест {tag} 2",
                award_name="Баярын тэмдэг",
                award_date=date(2018, 6, 1),
                description="",
            )
            row_b = AwardRow.objects.create(
                employee=ready.emp_b,
                give_org="",
                award_name="Талархал",
                award_date=None,
                description="",
            )
            emp_a_rows = [first_a, second_a]
            row_ids = [row.pk for row in [*emp_a_rows, row_b]]
            yield Made(
                world=ready,
                emp_a_ids=[row.pk for row in emp_a_rows],
                emp_b_ids=[row_b.pk],
            )
        finally:
            AwardRow.objects.filter(pk__in=row_ids).delete()


def test_awards_scope(made: Made) -> None:
    world = made.world
    ids = [*made.emp_a_ids, *made.emp_b_ids]
    sql = f"SELECT AWARD_ID FROM GOV_AWARDS WHERE AWARD_ID IN ({id_list(ids)})"  # noqa: S608 (ids are ints)

    hr_ids = {int(str(row[0])) for row in rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in rows(world.limited, sql)}
    own_ids = {int(str(row[0])) for row in rows(world.own, sql)}

    assert hr_ids == set(ids)  # HR sees both branches
    assert limited_ids == set(made.emp_a_ids)  # the branch limit keeps branch B out
    assert own_ids == set(made.emp_a_ids)  # own record only

    # many rows per person: two award rows for emp_a and one for emp_b, so two people
    people = rows(
        world.hr,
        f"SELECT COUNT(DISTINCT EMP_ID) FROM GOV_AWARDS WHERE AWARD_ID IN ({id_list(ids)})",  # noqa: S608
    )
    assert int(str(people[0][0])) == 2


def test_awards_columns(ready: World) -> None:
    assert columns("GOV_AWARDS") == AWARD_COLUMNS


def test_awards_hide_description(made: Made) -> None:
    ids = [*made.emp_a_ids, *made.emp_b_ids]
    every_column = ", ".join(AWARD_COLUMNS)  # the governed checker refuses SELECT *, so name all five
    listing = rows(made.world.hr, f"SELECT {every_column} FROM GOV_AWARDS WHERE AWARD_ID IN ({id_list(ids)})")  # noqa: S608
    assert len(listing) == len(ids)
    for row in listing:
        for cell in row:
            assert PRIVATE_TEXT not in str(cell)


def test_awards_gate(made: Made) -> None:
    assert "GOV_AWARDS" in OPEN_VIEWS
    sql = "SELECT AWARD_ID FROM GOV_AWARDS"
    assert rows(made.world.hr, sql)
    assert rows(made.world.own, sql)
    assert rows(made.world.accountant, sql)
    # a user with no record and no right, and an inactive user, are outside the catalogue
    assert "not a governed view" in refusal(made.world.nobody, sql)
    assert "not a governed view" in refusal(made.world.inactive, sql)
