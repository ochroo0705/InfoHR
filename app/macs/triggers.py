"""MACS database triggers that HR relies on (plan 3, Task 4).

HR writes into MACS tables. Some MACS behaviour lives in triggers (the employee id generator, the
address and contact audit triggers, the customer triggers). If one of them is missing or inactive, an
HR write can succeed and still leave the MACS data wrong. ``require()`` lets a write function refuse to
run before it writes anything.

On PostgreSQL none of this applies: ``missing()`` returns [] and ``require()`` does nothing, without
touching the database.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.db import connection

# Seconds a positive require() result stays valid in this process. After it, the triggers are checked again.
RECHECK_SECONDS = 300

EXPECTED: dict[str, frozenset[str]] = {
    "EMPLOYEE": frozenset({"TR_EMPLOYEEID", "EMPLOYEE_BU0", "TR_EMPCUST"}),
    # MOVEMENT_AI0 (AFTER INSERT) runs only for movements 'dep' and 'occ'. It copies the new branch, department and
    # position (new_branchid, new_depid, new_occupid) onto the employee row and sets status or contract_emp when
    # new_emptype changes. record_movement() sends all of those columns, so HR's Movement insert depends on it.
    "MOVEMENT": frozenset({"MOVEMENT_AI0"}),
    # EMPLOYEE_HISTORY_BD0 (BEFORE DELETE) rewrites the employee row from the previous history row. HR's
    # delete_event_rows() deletes history rows, so it depends on this trigger.
    "EMPLOYEE_HISTORY": frozenset({"EMPLOYEE_HISTORY_BD0"}),
    "CONTACTING": frozenset({"CONTACTING_AI0", "CONTACTING_AU0"}),
    "ADDRESS": frozenset({"ADDRESS_BI"}),
    "CUSTOMER": frozenset({"TR_CUSTID", "TR_UPDCUSTOMER"}),
}

# Tables whose triggers the personal-tab writes (contacts, addresses) rely on.
PERSONAL_WRITE_TABLES = ("CONTACTING", "ADDRESS", "CUSTOMER")

# Table sets that passed require() in this process, with the time.monotonic() reading of that check. A failing
# result is never stored.
_verified_at: dict[frozenset[str], float] = {}


class MacsTriggerMissing(Exception):
    """A MACS trigger that HR relies on is missing or inactive."""


def database_has_triggers() -> bool:
    return bool(settings.DB_ENGINE == "firebird")


def missing(*tables: str) -> list[str]:
    """Return the expected triggers of these tables that are missing or inactive, sorted.

    Active means RDB$TRIGGER_INACTIVE is 0 or NULL. Returns [] on PostgreSQL without querying anything.
    Raises ValueError for a table that has no entry in EXPECTED.
    """
    wanted = {(name, table) for table in tables for name in _expected_names(table)}
    if not database_has_triggers() or not wanted:
        return []
    names = sorted({name for name, _ in wanted})
    placeholders = ", ".join(["%s"] * len(names))  # only %s marks; the names themselves are passed as parameters
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT TRIM(RDB$TRIGGER_NAME), TRIM(RDB$RELATION_NAME) FROM RDB$TRIGGERS "  # noqa: S608 (%s marks only)
            "WHERE (RDB$TRIGGER_INACTIVE IS NULL OR RDB$TRIGGER_INACTIVE = 0) "
            f"AND TRIM(RDB$TRIGGER_NAME) IN ({placeholders})",
            names,
        )
        active = {(str(name), str(table)) for name, table in cursor.fetchall()}
    return sorted(name for name, table in wanted if (name, table) not in active)


def require(*tables: str) -> None:
    """Raise MacsTriggerMissing unless every expected trigger of these tables is active.

    A positive result is cached per process for this exact set of tables and re-checked once it is
    older than RECHECK_SECONDS, so a trigger switched off later in the same process is noticed. A failing
    result is not cached, so the next call checks again. Does nothing on PostgreSQL.
    """
    if not database_has_triggers():
        return
    key = frozenset(tables)
    checked_at = _verified_at.get(key)
    if checked_at is not None and time.monotonic() - checked_at < RECHECK_SECONDS:
        return
    names = missing(*tables)
    if names:
        _verified_at.pop(key, None)
        raise MacsTriggerMissing(
            f"MACS triggers missing or inactive: {', '.join(names)}. HR does not write until they are active."
        )
    _verified_at[key] = time.monotonic()


def _expected_names(table: str) -> frozenset[str]:
    if table not in EXPECTED:
        raise ValueError(f"No MACS trigger list for table {table!r}; add it to macs.triggers.EXPECTED.")
    return EXPECTED[table]
