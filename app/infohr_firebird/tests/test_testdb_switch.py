"""The Firebird test switch (plan 6, Task 1): INFOHR_TEST_DB=firebird runs pytest on ONE migrated copy of the template.

Each check runs pytest in a subprocess, so the switch, the environment and the settings are read fresh. The probe
tests are in pg_only_probes.py, which pytest does not collect by itself.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

REPO_DIR = Path(__file__).resolve().parents[3]  # <repo>
PROBES = "app/infohr_firebird/tests/pg_only_probes.py"
TEMPLATE = os.environ.get("FB_TEMPLATE_FDB", "")


def _pytest(*args: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    """Run pytest from the repo root with the switch variables cleared, then the overrides."""
    cleared = ("INFOHR_TEST_DB", "DB_ENGINE", "FIREBIRD_NAME")
    env = {key: value for key, value in os.environ.items() if key not in cleared}
    env.update(env_overrides)
    return subprocess.run(  # noqa: S603 (fixed argv, our own probes)
        [sys.executable, "-m", "pytest", *args],
        cwd=str(REPO_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _firebird_env() -> dict[str, str]:
    """The switch on, Firebird settings and the template. FIREBIRD_NAME is required by the settings, is never opened."""
    return {
        "INFOHR_TEST_DB": "firebird",
        "DB_ENGINE": "firebird",
        "FB_TEMPLATE_FDB": TEMPLATE,
        "FIREBIRD_NAME": TEMPLATE or "not-opened.fdb",
    }


def test_pg_only_marker_requires_a_reason() -> None:
    proc = _pytest(f"{PROBES}::test_bare_marker", "-q")
    assert proc.returncode != 0, proc.stdout
    assert "pg_only needs a reason" in proc.stdout + proc.stderr


def test_pg_only_test_is_skipped_on_firebird() -> None:
    proc = _pytest(f"{PROBES}::test_marked_probe", "-q", "-rs", **_firebird_env())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 skipped" in proc.stdout
    assert "PostgreSQL only: probe: stands in" in proc.stdout


def test_default_alias_points_at_a_migrated_copy() -> None:
    if not TEMPLATE or not Path(TEMPLATE).is_file():
        pytest.skip("FB_TEMPLATE_FDB is not set to an existing template")
    proc = _pytest("app/lists/tests/test_registry.py::test_personal_list_slugs_registered", "-q", **_firebird_env())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout


def test_copy_is_deleted_after_the_session() -> None:
    if not TEMPLATE or not Path(TEMPLATE).is_file():
        pytest.skip("FB_TEMPLATE_FDB is not set to an existing template")
    proc = _pytest(f"{PROBES}::test_copy_path_probe", "-q", "-s", **_firebird_env())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    found = re.search(r"COPY_PATH=(.+)", proc.stdout)
    assert found is not None, proc.stdout
    copy = Path(found.group(1).strip())
    assert copy.parent.name.startswith("scratch6_"), copy
    assert not copy.exists(), f"the copy was not deleted at the end of the session: {copy}"


def test_session_copy_has_no_macs_rows() -> None:
    """The session copy is emptied of MACS rows (plan 6, Task 3); the HR seed rows stay."""
    if not TEMPLATE or not Path(TEMPLATE).is_file():
        pytest.skip("FB_TEMPLATE_FDB is not set to an existing template")
    proc = _pytest(f"{PROBES}::test_session_counts_probe", "-q", "-s", **_firebird_env())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    found = re.search(r"COUNTS=(\{.*\})", proc.stdout)
    assert found is not None, proc.stdout
    counts: dict[str, int] = json.loads(found.group(1))
    assert counts["EMPLOYEE"] == 0, counts
    assert counts["CUSTOMER"] == 0, counts
    assert counts["DEPS"] == 0, counts
    assert counts["IHR_AUTH_GROUP"] > 0, counts


COUNT_CODE = """
import json
import django
django.setup()
from django.db import connection
with connection.cursor() as c:
    counts = {}
    for table in ("EMPLOYEE", "CUSTOMER", "DEPS"):
        c.execute("select count(*) from " + table)
        counts[table] = c.fetchone()[0]
print("RESULT " + json.dumps(counts))
"""


def test_backend_clone_keeps_macs_data(migrated_clone: str) -> None:
    """The migrated_clone fixture (used by the Firebird backend tests) keeps the MACS rows they rely on."""
    counts = result_of(run_django(COUNT_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    assert counts["EMPLOYEE"] > 0, counts
    assert counts["CUSTOMER"] > 0, counts
    assert counts["DEPS"] > 0, counts


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("db/work/scratch6_ab12cd/migrated.fdb", True),
        ("db/work/template_clone.fdb", False),
        ("db/MACSXE4DB.FDB", False),
        ("db/work/scratch6_ab12cd/other.fdb", False),
        ("db/work/notscratch/migrated.fdb", False),
    ],
)
def test_scratch_copy_name_check(name: str, expected: bool) -> None:
    from infohr_firebird.testdb import is_scratch_copy

    assert is_scratch_copy(name) is expected


def test_prepare_names_its_copy_so_the_check_accepts_it(tmp_path: Path) -> None:
    """The check and prepare() share one naming rule: a folder made the way prepare makes it passes the check."""
    import tempfile

    from infohr_firebird.testdb import COPY_NAME, FOLDER_PREFIX, is_scratch_copy

    folder = Path(tempfile.mkdtemp(prefix=FOLDER_PREFIX, dir=tmp_path))
    assert is_scratch_copy(str(folder / COPY_NAME))


def test_empty_macs_rows_refuses_a_database_that_is_not_a_scratch_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pointed at the template clone, empty_macs_rows raises before any SQL (the cursor is a tripwire)."""
    from django.db import connections

    from infohr_firebird import testdb

    alias = connections["default"]
    monkeypatch.setitem(alias.settings_dict, "NAME", "db/work/template_clone.fdb")

    def sql_ran(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("SQL ran before the guard refused the database")

    monkeypatch.setattr(alias, "cursor", sql_ran)
    with pytest.raises(RuntimeError, match="scratch copy"):
        testdb.empty_macs_rows()
