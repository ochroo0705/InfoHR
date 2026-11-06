"""MACS database triggers that HR relies on (plan 3, Task 4).

HR writes into MACS tables. Some MACS behaviour lives in triggers (the employee id generator, the
address and contact audit triggers, the customer triggers). If one of them is missing or inactive, an
HR write can succeed and still leave the MACS data wrong. ``require()`` lets a write function refuse to
run before it writes anything.

On PostgreSQL none of this applies: ``missing()`` returns [] and ``require()`` does nothing, without
touching the database.
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection

EXPECTED: dict[str, frozenset[str]] = {
    "EMPLOYEE": frozenset({"TR_EMPLOYEEID", "EMPLOYEE_BU0", "TR_EMPCUST"}),
    "MOVEMENT": frozenset({"MOVEMENT_AI0"}),
    "EMPLOYEE_HISTORY": frozenset({"EMPLOYEE_HISTORY_BD0"}),
    "CONTACTING": frozenset({"CONTACTING_AI0", "CONTACTING_AU0"}),
    "ADDRESS": frozenset({"ADDRESS_BI"}),
    "CUSTOMER": frozenset({"TR_CUSTID", "TR_UPDCUSTOMER"}),
}

# Table sets that already passed require() in this process. A failing result is never stored.
_verified: set[frozenset[str]] = set()


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

    A positive result is cached per process for this exact set of tables. A trigger deactivated later
    in the same process is therefore not noticed until the process restarts. A failing result is not
    cached, so the next call checks again. Does nothing on PostgreSQL.
    """
    if not database_has_triggers():
        return
    key = frozenset(tables)
    if key in _verified:
        return
    names = missing(*tables)
    if names:
        raise MacsTriggerMissing(
            f"MACS triggers missing or inactive: {', '.join(names)}. HR does not write until they are active."
        )
    _verified.add(key)


def _expected_names(table: str) -> frozenset[str]:
    if table not in EXPECTED:
        raise ValueError(f"No MACS trigger list for table {table!r}; add it to macs.triggers.EXPECTED.")
    return EXPECTED[table]
