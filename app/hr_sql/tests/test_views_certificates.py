"""The governed certificates view (Task 4): GOV_CERTIFICATES, on Firebird, through run_question.

Firebird only. Certificate rows and their type are committed (autocommit on `default`), because the governed
connection is another connection and sees only committed rows. The rows are removed again after each test.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from macs.models import CertificateRow, SpecEduType
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.tests.conftest import World
from hr_sql.tests.expected import PERSONAL_VIEWS
from hr_sql.tests.govhelpers import columns, id_list, refusal, rows

CERTIFICATE_COLUMNS = [
    "CERTIFICATE_ID",
    "EMP_ID",
    "CERTIFICATE_TYPE_NAME",
    "ORGANISATION",
    "CERTIFICATE_NUMBER",
    "CERTIFICATE_DATE",
    "END_DATE",
    "PROFESSION",
    "SPECIAL_PROFESSION",
    "CERTIFICATE_YEAR",
]


@dataclass(frozen=True)
class Made:
    world: World
    emp_a_ids: list[int]  # certificate rows of emp_a (branch A); two rows, so one person has two
    emp_b_ids: list[int]  # certificate rows of emp_b (branch B)


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Committed certificate rows for emp_a (branch A) and emp_b (branch B). Removed after the test."""
    tag = uuid.uuid4().hex[:6]
    row_ids: list[int] = []
    type_ids: list[int] = []
    with django_db_blocker.unblock():
        try:
            cert_type = SpecEduType.objects.create(name=f"Тест төрөл {tag}")
            type_ids = [cert_type.pk]
            first_a = CertificateRow.objects.create(
                employee=ready.emp_a,
                cert_type=cert_type,
                org_edu=f"Тест {tag}",
                certify_number="C-100",
                certify_date=date(2015, 3, 1),
                end_date=date(2020, 3, 1),
                profession="Эмч",
                spec_profession="Мэс засал",
                certify_year=2015,
            )
            second_a = CertificateRow.objects.create(
                employee=ready.emp_a,
                cert_type=cert_type,
                org_edu=f"Тест {tag} 2",
                certify_number="C-101",
                certify_date=date(2018, 6, 1),
                end_date=None,
                profession="Эмч",
                spec_profession="",
                certify_year=2018,
            )
            row_b = CertificateRow.objects.create(
                employee=ready.emp_b,
                cert_type=cert_type,
                org_edu=f"Тест {tag} Б",
                certify_number="C-200",
                certify_date=date(2016, 1, 1),
                end_date=None,
                profession="Багш",
                spec_profession="",
                certify_year=2016,
            )
            emp_a_rows = [first_a, second_a]
            row_ids = [row.pk for row in [*emp_a_rows, row_b]]
            yield Made(
                world=ready,
                emp_a_ids=[row.pk for row in emp_a_rows],
                emp_b_ids=[row_b.pk],
            )
        finally:
            CertificateRow.objects.filter(pk__in=row_ids).delete()
            SpecEduType.objects.filter(pk__in=type_ids).delete()


def test_certificates_scope(made: Made) -> None:
    world = made.world
    ids = [*made.emp_a_ids, *made.emp_b_ids]
    sql = f"SELECT CERTIFICATE_ID FROM GOV_CERTIFICATES WHERE CERTIFICATE_ID IN ({id_list(ids)})"  # noqa: S608 (ids are ints)

    hr_ids = {int(str(row[0])) for row in rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in rows(world.limited, sql)}
    own_ids = {int(str(row[0])) for row in rows(world.own, sql)}

    assert hr_ids == set(ids)  # HR sees both branches
    assert limited_ids == set(made.emp_a_ids)  # the branch limit keeps branch B out
    assert own_ids == set(made.emp_a_ids)  # own record only

    # many rows per person: two certificate rows for emp_a and one for emp_b, so two people
    people = rows(
        world.hr,
        f"SELECT COUNT(DISTINCT EMP_ID) FROM GOV_CERTIFICATES WHERE CERTIFICATE_ID IN ({id_list(ids)})",  # noqa: S608
    )
    assert int(str(people[0][0])) == 2


def test_certificates_columns(ready: World) -> None:
    assert columns("GOV_CERTIFICATES") == CERTIFICATE_COLUMNS


def test_certificates_gate(made: Made) -> None:
    assert "GOV_CERTIFICATES" in PERSONAL_VIEWS
    sql = "SELECT CERTIFICATE_ID FROM GOV_CERTIFICATES"
    assert rows(made.world.hr, sql)
    assert rows(made.world.own, sql)
    # the accountant holds no personal right, and a user with no record and no right is outside the catalogue
    assert "not a governed view" in refusal(made.world.accountant, sql)
    assert "not a governed view" in refusal(made.world.nobody, sql)
