"""Errors that the Firebird backend raises for HR users."""

from django.db import OperationalError
from firebird.driver import DatabaseError as FbDatabaseError  # type: ignore[import-untyped]

RECORD_BUSY_MESSAGE = "Another user is editing this record. Try again in a moment."

# Firebird error codes (from include/iberror.h of Firebird 3.0) that mean a row is held by
# another transaction:
#   335544336  isc_deadlock         reported with an update conflict ("deadlock -update conflicts...")
#   335544345  isc_lock_conflict    no-wait request on a locked row
#   335544451  isc_update_conflict  the row was changed by a concurrent transaction
#   335544510  isc_lock_timeout     a wait on a locked row ran past the lock timeout
_BUSY_GDS_CODES = frozenset({335544336, 335544345, 335544451, 335544510})
# SQLSTATE 40001: the transaction could not be serialized and must be retried.
_BUSY_SQLSTATE = "40001"
# Message fragments of the same errors, for when the codes are not reported.
_BUSY_MESSAGES = ("update conflicts with concurrent update", "lock conflict", "lock time-out")


class RecordBusy(OperationalError):
    """A row is held by another user's open transaction, and the wait was refused or timed out."""


def busy_error_for(exc: BaseException) -> RecordBusy | None:
    """Return a RecordBusy when a Firebird error means a row is busy, otherwise None.

    Callers chain the original error with `raise busy from exc`.
    """
    if not isinstance(exc, FbDatabaseError):
        return None
    if exc.sqlstate == _BUSY_SQLSTATE or _BUSY_GDS_CODES.intersection(exc.gds_codes or ()):
        return RecordBusy(RECORD_BUSY_MESSAGE)
    text = str(exc).lower()
    if any(fragment in text for fragment in _BUSY_MESSAGES):
        return RecordBusy(RECORD_BUSY_MESSAGE)
    return None
