"""The governed qualifications view (Task 3): GOV_QUALIFICATIONS, on Firebird, through run_question.

Firebird only. Qualification rows and their code lists are committed (autocommit on `default`), because the governed
connection is another connection and sees only committed rows. The rows are removed again after each test.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from macs.models import AcademicDegree, EducationLevel, ProfessionType, QualificationRow, QualificationType
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.tests.conftest import World
from hr_sql.tests.expected import PERSONAL_VIEWS
from hr_sql.tests.govhelpers import columns, id_list, refusal, rows

QUALIFICATION_COLUMNS = [
    "QUALIFICATION_ID",
    "EMP_ID",
    "QUALIFICATION_TYPE_NAME",
    "PROFESSION_NAME",
    "ORGANISATION",
    "DIPLOMA_NUMBER",
    "START_DATE",
    "END_DATE",
    "START_YEAR",
    "END_YEAR",
    "EDUCATION_LEVEL_NAME",
    "DEGREE_NAME",
    "COUNTRY",
]


@dataclass(frozen=True)
class Made:
    world: World
    emp_a_ids: list[int]  # qualification rows of emp_a (branch A); the last one has no type ids at all
    emp_b_ids: list[int]  # qualification rows of emp_b (branch B)
    empty_id: int  # the row of emp_a whose type, profession, level and degree are all empty


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Committed qualification rows for emp_a (branch A) and emp_b (branch B). Removed after the test."""
    tag = uuid.uuid4().hex[:6]
    row_ids: list[int] = []
    type_ids: list[int] = []
    level_ids: list[int] = []
    degree_ids: list[int] = []
    profession_ids: list[int] = []
    with django_db_blocker.unblock():
        try:
            qual_type = QualificationType.objects.create(name=f"Тест мэргэшил {tag}")
            profession = ProfessionType.objects.create(name=f"Тест мэргэжил {tag}")
            level = EducationLevel.objects.create(name=f"Тест түвшин {tag}")
            degree = AcademicDegree.objects.create(name=f"Тест зэрэг {tag}")
            type_ids = [qual_type.pk]
            profession_ids = [profession.pk]
            level_ids = [level.pk]
            degree_ids = [degree.pk]
            full_a = QualificationRow.objects.create(
                employee=ready.emp_a,
                qualification_type=qual_type,
                profession_type=profession,
                org_name=f"Тест байгууллага {tag}",
                diplom_number="A-100",
                start_date=date(2010, 9, 1),
                ending_date=date(2014, 6, 30),
                country="Монгол",
                edu_level=level,
                grade=degree,
                start_year=2010,
                end_year=2014,
            )
            # all four type ids empty: the row must still be listed, with empty names
            empty_a = QualificationRow.objects.create(
                employee=ready.emp_a,
                qualification_type=None,
                profession_type=None,
                org_name=f"Тест байгууллага {tag} хоосон",
                start_year=2015,
                end_year=2016,
                edu_level=None,
                grade=None,
            )
            full_b = QualificationRow.objects.create(
                employee=ready.emp_b,
                qualification_type=qual_type,
                profession_type=None,
                org_name=f"Тест байгууллага {tag} Б",
                start_year=2012,
                end_year=2013,
                edu_level=level,
                grade=None,
            )
            emp_a_rows = [full_a, empty_a]
            emp_b_rows = [full_b]
            row_ids = [row.pk for row in [*emp_a_rows, *emp_b_rows]]
            yield Made(
                world=ready,
                emp_a_ids=[row.pk for row in emp_a_rows],
                emp_b_ids=[row.pk for row in emp_b_rows],
                empty_id=empty_a.pk,
            )
        finally:
            QualificationRow.objects.filter(pk__in=row_ids).delete()
            QualificationType.objects.filter(pk__in=type_ids).delete()
            ProfessionType.objects.filter(pk__in=profession_ids).delete()
            EducationLevel.objects.filter(pk__in=level_ids).delete()
            AcademicDegree.objects.filter(pk__in=degree_ids).delete()


def test_qualifications_scope(made: Made) -> None:
    world = made.world
    ids = [*made.emp_a_ids, *made.emp_b_ids]
    sql = f"SELECT QUALIFICATION_ID FROM GOV_QUALIFICATIONS WHERE QUALIFICATION_ID IN ({id_list(ids)})"  # noqa: S608 (ids are ints)

    hr_ids = {int(str(row[0])) for row in rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in rows(world.limited, sql)}
    own_ids = {int(str(row[0])) for row in rows(world.own, sql)}

    assert hr_ids == set(ids)
    assert set(made.emp_a_ids) <= limited_ids  # branch A rows, including the row with empty type ids
    assert not set(made.emp_b_ids) & limited_ids  # branch B rows are outside the branch limit
    assert own_ids == set(made.emp_a_ids)  # own record only

    # many rows per person: two qualification rows for emp_a and one for emp_b, so two people
    people = rows(
        world.hr,
        f"SELECT COUNT(DISTINCT EMP_ID) FROM GOV_QUALIFICATIONS WHERE QUALIFICATION_ID IN ({id_list(ids)})",  # noqa: S608
    )
    assert int(str(people[0][0])) == 2


def test_qualifications_columns(ready: World) -> None:
    assert columns("GOV_QUALIFICATIONS") == QUALIFICATION_COLUMNS


def test_qualifications_gate(made: Made) -> None:
    assert "GOV_QUALIFICATIONS" in PERSONAL_VIEWS
    sql = "SELECT QUALIFICATION_ID FROM GOV_QUALIFICATIONS"
    assert rows(made.world.hr, sql)
    assert rows(made.world.own, sql)
    # the accountant holds no personal right, and a user with no record and no right is outside the catalogue
    assert "not a governed view" in refusal(made.world.accountant, sql)
    assert "not a governed view" in refusal(made.world.nobody, sql)


def test_qualifications_empty_type_ids_still_listed(made: Made) -> None:
    sql = (
        "SELECT QUALIFICATION_TYPE_NAME, PROFESSION_NAME, EDUCATION_LEVEL_NAME, DEGREE_NAME "  # noqa: S608 (id is an int)
        f"FROM GOV_QUALIFICATIONS WHERE QUALIFICATION_ID = {int(made.empty_id)}"
    )
    found = rows(made.world.hr, sql)
    assert len(found) == 1  # listed once, although its type ids are all empty
    assert all(not str(cell or "").strip() for cell in found[0])  # every name column is empty
