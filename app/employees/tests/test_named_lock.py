"""PostgreSQL side of named_lock.take: the advisory lock runs with the same keys as before the module existed."""

from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection, transaction

from employees.named_lock import Lock, take
from employees.services import history, orders
from employees.staff_import import run


def _captured(action: Callable[[], None]) -> list[tuple[str, Any]]:
    """Run action and return every (sql, params) the connection executed."""
    seen: list[tuple[str, Any]] = []

    def record(execute: Callable[..., Any], sql: str, params: Any, many: bool, context: Any) -> Any:
        seen.append((sql, params))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(record):
        action()
    return seen


@pytest.mark.pg_only(
    "checks the PostgreSQL advisory-lock SQL; the Firebird lock is in infohr_firebird/tests/test_named_lock_firebird.py"
)
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("lock", "key"),
    [(Lock.HIRE, 7301), (Lock.ORDER_NUMBER, 7302), (Lock.STAFF_IMPORT, 7302)],
)
def test_take_runs_the_advisory_lock_with_the_old_key(lock: Lock, key: int) -> None:
    with transaction.atomic():
        seen = _captured(lambda: take(lock))
    assert len(seen) == 1
    sql, params = seen[0]
    assert sql == "SELECT pg_advisory_xact_lock(%s)"
    assert list(params) == [key]


@pytest.mark.django_db(transaction=True)
def test_take_outside_a_transaction_raises() -> None:
    with pytest.raises(RuntimeError):
        take(Lock.HIRE)


def test_pg_keys_match_the_old_constants() -> None:
    assert Lock.HIRE.value[0] == history.HIRE_LOCK_KEY == 7301
    assert Lock.ORDER_NUMBER.value[0] == orders.ORDER_NUMBER_LOCK_KEY == 7302
    assert Lock.STAFF_IMPORT.value[0] == run.RUN_LOCK_KEY == 7302


def test_the_three_locks_are_distinct_members() -> None:
    assert len(Lock) == 3
    assert len({Lock.ORDER_NUMBER, Lock.STAFF_IMPORT}) == 2
    assert Lock.ORDER_NUMBER.value == (7302, -2)
    assert Lock.STAFF_IMPORT.value == (7302, -3)
    assert Lock.HIRE.value == (7301, -1)
