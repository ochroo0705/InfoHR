"""D-083: an action that needs an HR order gets its order number when it is created. No pending order is created."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User

from employees.forms import OrderFieldsForm
from employees.models import ActivityEntry, Employee, HrOrder, OrderState, OrderType, Position
from employees.services import events, history, orders
from employees.services.events import EventError
from employees.services.orders import OrderError

from .conftest import hire_values

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)


@pytest.fixture
def lead(db: None) -> Position:
    return Position.objects.create(name="Ахлах нягтлан")


def test_create_for_change_without_number_raises(hired: Employee, actor: User) -> None:
    before = HrOrder.objects.count()
    with pytest.raises(OrderError) as exc:
        orders.create_for_change(
            employee=hired,
            event=None,
            is_hire=False,
            order_type=1,
            number="",
            date=DAY,
            summary="",
            issued_by="",
            by=actor,
        )
    assert exc.value.errors == {"number": "Тушаалын дугаар заавал"}
    assert HrOrder.objects.count() == before  # no pending order row


def test_hire_form_requires_order_number() -> None:
    form = OrderFieldsForm({"date": "2026-01-05", "summary": "", "issued_by": ""}, required=True)
    assert not form.is_valid()
    assert form.errors["number"] == ["Тушаалын дугаар заавал"]


def test_hire_form_date_is_optional() -> None:
    assert OrderFieldsForm({"number": "Э/11", "summary": "", "issued_by": ""}, required=True).is_valid()


def test_create_for_change_never_stores_pending(hired: Employee, actor: User) -> None:
    order = orders.create_for_change(
        employee=hired,
        event=None,
        is_hire=True,  # a hire order has no event; the hired fixture's own hire order is left as it is
        order_type=OrderType.HIRED.value,
        number="Э/12",
        date=DAY,
        summary="",
        issued_by="",
        by=actor,
    )
    stored = HrOrder.objects.get(pk=order.pk)
    assert stored.state == OrderState.REGISTERED
    assert ActivityEntry.objects.filter(order=stored, message__contains="бүртгэсэн").exists()  # logged as registered


def test_change_form_requires_order_number_when_type_needs_order(hired: Employee, actor: User, lead: Position) -> None:
    # The change form cannot know its order type before saving, so the service refuses a blank number when the
    # change needs an order (a promotion to a new position needs a POSITION order, on by default).
    with pytest.raises(EventError) as exc:
        events.record(
            hired,
            type="promotion",
            effective=DAY,
            changes={"position": lead},
            salary=None,
            reason="",
            note="",
            by=actor,
            order_number="",
            order_date=DAY,
        )
    assert "order_number" in exc.value.errors
    assert exc.value.errors["order_number"] == "Тушаалын дугаар заавал"


def test_hire_without_number_is_refused(actor: User, job_values: dict[str, Any]) -> None:
    employees_before = Employee.objects.count()
    with pytest.raises(OrderError):
        history.hire(
            hire_values("УБ55667788"),
            {},
            start=date(2026, 1, 5),
            job=job_values,
            salary=Decimal("1"),
            by=actor,
            order_number="",
            order_date=date(2026, 1, 5),
        )
    assert Employee.objects.count() == employees_before  # the refused hire leaves no employee row


def test_change_order_date_defaults_to_effective_date(hired: Employee, actor: User, lead: Position) -> None:
    event = events.record(
        hired,
        type="promotion",
        effective=DAY,
        changes={"position": lead},
        salary=None,
        reason="",
        note="",
        by=actor,
        order_number="Т/901",
        order_date=None,
    )
    assert event.order.date == DAY and event.order.state == OrderState.REGISTERED


def test_hire_order_date_defaults_to_hire_date(actor: User, job_values: dict[str, Any]) -> None:
    employee = history.hire(
        hire_values("УБ55667799"),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("1"),
        by=actor,
        order_number="Э/13",
        order_date=None,
    )
    assert HrOrder.objects.get(employee=employee, is_hire=True).date == date(2026, 1, 5)
