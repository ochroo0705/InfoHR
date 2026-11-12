"""The governed leave and order views (Task 7): GOV_LEAVE and GOV_ORDERS, on Firebird, through run_question.

Firebird only. Leave and order rows are committed (autocommit on `default`), because the governed connection is
another connection and sees only committed rows. The rows are removed again after each test.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.db import transaction
from employees.access import visible_employees
from employees.models import HrOrder, OrderState, OrderType
from macs.models import FamilyRow, LeaveAssign, LeaveTypeRow
from pytest_django.plugin import DjangoDbBlocker
from sqlcore.limits import Limits
from sqlcore.runner import DEFAULT_LIMITS, Answered, Refused, run_question

from hr_sql.connection import GOVERNED_ALIAS, governed_connection
from hr_sql.host import HrHost
from hr_sql.tests.conftest import World

ORDER_TYPE_WORDS = {1: "hired", 2: "department", 3: "position", 4: "fired", 5: "pension", 6: "type_changed"}
LEAVE_COLUMNS = ["LEAVE_ID", "EMP_ID", "LEAVE_TYPE_NAME", "START_DATE", "END_DATE", "DAYS", "STATUS_NAME"]
ORDER_COLUMNS = ["ORDER_ID", "EMP_ID", "ORDER_TYPE_NAME", "STATE_NAME", "ORDER_NUMBER", "ORDER_DATE", "SUMMARY"]
CHILDREN_COUNT = (
    "SELECT COUNT(*) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID"  # noqa: S608 (fixed names)
)
PRIVATE_REASON = "private cancel reason"
PRIVATE_COMMENT = "private leave comment"


@dataclass(frozen=True)
class Made:
    world: World
    leave_by_status: dict[str, int]  # "approved", "cancelled", "rejected", "none" -> LEAVE_ID (emp_a)
    leave_emp_b: int  # a leave row of emp_b, in branch B
    order_by_type: dict[int, int]  # OrderType value -> ORDER_ID (emp_a)
    order_emp_b: int  # an order of emp_b, cancelled, with a private reason and a file


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Committed leave and order rows for emp_a (branch A) and emp_b (branch B). Removed after the test."""
    tag = uuid.uuid4().hex[:6]
    leave_ids: list[int] = []
    order_ids: list[int] = []
    leave_type: LeaveTypeRow | None = None
    with django_db_blocker.unblock():
        try:
            leave_type = LeaveTypeRow.objects.create(name=f"Тест амралт {tag}")
            leave_by_status: dict[str, int] = {}
            for day, (label, status) in enumerate(
                [
                    ("approved", LeaveAssign.APPROVED),
                    ("cancelled", LeaveAssign.CANCELLED),
                    ("rejected", LeaveAssign.REJECTED),
                    ("none", None),
                ],
                start=1,
            ):
                # Each row has its own dates: the table has a unique key on employee, type and dates.
                row = LeaveAssign.objects.create(
                    employee=ready.emp_a,
                    leave_type=leave_type,
                    date1=date(2026, 3, day),
                    date2=date(2026, 3, day + 4),
                    status=status,
                    adays=5,
                    comment=PRIVATE_COMMENT,
                )
                leave_ids.append(row.pk)
                leave_by_status[label] = row.pk
            emp_b_leave = LeaveAssign.objects.create(
                employee=ready.emp_b,
                leave_type=leave_type,
                date1=date(2026, 4, 1),
                date2=date(2026, 4, 2),
                status=LeaveAssign.APPROVED,
                adays=2,
                comment=PRIVATE_COMMENT,
            )
            leave_ids.append(emp_b_leave.pk)

            order_by_type: dict[int, int] = {}
            for order_type in OrderType.values:
                order = HrOrder.objects.create(
                    employee=ready.emp_a,
                    is_hire=True,  # the model's check allows is_hire with no event; the test needs no event
                    order_type=order_type,
                    state=OrderState.SIGNED,
                    number=f"{order_type}-{tag}"[:10],
                    date=date(2026, 1, order_type),
                    summary=f"Тест {order_type}",
                    issued_by="test",
                )
                order_ids.append(order.pk)
                order_by_type[order_type] = order.pk
            emp_b_order = HrOrder.objects.create(
                employee=ready.emp_b,
                is_hire=True,
                order_type=OrderType.FIRED,
                state=OrderState.CANCELLED,
                number=f"B-{tag}"[:10],
                date=date(2026, 2, 2),
                summary="Тест B",
                file="2026/private-test.docx",
                cancel_reason=PRIVATE_REASON,
            )
            order_ids.append(emp_b_order.pk)
            yield Made(
                world=ready,
                leave_by_status=leave_by_status,
                leave_emp_b=emp_b_leave.pk,
                order_by_type=order_by_type,
                order_emp_b=emp_b_order.pk,
            )
        finally:
            LeaveAssign.objects.filter(pk__in=leave_ids).delete()
            HrOrder.objects.filter(pk__in=order_ids).delete()
            if leave_type is not None:
                LeaveTypeRow.objects.filter(pk=leave_type.pk).delete()


def _rows(user: User, sql: str) -> list[tuple[Any, ...]]:
    outcome = run_question(HrHost(), user, sql, DEFAULT_LIMITS)
    if isinstance(outcome, Refused):
        pytest.fail(f"Refused: {outcome.reason}")
    assert isinstance(outcome, Answered)
    return list(outcome.result.rows)


def _refusal(user: User, sql: str, limits: Limits = DEFAULT_LIMITS) -> str:
    outcome = run_question(HrHost(), user, sql, limits)
    assert isinstance(outcome, Refused), "the question should have been refused"
    return outcome.reason


def _columns(view: str) -> list[str]:
    with transaction.atomic(using=GOVERNED_ALIAS), governed_connection().cursor() as cursor:
        cursor.execute(f"SELECT * FROM {view} WHERE 1 = 0")  # noqa: S608 (fixed view names)
        return [str(column[0]).strip() for column in cursor.description or ()]


def _id_list(ids: list[int]) -> str:
    return ", ".join(str(pk) for pk in ids)


def test_leave_view_scoped_to_visible_employees(made: Made) -> None:
    world = made.world
    ids = [*made.leave_by_status.values(), made.leave_emp_b]
    sql = f"SELECT LEAVE_ID FROM GOV_LEAVE WHERE LEAVE_ID IN ({_id_list(ids)})"  # noqa: S608 (ids are ints)

    hr_ids = {int(str(row[0])) for row in _rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in _rows(world.limited, sql)}
    own_ids = {int(str(row[0])) for row in _rows(world.own, sql)}

    assert hr_ids == set(ids)
    assert set(made.leave_by_status.values()) <= limited_ids  # branch A rows
    assert made.leave_emp_b not in limited_ids  # branch B row is outside the branch limit
    assert own_ids == set(made.leave_by_status.values())  # own record only


def test_user_with_no_right_and_no_record_is_refused_leave(made: Made) -> None:
    reason = _refusal(made.world.nobody, "SELECT LEAVE_ID FROM GOV_LEAVE")

    assert "not a governed view" in reason


def test_leave_status_names(made: Made) -> None:
    ids = list(made.leave_by_status.values())
    rows = _rows(
        made.world.hr,
        f"SELECT LEAVE_ID, STATUS_NAME FROM GOV_LEAVE WHERE LEAVE_ID IN ({_id_list(ids)})",  # noqa: S608 (ints)
    )
    got = {int(str(pk)): status for pk, status in rows}

    assert got[made.leave_by_status["approved"]] == "approved"
    assert got[made.leave_by_status["cancelled"]] == "cancelled"
    assert got[made.leave_by_status["rejected"]] == "rejected"
    assert got[made.leave_by_status["none"]] is None


def test_leave_view_has_no_comment_column(ready: World) -> None:
    columns = _columns("GOV_LEAVE")

    assert columns == LEAVE_COLUMNS
    assert "COMMENT" not in columns


def test_leave_comment_text_never_reaches_an_answer(made: Made) -> None:
    rows = _rows(
        made.world.hr,
        "SELECT LEAVE_ID, EMP_ID, LEAVE_TYPE_NAME, START_DATE, END_DATE, DAYS, STATUS_NAME FROM GOV_LEAVE",
    )

    assert all(PRIVATE_COMMENT not in str(cell) for row in rows for cell in row)


def test_orders_view_names_and_scope(made: Made) -> None:
    world = made.world
    ids = [*made.order_by_type.values(), made.order_emp_b]
    ids_sql = _id_list(ids)
    sql = (
        "SELECT ORDER_ID, ORDER_TYPE_NAME, STATE_NAME, ORDER_NUMBER, ORDER_DATE, SUMMARY FROM GOV_ORDERS"  # noqa: S608
        f" WHERE ORDER_ID IN ({ids_sql})"  # ids are ints
    )

    hr_rows = {int(str(row[0])): row for row in _rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in _rows(world.limited, sql)}

    assert set(hr_rows) == set(ids)
    for order_type, pk in made.order_by_type.items():
        assert hr_rows[pk][1] == ORDER_TYPE_WORDS[order_type]
        assert hr_rows[pk][2] == OrderState.SIGNED.value
    assert hr_rows[made.order_emp_b][1] == "fired"
    assert hr_rows[made.order_emp_b][2] == OrderState.CANCELLED.value
    assert set(made.order_by_type.values()) <= limited_ids
    assert made.order_emp_b not in limited_ids


def test_orders_view_columns(ready: World) -> None:
    assert _columns("GOV_ORDERS") == ORDER_COLUMNS


def test_orders_view_hides_file_and_cancel_reason(made: Made) -> None:
    columns = _columns("GOV_ORDERS")

    assert "FILE" not in columns
    assert "CANCEL_REASON" not in columns
    rows = _rows(
        made.world.hr,
        "SELECT ORDER_ID, EMP_ID, ORDER_TYPE_NAME, STATE_NAME, ORDER_NUMBER, ORDER_DATE, SUMMARY FROM GOV_ORDERS",
    )
    assert all(PRIVATE_REASON not in str(cell) for row in rows for cell in row)
    assert all("private-test.docx" not in str(cell) for row in rows for cell in row)


def test_children_question_still_correct(made: Made) -> None:
    # The leave and order rows are in the database now; the children count must still match the ORM.
    visible = visible_employees(made.world.hr)
    expected = FamilyRow.objects.filter(employee__in=visible, relation__fm_type__in=("son", "daughter")).count()

    rows = _rows(made.world.hr, CHILDREN_COUNT)

    assert int(str(rows[0][0])) == expected
