"""FirebirdCursorWrapper maps a row-lock refusal raised while fetching rows to RecordBusy (plan 4, Task 9).

A Firebird lock error from ``SELECT ... WITH LOCK`` can surface when the rows are fetched, not when the statement runs.
These tests use a fake driver cursor, so no database is needed.
"""

from collections.abc import Iterator
from typing import Any

import firebird.driver as fbd  # type: ignore[import-untyped]
import pytest

from infohr_firebird.base import FirebirdCursorWrapper
from infohr_firebird.errors import RecordBusy

LOCK_TIMEOUT = "lock time-out on wait transaction"
OTHER_ERROR = "table UNKNOWN"


class FakeCursor:
    """A driver cursor whose every fetch raises the given error (or returns one row when there is none)."""

    def __init__(self, error: BaseException | None) -> None:
        self.error = error

    def _fetch(self) -> Any:
        if self.error is not None:
            raise self.error
        return ("row",)

    def fetchone(self) -> Any:
        return self._fetch()

    def fetchmany(self, *args: Any, **kwargs: Any) -> Any:
        return [self._fetch()]

    def fetchall(self) -> Any:
        return [self._fetch()]

    def __iter__(self) -> Iterator[Any]:
        yield self._fetch()


def wrapper_for(error: BaseException | None) -> FirebirdCursorWrapper:
    return FirebirdCursorWrapper(FakeCursor(error), encoding="utf-8", autocommit=False)


@pytest.mark.parametrize("method", ["fetchone", "fetchmany", "fetchall"])
def test_lock_timeout_on_fetch_is_record_busy(method: str) -> None:
    error = fbd.DatabaseError(LOCK_TIMEOUT)
    with pytest.raises(RecordBusy) as info:
        getattr(wrapper_for(error), method)()
    assert info.value.__cause__ is error


def test_lock_timeout_while_iterating_is_record_busy() -> None:
    error = fbd.DatabaseError(LOCK_TIMEOUT)
    with pytest.raises(RecordBusy) as info:
        list(wrapper_for(error))
    assert info.value.__cause__ is error


def test_other_fetch_error_is_re_raised_unchanged() -> None:
    error = fbd.DatabaseError(OTHER_ERROR)
    with pytest.raises(fbd.DatabaseError) as info:
        wrapper_for(error).fetchall()
    assert info.value is error


def test_rows_pass_through_when_nothing_fails() -> None:
    cursor = wrapper_for(None)
    assert cursor.fetchone() == ("row",)
    assert cursor.fetchall() == [("row",)]
    assert list(wrapper_for(None)) == [("row",)]
