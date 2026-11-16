"""Automatic order numbers (D-083): an order gets its number when it is made, never later.

`take_next_number` is the one call that makes a new number. It takes the ORDER_NUMBER named lock, the same lock the
manual number check (`orders._validate`) takes, so the automatic and the typed numbers of a year serialise against
each other. Then it returns the next free number read from the orders and MACS commands of that year
(`orders.suggest_number`).
The caller must run inside its own transaction and save the order in it: the lock is held until that transaction ends.
"""

import datetime

from django.db import connection

from employees import named_lock
from employees.named_lock import Lock, LockBusy
from employees.services.orders import NUMBER_REQUIRED, OrderError, suggest_number


def take_next_number(day: datetime.date) -> str:
    """The next free order number of `day`'s year, under the order-number lock. Raises RuntimeError outside a
    transaction (the lock would be released at once) and OrderError when no number can be suggested (the year is
    numbered with letters only, or the number would be too long) or the lock is busy."""
    if not connection.in_atomic_block:
        raise RuntimeError("take_next_number must run inside a transaction; outside one the lock is released at once.")
    try:
        named_lock.take(Lock.ORDER_NUMBER)
    except LockBusy as exc:
        raise OrderError({"number": exc.message}) from exc
    number = suggest_number(day)
    if not number:
        raise OrderError({"number": NUMBER_REQUIRED})
    return number
