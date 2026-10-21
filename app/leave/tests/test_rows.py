import logging
from datetime import date

import pytest
from accounts.models import User
from django.db import connection
from macs.models import Employee, Entitlement, LeaveAssign, LeaveTypeRow

from leave.models import GrantKind, LeaveGrantExt
from leave.services import rows, writes
from leave.services.rows import State

pytestmark = pytest.mark.django_db

# Mon 2026-02-16 .. Fri 2026-02-20: five working days, no holiday.
MON = date(2026, 2, 16)
FRI = date(2026, 2, 20)


def _old_row(
    employee: Employee, leave_type: LeaveTypeRow, *, status: int | None = None, adays: int | None = None
) -> LeaveAssign:
    """A row the old program wrote: no Info HR ext row, status and adays may be NULL."""
    return LeaveAssign.objects.create(
        employee=employee,
        leave_type=leave_type,
        date1=MON,
        date2=FRI,
        comment="хуучин",
        status=status,
        adays=adays,
    )


def _delete_assign(pk: int) -> None:
    with connection.cursor() as cur:
        cur.execute("DELETE FROM leave_assign WHERE assign_id = %s", [pk])


def test_old_row_null_status_and_days(employee: Employee, annual: LeaveTypeRow) -> None:
    _old_row(employee, annual)

    found = rows.leaves(employee_ids=[employee.pk])

    assert len(found) == 1
    row = found[0]
    assert row.state is State.RECORDED
    assert row.counts is True
    assert row.days == 5
    assert row.from_old_system is True
    assert LeaveAssign.objects.get(pk=row.id).adays is None


def test_rejected_not_counted(employee: Employee, annual: LeaveTypeRow) -> None:
    _old_row(employee, annual, status=LeaveAssign.REJECTED, adays=5)

    row = rows.leaves(employee_ids=[employee.pk])[0]

    assert row.state is State.REJECTED
    assert row.counts is False


def test_mistake_state(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = writes.record_assign(employee, annual, MON, FRI, 5, "", actor)
    writes.cancel_assign(a, writes.snapshot(a), "алдсан", mistake=True, by=actor)

    row = rows.leave(a.pk)

    assert row.state is State.MISTAKE
    assert row.cancel_reason == "алдсан"
    assert row.from_old_system is False
    assert row.counts is False


def test_cancelled_state(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = writes.record_assign(employee, annual, MON, FRI, 5, "", actor)
    writes.cancel_assign(a, writes.snapshot(a), "өөрчлөгдсөн", mistake=False, by=actor)

    assert rows.leave(a.pk).state is State.CANCELLED


def test_snapshot_built_from_production_row(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = writes.record_assign(employee, annual, MON, FRI, 5, "Гэр бүл", actor)

    row = rows.leave(a.pk)

    assert row.snapshot == writes.snapshot(LeaveAssign.objects.get(pk=a.pk))


def test_orphan_ext_ignored(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = writes.record_assign(employee, annual, MON, FRI, 5, "", actor)
    _delete_assign(a.pk)

    assert rows.leaves(employee_ids=[employee.pk]) == []


def test_missing_type_row_skipped(employee: Employee, annual: LeaveTypeRow, caplog: pytest.LogCaptureFixture) -> None:
    a = _old_row(employee, annual)
    with connection.cursor() as cur:
        cur.execute("DELETE FROM leave_type WHERE leavetype_id = %s", [annual.pk])

    with caplog.at_level(logging.WARNING, logger="leave.services.rows"):
        found = rows.leaves(employee_ids=[employee.pk])

    assert found == []
    assert any(str(a.pk) in r.getMessage() for r in caplog.records)


def test_missing_employee_row_skipped(
    employee: Employee, annual: LeaveTypeRow, caplog: pytest.LogCaptureFixture
) -> None:
    LeaveAssign.objects.create(employee_id=999_999, leave_type=annual, date1=MON, date2=FRI, status=None)

    with caplog.at_level(logging.WARNING, logger="leave.services.rows"):
        assert rows.leaves() == []
    assert caplog.records


def test_filters_overlap_and_order(employee: Employee, annual: LeaveTypeRow) -> None:
    early = LeaveAssign.objects.create(
        employee=employee, leave_type=annual, date1=date(2026, 1, 5), date2=date(2026, 1, 6), status=None
    )
    late = _old_row(employee, annual)

    assert [r.id for r in rows.leaves(employee_ids=[employee.pk])] == [late.pk, early.pk]
    overlap = rows.leaves(start=date(2026, 1, 6), end=date(2026, 2, 16))
    assert [r.id for r in overlap] == [late.pk, early.pk]
    assert [r.id for r in rows.leaves(start=date(2026, 1, 7), end=date(2026, 2, 15))] == []


def test_old_grant_is_manual(employee: Employee, annual: LeaveTypeRow) -> None:
    Entitlement.objects.create(employee=employee, leave_type=annual, date1=MON, date2=FRI, ent_days=10, comment="")

    found = rows.grants(employee.pk)

    assert len(found) == 1
    assert found[0].kind is GrantKind.MANUAL
    assert found[0].from_old_system is True
    assert found[0].days == 10


def test_written_grant_keeps_kind(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    grant = writes.add_grant(employee, annual, MON, FRI, 3, "", GrantKind.ADJUSTMENT, actor, breakdown="засвар")

    found = rows.grants(employee.pk)

    assert found[0].id == grant.pk
    assert found[0].kind is GrantKind.ADJUSTMENT
    assert found[0].breakdown == "засвар"
    assert found[0].from_old_system is False
    assert LeaveGrantExt.objects.filter(grant=grant).exists()


def test_unknown_status_warns(employee: Employee, annual: LeaveTypeRow, caplog: pytest.LogCaptureFixture) -> None:
    odd = _old_row(employee, annual, status=9)

    with caplog.at_level(logging.WARNING, logger="leave.services.rows"):
        found = rows.leaves(employee_ids=[employee.pk])

    assert found[0].state is State.RECORDED
    assert found[0].counts is True
    assert any(str(odd.pk) in record.getMessage() for record in caplog.records)


def test_bad_grant_kind_falls_back(
    employee: Employee, annual: LeaveTypeRow, actor: User, caplog: pytest.LogCaptureFixture
) -> None:
    grant = writes.add_grant(employee, annual, date(2026, 1, 1), date(2026, 12, 31), 15, "2026", GrantKind.AUTO, actor)
    LeaveGrantExt.objects.filter(pk=grant.pk).update(kind="bogus")

    with caplog.at_level(logging.WARNING, logger="leave.services.rows"):
        found = rows.grants(employee.pk, annual_only=False)

    assert found[0].kind is GrantKind.MANUAL
    assert any(str(grant.pk) in record.getMessage() for record in caplog.records)
