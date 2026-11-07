"""Named locks for writes that must not run twice at once, on PostgreSQL and on Firebird.

`take` is the one call the write paths use. Each `Lock` has two keys:
- PostgreSQL: the advisory lock key the code used before this module existed (the same numbers, unchanged).
  ORDER_NUMBER and STAFF_IMPORT share key 7302 there, as they always did.
- Firebird: a row of the HistoryLock table (employee_id -1, -2, -3). Firebird has no advisory locks; a lock is an
  UPDATE of that row, which waits or is refused while another writer's transaction holds it
  (history_range.lock_employee).

The lock is held until the enclosing transaction ends. Call `take` inside a transaction, as the first statement
that needs the lock; outside one it would be released at once, so `take` refuses to run there.
"""

from __future__ import annotations

import enum

from django.db import OperationalError, connection
from macs.dialect import is_firebird

from employees import history_range


class Lock(enum.Enum):
    """Each value is (PostgreSQL advisory key, Firebird HistoryLock employee_id). The Firebird values are distinct
    so that the members stay distinct even where the PostgreSQL keys are equal."""

    HIRE = (7301, -1)
    ORDER_NUMBER = (7302, -2)
    STAFF_IMPORT = (7302, -3)


class LockBusy(Exception):
    """Another writer holds the lock, or the lock could not be taken in time. The message is shown to the user."""

    def __init__(self) -> None:
        super().__init__(history_range.LOCK_BUSY_MESSAGE)
        self.message: str = history_range.LOCK_BUSY_MESSAGE


def take(lock: Lock) -> None:
    """Take the named lock for the rest of the current transaction. Raises LockBusy on Firebird when another
    writer holds it; raises RuntimeError when no transaction is open."""
    if not connection.in_atomic_block:
        raise RuntimeError("named_lock.take must run inside a transaction; outside one the lock is released at once.")
    postgres_key, firebird_row = lock.value
    if not is_firebird():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [postgres_key])
        return
    # Imported here, not at module level: the callers of this module are in employees.services, which would cycle.
    from employees.services.history import HistoryError

    try:
        history_range.lock_employee(firebird_row)
    except (HistoryError, OperationalError) as exc:
        # RecordBusy is the expected case; by design any other database error here is also reported as busy.
        raise LockBusy() from exc
