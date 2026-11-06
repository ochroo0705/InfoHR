"""SQL that differs between PostgreSQL and Firebird (plan 3, Task 9).

The write functions run raw SQL in both databases. Two statements differ:
- a generator (sequence) value: PostgreSQL `nextval`, Firebird `gen_id`;
- a row lock on a select: PostgreSQL `FOR UPDATE`, Firebird `WITH LOCK` (placed at the end of the statement).

The mode is `settings.DB_ENGINE`, as in `macs.triggers`. Generator names come from a fixed allow-list in this
module, never from user input.
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection

# PostgreSQL sequence name -> Firebird generator name.
GENERATORS: dict[str, str] = {
    "gen_employee_history_id": "GEN_EMPLOYEE_HISTORY_ID",
}


def is_firebird() -> bool:
    return bool(settings.DB_ENGINE == "firebird")


def next_value(generator: str) -> int:
    """Take the next value of a generator. The name must be in GENERATORS (ValueError otherwise)."""
    if generator not in GENERATORS:
        raise ValueError(f"unknown generator: {generator!r}; add it to macs.dialect.GENERATORS")
    with connection.cursor() as cur:
        if is_firebird():
            # The name is a constant from GENERATORS, so interpolating it is safe.
            cur.execute(f"select gen_id({GENERATORS[generator]}, 1) from rdb$database")
        else:
            cur.execute("select nextval(%s)", [generator])
        return int(cur.fetchone()[0])


def lock_suffix() -> str:
    """The clause that locks the rows a SELECT returns, appended to the statement (after ORDER BY)."""
    return " WITH LOCK" if is_firebird() else " FOR UPDATE"
