"""The governed events view (Task 8): GOV_EVENTS, on Firebird, through run_question.

Firebird only. Event rows are committed (autocommit on `default`), because the governed connection is another
connection and sees only committed rows. The rows are removed again after each test.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from django.utils import timezone
from employees.models import Event, EventType
from macs.models import FiredReason
from pytest_django.plugin import DjangoDbBlocker

from hr_sql.tests.conftest import World
from hr_sql.tests.expected import EMPLOYEE_RIGHT_VIEWS
from hr_sql.tests.govhelpers import columns, id_list, refusal, rows

EVENT_COLUMNS = [
    "EVENT_ID",
    "EMP_ID",
    "EVENT_TYPE",
    "EFFECTIVE_DATE",
    "FIRED_REASON_NAME",
    "EXPECTED_RETURN",
    "STATUS_NAME",
]
PRIVATE_NOTE = "private event note"
PRIVATE_CANCEL = "private cancel text"
PRIVATE_REASON = "private event reason"


@dataclass(frozen=True)
class Made:
    world: World
    applied_a: int  # emp_a (branch A): a promotion, signed and in force
    awaiting_a: int  # emp_a: a transfer, waiting for the order to be signed
    cancelled_a: int  # emp_a: a contract change, cancelled
    termination_b: int  # emp_b (branch B): a termination, signed, with a leaving reason
    fired_reason_name: str  # the name of the leaving reason of termination_b


@pytest.fixture
def ready(governed_objects: None, world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def made(ready: World, django_db_blocker: DjangoDbBlocker) -> Iterator[Made]:
    """Committed events for emp_a (branch A) and emp_b (branch B). Removed after the test."""
    event_ids: list[int] = []
    reason_ids: list[int] = []
    with django_db_blocker.unblock():
        reason_name = f"Тест шалтгаан {uuid.uuid4().hex[:6]}"
        reason = FiredReason.objects.create(name=reason_name)
        reason_ids.append(reason.pk)
        try:
            applied = Event.objects.create(
                employee=ready.emp_a,
                type=EventType.PROMOTION,
                effective=date(2020, 1, 1),
                reason=PRIVATE_REASON,
                note=PRIVATE_NOTE,
                applied_at=timezone.now(),
            )
            awaiting = Event.objects.create(
                employee=ready.emp_a,
                type=EventType.TRANSFER,
                effective=date(2031, 4, 1),
                reason="",
                note=PRIVATE_NOTE,
            )
            cancelled = Event.objects.create(
                employee=ready.emp_a,
                type=EventType.CONTRACT,
                effective=date(2025, 6, 1),
                reason="",
                note=PRIVATE_NOTE,
                cancelled_at=timezone.now(),
                cancel_reason=PRIVATE_CANCEL,
            )
            termination = Event.objects.create(
                employee=ready.emp_b,
                type=EventType.TERMINATION,
                effective=date(2019, 12, 31),
                reason="",
                note=PRIVATE_NOTE,
                fired_reason=reason,
                applied_at=timezone.now(),
            )
            event_ids = [applied.pk, awaiting.pk, cancelled.pk, termination.pk]
            yield Made(
                world=ready,
                applied_a=applied.pk,
                awaiting_a=awaiting.pk,
                cancelled_a=cancelled.pk,
                termination_b=termination.pk,
                fired_reason_name=reason_name,
            )
        finally:
            Event.objects.filter(pk__in=event_ids).delete()
            FiredReason.objects.filter(pk__in=reason_ids).delete()


def test_events_scope(made: Made) -> None:
    world = made.world
    ids = [made.applied_a, made.awaiting_a, made.cancelled_a, made.termination_b]
    branch_a_ids = [made.applied_a, made.awaiting_a, made.cancelled_a]
    sql = f"SELECT EVENT_ID FROM GOV_EVENTS WHERE EVENT_ID IN ({id_list(ids)})"  # noqa: S608 (ids are ints)

    hr_ids = {int(str(row[0])) for row in rows(world.hr, sql)}
    limited_ids = {int(str(row[0])) for row in rows(world.limited, sql)}

    assert hr_ids == set(ids)  # HR sees both branches
    assert limited_ids == set(branch_a_ids)  # the branch limit keeps branch B out
    assert "not a governed view" in refusal(world.own, sql)  # own record only: no events view at all

    name_sql = f"SELECT EVENT_ID, FIRED_REASON_NAME FROM GOV_EVENTS WHERE EVENT_ID = {made.termination_b}"  # noqa: S608
    assert [(int(str(e)), n) for e, n in rows(world.hr, name_sql)] == [(made.termination_b, made.fired_reason_name)]


def test_events_columns(ready: World) -> None:
    assert columns("GOV_EVENTS") == EVENT_COLUMNS


def test_events_status_names(made: Made) -> None:
    ids = [made.applied_a, made.awaiting_a, made.cancelled_a, made.termination_b]
    sql = f"SELECT EVENT_ID, STATUS_NAME FROM GOV_EVENTS WHERE EVENT_ID IN ({id_list(ids)})"  # noqa: S608 (ids are ints)
    status = {int(str(event_id)): str(name) for event_id, name in rows(made.world.hr, sql)}
    assert status == {
        made.cancelled_a: "cancelled",
        made.awaiting_a: "awaiting_signature",
        made.applied_a: "applied",
        made.termination_b: "applied",
    }


def test_events_hide_private_text(made: Made) -> None:
    ids = [made.applied_a, made.awaiting_a, made.cancelled_a, made.termination_b]
    every_column = ", ".join(EVENT_COLUMNS)  # the governed checker refuses SELECT *, so name all seven
    listing = rows(made.world.hr, f"SELECT {every_column} FROM GOV_EVENTS WHERE EVENT_ID IN ({id_list(ids)})")  # noqa: S608
    assert len(listing) == len(ids)
    for row in listing:
        for cell in row:
            assert PRIVATE_NOTE not in str(cell)
            assert PRIVATE_CANCEL not in str(cell)
            assert PRIVATE_REASON not in str(cell)  # Event.reason is planted above; the view has no such column


def test_events_hide_salary_changes(ready: World, django_db_blocker: DjangoDbBlocker) -> None:
    """A pay change is not in GOV_EVENTS (the salary right gates it); the other change of the same person is."""
    every_column = ", ".join(EVENT_COLUMNS)  # the governed checker refuses SELECT *, so name all seven
    with django_db_blocker.unblock():
        pay = Event.objects.create(
            employee=ready.emp_a,
            type=EventType.SALARY_CHANGE,
            effective=date(2021, 1, 1),
            reason="",
            note=PRIVATE_NOTE,
            applied_at=timezone.now(),
        )
        move = Event.objects.create(
            employee=ready.emp_a,
            type=EventType.TRANSFER,
            effective=date(2021, 2, 1),
            reason="",
            note=PRIVATE_NOTE,
            applied_at=timezone.now(),
        )
        try:
            listing = rows(
                ready.hr,
                f"SELECT {every_column} FROM GOV_EVENTS WHERE EVENT_ID IN ({id_list([pay.pk, move.pk])})",  # noqa: S608
            )
            assert [int(str(row[0])) for row in listing] == [move.pk]
            assert str(listing[0][2]) == EventType.TRANSFER.value
        finally:
            Event.objects.filter(pk__in=[pay.pk, move.pk]).delete()


def test_events_gate(made: Made) -> None:
    assert "GOV_EVENTS" in EMPLOYEE_RIGHT_VIEWS
    sql = "SELECT EVENT_ID FROM GOV_EVENTS"
    assert rows(made.world.hr, sql)
    assert rows(made.world.limited, sql)
    assert rows(made.world.accountant, sql)
    # the own-record user, a user with no record and no right, and an inactive user are outside the catalogue
    assert "not a governed view" in refusal(made.world.own, sql)
    assert "not a governed view" in refusal(made.world.nobody, sql)
    assert "not a governed view" in refusal(made.world.inactive, sql)
