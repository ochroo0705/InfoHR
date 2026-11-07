"""Probe tests for test_testdb_switch.py (plan 6, Task 1).

This file does not match python_files, so `pytest app` never collects it. The switch tests run its probes by node id,
in a subprocess, so the switch and the settings are read fresh.
"""

import json

import pytest
from django.db import connections


@pytest.mark.pg_only
def test_bare_marker() -> None:
    """A bare pg_only (no reason) must fail collection. This body must never run."""
    raise AssertionError("a bare pg_only marker ran")


@pytest.mark.pg_only("probe: stands in for a test that checks a PostgreSQL-only feature")
def test_marked_probe() -> None:
    assert True


@pytest.mark.django_db
def test_copy_path_probe() -> None:
    """Prints the database file the default alias uses, so the switch test can check it is deleted afterwards."""
    print(f"COPY_PATH={connections['default'].settings_dict['NAME']}")


@pytest.mark.django_db
def test_session_counts_probe() -> None:
    """Prints row counts on the session's default alias: three MACS tables and one HR seed table (plan 6, Task 3)."""
    counts: dict[str, int] = {}
    with connections["default"].cursor() as cursor:
        for table in ("EMPLOYEE", "CUSTOMER", "DEPS", "IHR_AUTH_GROUP"):
            cursor.execute(f"select count(*) from {table}")  # noqa: S608 (fixed table names)
            counts[table] = int(cursor.fetchone()[0])
    print("COUNTS=" + json.dumps(counts))
