import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import firebird.driver as fbd  # type: ignore[import-untyped]
import pytest
from django.db import OperationalError, connections, transaction

from infohr_firebird.errors import RecordBusy

# Employee 1767 exists in the template clone; tests only ever touch the copy.
UPDATE_ROW = "update employee set post = post where employee_id = 1767"
READ_ROW = "select post from employee where employee_id = 1767"
BUSY_MESSAGE = "Another user is editing this record. Try again in a moment."
# Above the longest expected wait (3 s default timeout), so a correct run never reaches it.
# If the lock timeout is missing, the watchdog releases the row and the test fails in bounded time.
WATCHDOG_SECONDS = 8.0

_release_lock = threading.Lock()


def _release_row(tra: fbd.TransactionManager) -> None:
    """Roll back the other attachment's transaction once, so the row lock is released."""
    with _release_lock:
        if tra.is_active():
            tra.rollback()


@contextmanager
def _watchdog(tra: fbd.TransactionManager) -> Iterator[None]:
    """Release the row after WATCHDOG_SECONDS, so a blocked writer cannot hang the test run."""
    timer = threading.Timer(WATCHDOG_SECONDS, _release_row, args=(tra,))
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()
        timer.join()


def _set_lock_timeout(alias: str, seconds: int) -> None:
    """Reconnect the wrapper with the given lock_timeout option.

    The wrapper reads OPTIONS at connect time, so the connection is recycled.
    """
    wrapper = connections[alias]
    wrapper.ensure_connection()
    wrapper.settings_dict["OPTIONS"]["lock_timeout"] = seconds
    wrapper.close()
    wrapper.ensure_connection()


@pytest.fixture
def busy_row(fb_clone: str, fb_alias: str) -> Iterator[fbd.TransactionManager]:
    """A second attachment that updates employee 1767 and keeps its transaction open.

    The wrapper must connect first: it sets the Firebird client library and dialect
    process-wide, and the raw driver connection needs those settings.
    """
    connections[fb_alias].ensure_connection()
    kwargs: dict[str, Any] = {"user": "SYSDBA", "charset": "UTF8"}
    password = os.environ.get("FIREBIRD_PASSWORD", "")
    if password:
        kwargs["password"] = password
    other = fbd.connect(fb_clone, **kwargs)
    tra = other.transaction_manager()
    try:
        tra.cursor().execute(UPDATE_ROW)
        yield tra
    finally:
        _release_row(tra)
        other.close()


def test_second_writer_gets_record_busy_fast(fb_alias: str, busy_row: fbd.TransactionManager) -> None:
    _set_lock_timeout(fb_alias, 1)
    started = time.monotonic()
    with _watchdog(busy_row), pytest.raises(RecordBusy) as info:
        with transaction.atomic(using=fb_alias):
            with connections[fb_alias].cursor() as cursor:
                cursor.execute(UPDATE_ROW)
    elapsed = time.monotonic() - started
    assert elapsed < 3
    assert isinstance(info.value, OperationalError)
    assert str(info.value) == BUSY_MESSAGE


def test_default_timeout_is_3(fb_alias: str, busy_row: fbd.TransactionManager) -> None:
    wrapper = connections[fb_alias]
    wrapper.ensure_connection()
    assert cast(Any, wrapper)._lock_timeout == 3
    started = time.monotonic()
    with _watchdog(busy_row), pytest.raises(RecordBusy):
        with transaction.atomic(using=fb_alias):
            with connections[fb_alias].cursor() as cursor:
                cursor.execute(UPDATE_ROW)
    elapsed = time.monotonic() - started
    assert 2.5 <= elapsed <= 6


def test_reader_is_not_blocked(fb_alias: str, busy_row: fbd.TransactionManager) -> None:
    wrapper = connections[fb_alias]
    started = time.monotonic()
    with _watchdog(busy_row), wrapper.cursor() as cursor:
        cursor.execute(READ_ROW)
        row = cursor.fetchone()
    assert time.monotonic() - started < 1
    assert row is not None
