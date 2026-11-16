"""The governed leave request view (Task 10): GOV_LEAVE_REQUESTS, on Firebird, through run_question.

Firebird only. Leave request rows are committed (autocommit on `default`), because the governed connection is another
connection and sees only committed rows. The rows are removed again after each test.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from leave.models import LeaveRequest, RequestStatus
from macs.models import Employee, LeaveTypeRow
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.tests.conftest import World
from hr_sql.tests.expected import OPEN_VIEWS
from hr_sql.tests.govhelpers import columns, id_list, refusal, rows

REQUEST_COLUMNS = [
    "REQUEST_ID",
    "EMP_ID",
    "LEAVE_TYPE_NAME",
    "START_DATE",
    "END_DATE",
    "WORKING_DAYS",
    "STATUS_NAME",
]
EXCLUDED_COLUMNS = {
    "NOTE",
    "REASON",
    "CURRENT_STEP",
    "STEP_COUNT",
    "STEP1_GROUP_ID",
    "STEP2_GROUP_ID",
    "STEP1_MANAGER",
    "STEP2_MANAGER",
    "ASSIGN_ID",
    "CREATED_BY_ID",
    "CREATED_AT",
    "UPDATED_AT",
}
PRIVATE_NOTE = "private request note"
PRIVATE_REJECT_REASON = "private reject reason"


@dataclass(frozen=True)
class Made:
    world: World
    type_name: str  # the leave type name shared by the requests
    waiting_a: int  # emp_a (branch A): waiting for approval
    approved_a: int  # emp_a: approved
    rejected_a: int  # emp_a: rejected, with a reject reason
    withdrawn_a: int  # emp_a: taken back by the employee
    waiting_b: int  # emp_b (branch B): waiting for approval


def _request(employee: Employee, leave_type: LeaveTypeRow, status: str, reason: str = "") -> LeaveRequest:
    return LeaveRequest.objects.create(
        employee=employee,
        leave_type=leave_type,
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 4),
        working_days=3,
        note=PRIVATE_NOTE,
        status=status,
        reason=reason,
        step1_manager=True,
        step_count=1,
    )


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Committed leave requests for emp_a (branch A) and emp_b (branch B). Removed after the test."""
    request_ids: list[int] = []
    with django_db_blocker.unblock():
        leave_type = LeaveTypeRow.objects.create(name=f"Тест хүсэлт {uuid.uuid4().hex[:6]}")
        try:
            waiting_a = _request(ready.emp_a, leave_type, RequestStatus.WAITING)
            approved_a = _request(ready.emp_a, leave_type, RequestStatus.APPROVED)
            rejected_a = _request(ready.emp_a, leave_type, RequestStatus.REJECTED, PRIVATE_REJECT_REASON)
            withdrawn_a = _request(ready.emp_a, leave_type, RequestStatus.WITHDRAWN)
            waiting_b = _request(ready.emp_b, leave_type, RequestStatus.WAITING)
            request_ids = [r.pk for r in (waiting_a, approved_a, rejected_a, withdrawn_a, waiting_b)]
            yield Made(
                world=ready,
                type_name=leave_type.name,
                waiting_a=waiting_a.pk,
                approved_a=approved_a.pk,
                rejected_a=rejected_a.pk,
                withdrawn_a=withdrawn_a.pk,
                waiting_b=waiting_b.pk,
            )
        finally:
            LeaveRequest.objects.filter(pk__in=request_ids).delete()
            LeaveTypeRow.objects.filter(pk=leave_type.pk).delete()


def test_leave_requests_scope(made: Made) -> None:
    world = made.world
    ids = [made.waiting_a, made.approved_a, made.rejected_a, made.withdrawn_a, made.waiting_b]
    branch_a_ids = [made.waiting_a, made.approved_a, made.rejected_a, made.withdrawn_a]
    sql = f"SELECT REQUEST_ID FROM GOV_LEAVE_REQUESTS WHERE REQUEST_ID IN ({id_list(ids)})"  # noqa: S608 (ids are ints)

    hr_ids = {int(str(row[0])) for row in rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in rows(world.limited, sql)}
    own_ids = {int(str(row[0])) for row in rows(world.own, sql)}

    assert hr_ids == set(ids)  # HR sees both branches
    assert limited_ids == set(branch_a_ids)  # the branch limit keeps branch B out
    assert own_ids == set(branch_a_ids)  # own record only


def test_leave_requests_columns(ready: World) -> None:
    listed = columns("GOV_LEAVE_REQUESTS")
    assert listed == REQUEST_COLUMNS
    assert not EXCLUDED_COLUMNS & set(listed)


def test_leave_requests_status_names(made: Made) -> None:
    ids = [made.waiting_a, made.approved_a, made.rejected_a, made.withdrawn_a]
    sql = (
        "SELECT REQUEST_ID, LEAVE_TYPE_NAME, STATUS_NAME FROM GOV_LEAVE_REQUESTS"  # noqa: S608 (fixed names)
        f" WHERE REQUEST_ID IN ({id_list(ids)})"  # noqa: S608 (ids are ints)
    )
    listing = rows(made.world.hr, sql)
    status = {int(str(request_id)): str(status_name) for request_id, _, status_name in listing}
    assert status == {
        made.waiting_a: "waiting",
        made.approved_a: "approved",
        made.rejected_a: "rejected",
        made.withdrawn_a: "withdrawn",
    }
    assert {str(type_name) for _, type_name, _ in listing} == {made.type_name}


def test_leave_requests_hide_private_text(made: Made) -> None:
    ids = [made.waiting_a, made.approved_a, made.rejected_a, made.withdrawn_a, made.waiting_b]
    every_column = ", ".join(REQUEST_COLUMNS)  # the governed checker refuses SELECT *, so name all seven
    listing = rows(
        made.world.hr,
        f"SELECT {every_column} FROM GOV_LEAVE_REQUESTS WHERE REQUEST_ID IN ({id_list(ids)})",  # noqa: S608 (ints)
    )
    assert len(listing) == len(ids)
    for row in listing:
        for cell in row:
            assert PRIVATE_NOTE not in str(cell)
            assert PRIVATE_REJECT_REASON not in str(cell)


def test_leave_requests_gate(made: Made) -> None:
    assert "GOV_LEAVE_REQUESTS" in OPEN_VIEWS
    sql = "SELECT REQUEST_ID FROM GOV_LEAVE_REQUESTS"
    assert rows(made.world.hr, sql)
    assert rows(made.world.own, sql)
    assert rows(made.world.accountant, sql)
    # a user with no record and no right, and an inactive user, are outside the catalogue
    assert "not a governed view" in refusal(made.world.nobody, sql)
    assert "not a governed view" in refusal(made.world.inactive, sql)
