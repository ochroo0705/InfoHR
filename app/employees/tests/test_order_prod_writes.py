from datetime import date
from typing import Any

import pytest
from accounts.models import User
from macs.models import Branch, Command, EmployeeHistory

from employees.models import Employee, Event, HrOrder, OrderState, OrderType, Position
from employees.services import macs_writes
from employees.tests.test_events import rec

HIRE_DAY = date(2026, 1, 5)
D1 = date(2026, 3, 1)
D2 = date(2026, 4, 1)


@pytest.fixture
def lead(db: None) -> Position:
    return Position.objects.create(name="Ахлах нягтлан")


@pytest.fixture
def chief(db: None) -> Position:
    return Position.objects.create(name="Захирал")


def order_for(
    employee: Employee,
    event: Event | None = None,
    *,
    number: str = "A-1",
    state: str = OrderState.REGISTERED,
    **kw: Any,
) -> HrOrder:
    values: dict[str, Any] = {
        "employee": employee,
        "event": event,
        "is_hire": event is None,
        "order_type": OrderType.HIRED if event is None else OrderType.POSITION,
        "state": state,
        "number": number,
        "number_key": number,
        "date": D1,
        "summary": "Тушаал",
        "issued_by": "Захирал",
    }
    # Events and hires now create their own pending order; these tests build the order they need instead.
    existing = (
        HrOrder.objects.filter(employee=employee, event=event) if event else employee.hr_orders.filter(is_hire=True)
    )
    if event is None and "history_id" not in kw:
        values["history_id"] = existing.values_list("history_id", flat=True).first()
    existing.delete()
    values.update(kw)
    return HrOrder.objects.create(**values)


def history_of(event: Event) -> EmployeeHistory:
    return EmployeeHistory.objects.get(pk=event.prod_rows.get().history_id or 0)


def reload(employee: Employee) -> Employee:
    return Employee.objects.get(pk=employee.pk)


def test_command_row_fields(hired: Employee, actor: User, lead: Position) -> None:
    ev = rec(hired, actor, "promotion", D1, changes={"position": lead})
    order = order_for(ev.employee, ev, number="123", summary="Албан тушаал", issued_by="Б.Бат", file="2026/x.pdf")
    macs_writes.write_order(order)
    order.refresh_from_db()
    cmd = Command.objects.get(pk=order.command_id or 0)
    assert (cmd.number, cmd.date, cmd.order_type) == ("123", D1, OrderType.POSITION)
    assert cmd.path is None  # spec §6: Info HR files are never exposed to the old MACS share
    assert (cmd.summary, cmd.issued_by, cmd.employee_id) == ("Албан тушаал", "Б.Бат", hired.pk)
    # a second write updates the same row
    order.number = "124"
    macs_writes.write_order(order)
    assert Command.objects.filter(employee=hired).count() == 1
    assert Command.objects.get(pk=order.command_id or 0).number == "124"


def test_history_row_gets_order_columns(hired: Employee, actor: User, lead: Position) -> None:
    ev = rec(hired, actor, "promotion", D1, changes={"position": lead})
    order = order_for(hired, ev)
    macs_writes.write_order(order)
    snap = history_of(ev)
    assert (snap.command_id_value, snap.move_type) == (order.command_id, OrderType.POSITION)


def test_hire_order_uses_history_id(hired: Employee) -> None:
    hid = macs_writes.snapshot_history(hired, HIRE_DAY)
    order = order_for(hired, history_id=hid)
    macs_writes.write_order(order)
    snap = EmployeeHistory.objects.get(pk=hid)
    assert (snap.command_id_value, snap.move_type) == (order.command_id, OrderType.HIRED)
    assert reload(hired).command_id_value == order.command_id


def test_pointer_follows_latest_order(hired: Employee, actor: User, lead: Position, chief: Position) -> None:
    hire = order_for(hired, number="1", history_id=macs_writes.snapshot_history(hired, HIRE_DAY))
    macs_writes.write_order(hire)
    ev = rec(hired, actor, "promotion", D1, changes={"position": lead})
    promo = order_for(hired, ev, number="2")
    macs_writes.write_order(promo)
    emp = reload(hired)
    assert (emp.command_id_value, emp.move_type) == (promo.command_id, OrderType.POSITION)
    assert hire.command_id != promo.command_id


def test_pointer_reverts_after_cancel(hired: Employee, actor: User, lead: Position) -> None:
    hire = order_for(hired, number="1", history_id=macs_writes.snapshot_history(hired, HIRE_DAY))
    macs_writes.write_order(hire)
    ev = rec(hired, actor, "promotion", D1, changes={"position": lead})
    promo = order_for(hired, ev, number="2")
    macs_writes.write_order(promo)
    promo.state = OrderState.CANCELLED
    promo.save()
    macs_writes.point_employee_to_latest_order(hired)
    emp = reload(hired)
    assert (emp.command_id_value, emp.move_type) == (hire.command_id, OrderType.HIRED)


def test_pointer_null_when_none_left(hired: Employee) -> None:
    hire = order_for(hired, number="1", history_id=macs_writes.snapshot_history(hired, HIRE_DAY))
    macs_writes.write_order(hire)
    assert reload(hired).command_id_value is not None
    hire.state = OrderState.CANCELLED
    hire.save()
    macs_writes.point_employee_to_latest_order(hired)
    emp = reload(hired)
    assert (emp.command_id_value, emp.move_type) == (None, None)


def test_changes_without_order_are_ignored(hired: Employee, actor: User, lead: Position) -> None:
    hire = order_for(hired, number="1", history_id=macs_writes.snapshot_history(hired, HIRE_DAY))
    macs_writes.write_order(hire)
    rec(hired, actor, "promotion", D1, changes={"position": lead})  # no order
    macs_writes.point_employee_to_latest_order(hired)
    assert reload(hired).command_id_value == hire.command_id


def test_number_later_updates_old_snapshot_not_pointer_if_newer_order_exists(
    hired: Employee, actor: User, lead: Position, chief: Position
) -> None:
    old_ev = rec(hired, actor, "promotion", D1, changes={"position": lead})
    new_ev = rec(hired, actor, "promotion", D2, changes={"position": chief})
    newer = order_for(hired, new_ev, number="9")
    macs_writes.write_order(newer)
    older = order_for(hired, old_ev, number="5")
    macs_writes.write_order(older)  # number entered later for the older change
    assert history_of(old_ev).command_id_value == older.command_id
    assert reload(hired).command_id_value == newer.command_id


def test_command_never_deleted_on_cancel(hired: Employee, actor: User, lead: Position) -> None:
    ev = rec(hired, actor, "promotion", D1, changes={"position": lead})
    order = order_for(hired, ev)
    macs_writes.write_order(order)
    order.state = OrderState.CANCELLED
    order.save()
    macs_writes.point_employee_to_latest_order(hired)
    assert Command.objects.filter(pk=order.command_id or 0).exists()


def test_snapshot_has_branch(hired: Employee) -> None:
    branch = Branch.objects.create(name="Төв")
    hired.branch = branch
    hired.save(update_fields=["branch"])
    sid = macs_writes.snapshot_history(hired, HIRE_DAY)
    assert EmployeeHistory.objects.get(pk=sid).branch_id_value == branch.pk
