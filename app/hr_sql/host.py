"""The HR host of the governed SQL (sqlcore.runner.Host): runs a checked query as the asker, and can cancel it.

execute, in one transaction on the governed connection:
  1. fill GOV_SCOPE with the asker's visible employee ids (hr_sql/scope.py),
  2. run the checked SQL and fetch at most max_rows + 1 rows,
  3. always roll back, so GOV_SCOPE is empty again whatever happened.

cancel: Firebird's own cancel call (fb_cancel_operation with fb_cancel_raise, the driver's
Attachment.cancel_operation(CancelType.RAISE)). It makes the running statement raise and leaves the attachment
usable. It is aimed at the run of the same user that is in progress; a call with nothing running does nothing.
Each run is registered under the user's id only while it executes, under a lock, so a cancel after the run has
unregistered does nothing. Known gap: a cancel that lands in the short window between the last fetch and the
unregister can leave a cancel flag on the attachment; see the task report.
"""

import contextlib
import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.db import transaction
from firebird.driver import CancelType  # type: ignore[import-untyped]
from sqlcore.catalogue import Catalogue
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, QueryTimeout, Result

from hr_sql.catalogue import catalogue_for
from hr_sql.connection import GOVERNED_ALIAS, governed_connection
from hr_sql.scope import fill_scope


@dataclass(eq=False)
class _Run:
    attachment: Any  # the driver's attachment (firebird.driver), the object that owns cancel_operation
    cancelled: bool = False


def _exact(cell: Any) -> Any:
    """Firebird dialect 1 stores money with more than 9 digits as DOUBLE PRECISION, which the driver returns as a
    float. Its shortest repr is the amount that was stored (the same rule as ExactMoneyField.from_db_value), so the
    answer shows an exact Decimal. Other values pass through unchanged."""
    if isinstance(cell, float):
        return Decimal(repr(cell))
    return cell


class _Discard(Exception):
    """Ends the governed transaction on purpose, so Django rolls it back."""


_runs_lock = threading.Lock()
_runs: dict[int, list[_Run]] = {}


def _register(user_id: int, run: _Run) -> None:
    with _runs_lock:
        _runs.setdefault(user_id, []).append(run)


def _unregister(user_id: int, run: _Run) -> None:
    with _runs_lock:
        runs = _runs.get(user_id, [])
        if run in runs:
            runs.remove(run)
        if not runs:
            _runs.pop(user_id, None)


class HrHost:
    def catalogue_for(self, user: object) -> Catalogue:
        if not isinstance(user, User):
            return Catalogue(views=())
        return catalogue_for(user)

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        if not isinstance(user, User) or user.pk is None:
            raise PermissionError("Only a saved user can run a governed query.")
        connection = governed_connection()
        connection.ensure_connection()
        run = _Run(attachment=connection.connection._att)
        answer: Result | None = None
        _register(user.pk, run)
        try:
            # Everything below is discarded: the sentinel ends the transaction, so the scope rows and the query's
            # rows never outlive this call, on success or on failure.
            with transaction.atomic(using=GOVERNED_ALIAS), connection.cursor() as cursor:
                fill_scope(connection, user)
                cursor.execute(query.sql)
                columns = tuple(str(column[0] or "").strip() for column in cursor.description or ())
                rows = tuple(tuple(_exact(cell) for cell in row) for row in cursor.fetchmany(limits.max_rows + 1))
                answer = Result(columns=columns, rows=rows, truncated=False)
                raise _Discard()
        except _Discard:
            pass
        except Exception as error:
            if run.cancelled:
                raise QueryTimeout("The query was cancelled because it ran past its time limit.") from error
            raise
        finally:
            _unregister(user.pk, run)
        if run.cancelled:
            raise QueryTimeout("The query was cancelled because it ran past its time limit.")
        if answer is None:  # not reachable: the block either raised or set the answer
            raise RuntimeError("The governed query produced no result.")
        return answer

    def cancel(self, user: object) -> None:
        if not isinstance(user, User) or user.pk is None:
            return
        with _runs_lock:
            for run in _runs.get(user.pk, []):
                run.cancelled = True
                # A failed cancel must not raise into the timer thread; the run then ends on its own.
                with contextlib.suppress(Exception):
                    run.attachment.cancel_operation(int(CancelType.RAISE))
