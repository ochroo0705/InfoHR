"""A registered order that has no MACS command row (numbered by the data migration, which cannot write production) gets
its row when it is signed or edited. An order that already has one is updated, never written twice."""

from datetime import date

import pytest
from accounts.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from macs.models import Command, EmployeeHistory

from employees.models import Employee, Event, HrOrder, OrderState, OrderType
from employees.services import events, macs_writes, orders

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)


def _scan() -> SimpleUploadedFile:
    return SimpleUploadedFile("order.pdf", b"%PDF-1.4 test", content_type="application/pdf")


def _waiting_transfer(hired: Employee, actor: User, number: str) -> HrOrder:
    """A registered transfer order whose change waits for the signed scan."""
    events.record(
        hired,
        type="transfer",
        effective=DAY,
        changes={"department": macs_writes.save_department("Инженер")},
        salary=None,
        reason="",
        note="",
        by=actor,
        order_number=number,
        order_date=DAY,
    )
    return HrOrder.objects.get(employee=hired, event__isnull=False)


def _strip_command(order: HrOrder) -> None:
    """Make the order look like a legacy one: no command row, no history link to it, no pointer to it."""
    old = order.command_id
    HrOrder.objects.filter(pk=order.pk).update(command_id=None)
    if old:
        EmployeeHistory.objects.filter(command_id_value=old).update(command_id_value=None)
        Employee.objects.filter(command_id_value=old).update(command_id_value=None)
        Command.objects.filter(pk=old).delete()
    order.refresh_from_db()


def test_signing_a_legacy_change_order_writes_its_command_row(actor: User, hired: Employee) -> None:
    order = _waiting_transfer(hired, actor, "901")
    _strip_command(order)
    assert not Command.objects.filter(number="901").exists()

    orders.attach_signed_file(order, _scan(), by=actor)

    order.refresh_from_db()
    command = Command.objects.get(number="901")
    assert command.pk == order.command_id
    assert command.date == DAY
    assert command.order_type == OrderType.DEPARTMENT
    event = Event.objects.get(pk=order.event_id)
    assert event.applied_at is not None
    history_ids = [row.history_id for row in event.prod_rows.all() if row.history_id]
    assert history_ids and all(
        EmployeeHistory.objects.get(pk=h).command_id_value == command.pk for h in history_ids
    )
    hired.refresh_from_db()
    assert hired.command_id_value == command.pk


def test_signing_a_legacy_hire_order_writes_its_command_row(actor: User, hired: Employee) -> None:
    hire = HrOrder.objects.get(employee=hired, is_hire=True)
    hire = orders.register(hire, number="902", date=DAY, summary="Ажилд авав", issued_by="", by=actor)
    _strip_command(hire)

    orders.attach_signed_file(hire, _scan(), by=actor)

    command = Command.objects.get(number="902")
    hire.refresh_from_db()
    assert hire.command_id == command.pk
    assert command.order_type == OrderType.HIRED
    assert EmployeeHistory.objects.get(pk=hire.history_id).command_id_value == command.pk
    hired.refresh_from_db()
    assert hired.command_id_value == command.pk


def test_editing_a_legacy_order_writes_its_command_row(actor: User, hired: Employee) -> None:
    hire = HrOrder.objects.get(employee=hired, is_hire=True)
    hire = orders.register(hire, number="903", date=DAY, summary="", issued_by="", by=actor)
    _strip_command(hire)

    orders.register(hire, number="904", date=DAY, summary="Засвар", issued_by="", by=actor)

    command = Command.objects.get(pk=HrOrder.objects.get(pk=hire.pk).command_id)
    assert command.number == "904"
    assert command.summary == "Засвар"
    assert not Command.objects.filter(number="903").exists()


def test_order_with_a_command_row_is_updated_not_written_twice(actor: User, hired: Employee) -> None:
    order = _waiting_transfer(hired, actor, "905")
    before = Command.objects.filter(number="905").count()
    command_id = order.command_id
    assert before == 1 and command_id is not None

    orders.attach_signed_file(order, _scan(), by=actor)

    order.refresh_from_db()
    assert order.state == OrderState.SIGNED
    assert order.command_id == command_id
    assert Command.objects.filter(number="905").count() == 1
