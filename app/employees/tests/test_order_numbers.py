"""D-083: automatic order numbers. `take_next_number` numbers a new order under the order-number lock, and the one-time
migration numbers every pending order that exists."""

import importlib
from datetime import UTC, date, datetime

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from macs.models import Command

from employees import named_lock
from employees.models import ActivityEntry, HrOrder, OrderState, OrderType
from employees.named_lock import Lock, LockBusy
from employees.services import order_numbers
from employees.services.orders import OrderError

pytestmark = pytest.mark.django_db

# The data migration module starts with a digit, so it is loaded by name.
number_migration = importlib.import_module("employees.migrations.0039_number_pending_orders")


def _historical_apps():
    """The model state the data migration really runs on (not the live app models)."""
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    return loader.project_state([("employees", "0039_number_pending_orders")]).apps


def _registered(emp, number: str, day: date) -> HrOrder:
    return HrOrder.objects.create(
        employee=emp,
        is_hire=True,
        order_type=OrderType.HIRED,
        state=OrderState.REGISTERED,
        number=number,
        number_key=number.casefold(),
        date=day,
    )


def _pending(emp, day: date | None, created: datetime, number: str = "") -> HrOrder:
    order = HrOrder.objects.create(
        employee=emp, is_hire=True, order_type=OrderType.HIRED, state=OrderState.PENDING, date=day, number=number
    )
    HrOrder.objects.filter(pk=order.pk).update(created_at=created)  # auto_now_add would stamp the real time
    order.refresh_from_db()
    return order


def test_take_next_number_after_highest(hired) -> None:
    _registered(hired, "4", date(2026, 3, 1))
    _registered(hired, "7", date(2026, 4, 1))
    assert order_numbers.take_next_number(date(2026, 5, 1)) == "8"


def test_take_next_number_counts_command_rows(hired) -> None:
    Command.objects.create(employee_id=hired.pk, number="9", date=date(2026, 4, 1), order_type=1)
    assert order_numbers.take_next_number(date(2026, 5, 1)) == "10"


def test_take_next_number_takes_the_order_number_lock(hired, monkeypatch: pytest.MonkeyPatch) -> None:
    taken: list[Lock] = []
    monkeypatch.setattr(named_lock, "take", lambda lock: taken.append(lock))
    assert order_numbers.take_next_number(date(2026, 5, 1)) == "2"  # the hired fixture's order is "1"
    assert taken == [Lock.ORDER_NUMBER]


def test_take_next_number_busy_lock_is_an_order_error(hired, monkeypatch: pytest.MonkeyPatch) -> None:
    def busy(lock: Lock) -> None:
        raise LockBusy()

    monkeypatch.setattr(named_lock, "take", busy)
    with pytest.raises(OrderError) as info:
        order_numbers.take_next_number(date(2026, 5, 1))
    assert "number" in info.value.errors


@pytest.mark.django_db(transaction=True)
def test_take_next_number_outside_a_transaction_raises() -> None:
    with pytest.raises(RuntimeError):
        order_numbers.take_next_number(date(2026, 5, 1))


def test_take_next_number_refuses_a_year_numbered_with_letters_only(hired) -> None:
    # Only letter numbers exist in 2025, so no suggestion is made for that year.
    Command.objects.create(employee_id=hired.pk, number="Б/3", date=date(2025, 4, 1), order_type=1)
    with pytest.raises(OrderError):
        order_numbers.take_next_number(date(2025, 6, 1))


def test_number_pending_orders_by_year_in_creation_order(hired) -> None:
    _registered(hired, "3", date(2025, 6, 1))
    # `y` is created second (higher pk) but earlier in time, so creation time, not pk, decides the order.
    x = _pending(hired, date(2025, 5, 2), datetime(2025, 5, 2, 9, tzinfo=UTC))
    y = _pending(hired, date(2025, 5, 1), datetime(2025, 5, 1, 9, tzinfo=UTC))
    c = _pending(hired, None, datetime(2026, 7, 1, 12, tzinfo=UTC))  # no date: the creation day
    assert number_migration.number_pending_orders(_historical_apps()) == 3
    x.refresh_from_db()
    y.refresh_from_db()
    c.refresh_from_db()
    assert (y.number, x.number) == ("4", "5")
    assert c.date == date(2026, 7, 1)
    assert c.number == "2"  # 2026 already has the hire order "1" from the hired fixture


def test_number_pending_orders_keeps_an_existing_number(hired) -> None:
    _registered(hired, "3", date(2025, 6, 1))
    kept = _pending(hired, date(2025, 5, 1), datetime(2025, 5, 1, 9, tzinfo=UTC), number="5")
    after = _pending(hired, date(2025, 5, 2), datetime(2025, 5, 2, 9, tzinfo=UTC))
    number_migration.number_pending_orders(_historical_apps())
    kept.refresh_from_db()
    after.refresh_from_db()
    assert kept.number == "5" and kept.state == OrderState.REGISTERED
    assert after.number == "6"  # numbering continues above the kept number


def test_number_pending_orders_renumbers_a_typed_number_that_clashes(hired) -> None:
    _registered(hired, "3", date(2025, 6, 1))
    clash = _pending(hired, date(2025, 5, 1), datetime(2025, 5, 1, 9, tzinfo=UTC), number="3")
    number_migration.number_pending_orders(_historical_apps())
    clash.refresh_from_db()
    assert clash.number == "4" and clash.number_key == "4"  # 2025 already has "3": the next free number
    assert clash.state == OrderState.REGISTERED
    entry = ActivityEntry.objects.get(order=clash)
    assert "№ 4" in entry.message and "3" in entry.message  # the history says the typed number was replaced
    assert {"field": "Дугаар", "old": "3", "new": "4"} in entry.changes


def test_number_pending_orders_renumbers_a_second_pending_order_with_the_same_typed_number(hired) -> None:
    first = _pending(hired, date(2025, 5, 1), datetime(2025, 5, 1, 9, tzinfo=UTC), number="9")
    second = _pending(hired, date(2025, 5, 2), datetime(2025, 5, 2, 9, tzinfo=UTC), number="9")
    number_migration.number_pending_orders(_historical_apps())
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.number == "9"  # the first keeps its typed number
    assert second.number == "10"  # the second clashes with it and gets the next free number


def test_number_pending_orders_logs_history(hired) -> None:
    a = _pending(hired, date(2025, 5, 1), datetime(2025, 5, 1, 9, tzinfo=UTC))
    number_migration.number_pending_orders(_historical_apps())
    entries = ActivityEntry.objects.filter(order=a)
    assert entries.count() == 1
    entry = entries.get()
    assert entry.employee_id == hired.pk
    assert "№ 1" in entry.message
    assert "2025-05-01" in entry.change_text


def test_number_pending_sets_registered(hired) -> None:
    a = _pending(hired, date(2025, 5, 1), datetime(2025, 5, 1, 9, tzinfo=UTC))
    number_migration.number_pending_orders(_historical_apps())
    a.refresh_from_db()
    assert a.state == OrderState.REGISTERED
    assert a.number == "1" and a.number_key == "1"
    assert HrOrder.objects.filter(state=OrderState.PENDING).count() == 0
