"""The governed entitlement view (Task 9): GOV_ENTITLEMENTS, on Firebird, through run_question.

Firebird only. Entitlement and leave rows are committed (autocommit on `default`), because the governed connection is
another connection and sees only committed rows. The rows are removed again after each test.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from macs.models import Entitlement, LeaveAssign, LeaveTypeRow
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.tests.conftest import World
from hr_sql.tests.expected import OPEN_VIEWS
from hr_sql.tests.govhelpers import columns, id_list, refusal, rows

ENTITLEMENT_COLUMNS = ["ENTITLEMENT_ID", "EMP_ID", "LEAVE_TYPE_NAME", "START_DATE", "END_DATE", "DAYS"]
PRIVATE_COMMENT = "private entitlement text"
APPROVED_LEAVE_DAYS = 5


@dataclass(frozen=True)
class Made:
    world: World
    type_name: str  # the leave type name shared by the entitlements and the leave row of emp_a
    emp_a_ids: list[int]  # entitlement rows of emp_a (branch A): a grant of 20 days and a deduction of 2
    emp_b_id: int  # an entitlement row of emp_b (branch B)


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Committed entitlement rows for emp_a (branch A) and emp_b (branch B), and one approved leave of emp_a.

    Removed after the test.
    """
    tag = uuid.uuid4().hex[:6]
    entitlement_ids: list[int] = []
    leave_ids: list[int] = []
    leave_type: LeaveTypeRow | None = None
    with django_db_blocker.unblock():
        try:
            leave_type = LeaveTypeRow.objects.create(name=f"Тест эрх {tag}")
            # Each row has its own dates: the table has a unique key on employee, type and dates.
            grant = Entitlement.objects.create(
                employee=ready.emp_a,
                leave_type=leave_type,
                date1=date(2026, 1, 1),
                date2=date(2026, 12, 31),
                ent_days=20,
                comment=PRIVATE_COMMENT,
            )
            deduction = Entitlement.objects.create(
                employee=ready.emp_a,
                leave_type=leave_type,
                date1=date(2026, 6, 1),
                date2=date(2026, 6, 2),
                ent_days=-2,
                comment=PRIVATE_COMMENT,
            )
            emp_b_row = Entitlement.objects.create(
                employee=ready.emp_b,
                leave_type=leave_type,
                date1=date(2026, 1, 1),
                date2=date(2026, 12, 31),
                ent_days=20,
                comment=PRIVATE_COMMENT,
            )
            entitlement_ids = [grant.pk, deduction.pk, emp_b_row.pk]
            taken = LeaveAssign.objects.create(
                employee=ready.emp_a,
                leave_type=leave_type,
                date1=date(2026, 3, 1),
                date2=date(2026, 3, 5),
                status=LeaveAssign.APPROVED,
                adays=APPROVED_LEAVE_DAYS,
            )
            leave_ids = [taken.pk]
            yield Made(
                world=ready,
                type_name=leave_type.name,
                emp_a_ids=[grant.pk, deduction.pk],
                emp_b_id=emp_b_row.pk,
            )
        finally:
            LeaveAssign.objects.filter(pk__in=leave_ids).delete()
            Entitlement.objects.filter(pk__in=entitlement_ids).delete()
            if leave_type is not None:
                LeaveTypeRow.objects.filter(pk=leave_type.pk).delete()


def test_entitlements_scope(made: Made) -> None:
    world = made.world
    ids = [*made.emp_a_ids, made.emp_b_id]
    sql = f"SELECT ENTITLEMENT_ID FROM GOV_ENTITLEMENTS WHERE ENTITLEMENT_ID IN ({id_list(ids)})"  # noqa: S608 (ints)

    hr_ids = {int(str(row[0])) for row in rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in rows(world.limited, sql)}
    own_ids = {int(str(row[0])) for row in rows(world.own, sql)}

    assert hr_ids == set(ids)  # HR sees both branches
    assert limited_ids == set(made.emp_a_ids)  # the branch limit keeps branch B out
    assert own_ids == set(made.emp_a_ids)  # own record only


def test_entitlements_columns(ready: World) -> None:
    assert columns("GOV_ENTITLEMENTS") == ENTITLEMENT_COLUMNS
    assert "COMMENT" not in columns("GOV_ENTITLEMENTS")


def test_entitlements_hide_comment(made: Made) -> None:
    ids = [*made.emp_a_ids, made.emp_b_id]
    every_column = ", ".join(ENTITLEMENT_COLUMNS)  # the governed checker refuses SELECT *, so name all six
    listing = rows(
        made.world.hr,
        f"SELECT {every_column} FROM GOV_ENTITLEMENTS WHERE ENTITLEMENT_ID IN ({id_list(ids)})",  # noqa: S608 (ints)
    )

    assert len(listing) == len(ids)
    for row in listing:
        for cell in row:
            assert PRIVATE_COMMENT not in str(cell)


def test_entitlements_balance(made: Made) -> None:
    # The balance of emp_a for the leave type: the grants and deductions (+20, -2) minus the approved leave (5).
    emp = made.world.emp_a.pk
    name = made.type_name
    sql = (
        f"SELECT (SELECT SUM(e.DAYS) FROM GOV_ENTITLEMENTS e WHERE e.EMP_ID = {emp} AND e.LEAVE_TYPE_NAME = '{name}')"  # noqa: S608
        f" - (SELECT SUM(l.DAYS) FROM GOV_LEAVE l WHERE l.EMP_ID = {emp} AND l.LEAVE_TYPE_NAME = '{name}'"  # noqa: S608
        " AND l.STATUS_NAME = 'approved')"
        f" FROM GOV_EMPLOYEES WHERE EMP_ID = {emp}"  # noqa: S608 (ints and a name of this test)
    )

    balance = rows(made.world.hr, sql)

    assert int(str(balance[0][0])) == 13  # 20 - 2 - 5


def test_entitlements_gate(made: Made) -> None:
    assert "GOV_ENTITLEMENTS" in OPEN_VIEWS
    sql = "SELECT ENTITLEMENT_ID FROM GOV_ENTITLEMENTS"
    assert rows(made.world.hr, sql)
    assert rows(made.world.own, sql)
    assert rows(made.world.accountant, sql)
    assert "not a governed view" in refusal(made.world.nobody, sql)
    assert "not a governed view" in refusal(made.world.inactive, sql)
