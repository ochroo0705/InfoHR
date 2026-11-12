"""The runner: check a question, run it through a host under a time limit, and cap the rows.

Plain Python only. No Django, no HR imports, no database connection.
The host does the database work and the access rules; this module only sequences the steps.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from sqlcore.catalogue import Catalogue
from sqlcore.check import CheckedQuery, CheckError, check_sql
from sqlcore.limits import Limits, QueryTimeout, Result

TIMEOUT_REASON = "The query took too long and was stopped."
FAILURE_REASON = "The query could not be run."
DEFAULT_LIMITS = Limits()


class Host(Protocol):
    def catalogue_for(self, user: object) -> Catalogue: ...

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        """Run the checked query as this user. Return at most limits.max_rows + 1 rows.

        Raise QueryTimeout when cancel stopped it. Any other exception is reported as a refusal.
        """
        ...

    def cancel(self, user: object) -> None: ...


@dataclass(frozen=True)
class Answered:
    result: Result
    query: CheckedQuery


@dataclass(frozen=True)
class Refused:
    reason: str


def run_question(host: Host, user: object, sql: str, limits: Limits = DEFAULT_LIMITS) -> Answered | Refused:
    if limits.max_rows < 1:
        raise ValueError("max_rows must be at least 1.")
    if limits.timeout_s <= 0:
        raise ValueError("timeout_s must be greater than 0.")

    try:
        query = check_sql(sql, host.catalogue_for(user))
    except CheckError as error:
        return Refused(reason=str(error))

    timer = threading.Timer(limits.timeout_s, host.cancel, [user])
    timer.start()
    try:
        raw = host.execute(user, query, limits)
    except QueryTimeout:
        return Refused(reason=TIMEOUT_REASON)
    except Exception:
        return Refused(reason=FAILURE_REASON)
    finally:
        timer.cancel()

    truncated = raw.truncated or len(raw.rows) > limits.max_rows
    rows = raw.rows[: limits.max_rows]
    result = Result(columns=raw.columns, rows=rows, truncated=truncated)
    return Answered(result=result, query=query)
