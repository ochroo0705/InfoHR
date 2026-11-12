"""Firebird test database for the whole suite (plan 6, Task 1).

With INFOHR_TEST_DB=firebird, pytest makes ONE migrated copy of the template at session start (prepare), points the
`default` alias at it (app/conftest.py, django_db_setup) and deletes it at the end (discard). Every test then runs in
pytest-django's normal rolled-back transaction.

The copy is migrated the way the migrated_clone fixture always did: one `manage.py migrate <app>` per app, in
MIGRATE_ORDER, each in its own interpreter, so the settings read the Firebird variables.

The session copy (empty=True) then loses its MACS rows (empty_macs_rows), because the PostgreSQL test database has
none; migrated_clone (empty=False) keeps them for the backend tests that rely on them (plan 6, Task 3).
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from infohr_firebird.tests.copies import remove_copy

APP_DIR = Path(__file__).resolve().parents[1]  # <repo>/app
WORK_DIR = APP_DIR.parent / "db" / "work"  # scratch copies live here (git-ignored), never in the template's place
FOLDER_PREFIX = "scratch6_"  # prepare() makes each copy in a new folder with this prefix
COPY_NAME = "migrated.fdb"  # the copy's file name inside that folder

# Environment variables that select a database engine. A subprocess starts without them, then gets its own.
SEAM_VARS = (
    "DB_ENGINE",
    "FIREBIRD_HOST",
    "FIREBIRD_PORT",
    "FIREBIRD_NAME",
    "FIREBIRD_USER",
    "FIREBIRD_PASSWORD",
    "DJANGO_HR_TABLE_PREFIX",
    "DJANGO_DB_NAME",
    "DATABASE_URL",
    "FIREBIRD_CLIENT_LIBRARY",
    "FIREBIRD_DIALECT",
)

# The foundation acceptance order (docs/superpowers/plans/2026-11-03-firebird3-foundation.md, Task 10).
MIGRATE_ORDER = (
    "contenttypes",
    "auth",
    "sessions",
    "admin",
    "accounts",
    "lists",
    "leave",
    "recruitment",
    "reports",
    "macs",
    "employees",
    "checklists",
    "assistant",
    "hr_mcp",
)


def run_manage(args: list[str], **overrides: str) -> subprocess.CompletedProcess[str]:
    """Run manage.py in a fresh interpreter with the seam variables cleared, then set the overrides."""
    env = {key: value for key, value in os.environ.items() if key not in SEAM_VARS}
    env.update({"DJANGO_SETTINGS_MODULE": "config.settings", "PYTHONPATH": str(APP_DIR)})
    env.update(overrides)
    return subprocess.run(  # noqa: S603 (fixed argv, our own script)
        [sys.executable, "-B", str(APP_DIR / "manage.py"), *args],
        env=env,
        cwd=str(APP_DIR),
        capture_output=True,
        text=True,
        check=False,
    )


def prepare(template: str, work_dir: Path = WORK_DIR, *, empty: bool = False) -> str:
    """Copy the template into a new scratch folder and migrate the copy through every app. Returns the copy's path.

    With empty=True (the pytest session copy) the MACS rows are then deleted, so the copy matches the empty PostgreSQL
    test database; the HR tables keep their migration seeds. With empty=False (migrated_clone) the data stays.

    The template is never opened for writing. A migration or emptying that fails deletes the copy and raises
    RuntimeError.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=FOLDER_PREFIX, dir=work_dir))
    clone = folder / COPY_NAME
    try:
        shutil.copyfile(template, clone)
        for app in MIGRATE_ORDER:
            proc = run_manage(["migrate", app, "--noinput"], DB_ENGINE="firebird", FIREBIRD_NAME=str(clone))
            if proc.returncode != 0:
                raise RuntimeError(f"migrate {app} failed:\n{proc.stdout}\n{proc.stderr}")
        if empty:
            proc = run_manage(
                ["shell", "-c", "from infohr_firebird.testdb import empty_macs_rows; empty_macs_rows()"],
                DB_ENGINE="firebird",
                FIREBIRD_NAME=str(clone),
            )
            if proc.returncode != 0:
                raise RuntimeError(f"emptying the copy failed:\n{proc.stdout}\n{proc.stderr}")
    except BaseException:
        discard(clone)
        raise
    return str(clone)


# Firebird names in the copy are plain upper-case identifiers (dialect 1 has no quoted names). Anything else is refused.
_PLAIN_NAME = re.compile(r"[A-Z][A-Z0-9_$]*")


def _plain(name: str) -> str:
    if not _PLAIN_NAME.fullmatch(name):
        raise RuntimeError(f"name not emptied, not a plain identifier: {name!r}")
    return name


_SCRATCH_FOLDER = re.compile(re.escape(FOLDER_PREFIX) + r"[A-Za-z0-9_]+")


def is_scratch_copy(name: str) -> bool:
    """True when `name` is a copy made by prepare(): <some folder>/<FOLDER_PREFIX>xxxx/<COPY_NAME>. Uses the same
    constants as prepare(), so the two cannot drift apart."""
    path = Path(name)
    return path.name == COPY_NAME and _SCRATCH_FOLDER.fullmatch(path.parent.name) is not None


def empty_macs_rows() -> int:
    """Delete every row of every MACS table (every table without the HR prefix). Returns the table count.

    Runs in the copy's own `manage.py shell` (see prepare). The HR tables and their migration seeds, the generators
    and the triggers' definitions are left as they are. Refuses, before any SQL, a connection whose database file is
    not a scratch copy made by prepare(). Steps:

    - Every MACS trigger that is active is set INACTIVE first and ACTIVE again in a finally, so the copy ends as it
      began. The triggers would refill or block the deletes: the audit triggers write DELETED_RECORD and SERVCARDS_BD0
      raises on old service cards. Only the copy is changed; the template is never opened.
    - Firebird cannot switch foreign keys off. Tables are deleted in passes: a table whose delete fails (a foreign key
      still refers to it) is tried again after the others. A pass with no success raises, with the first error.
    - At the end every MACS table is counted again, and any row left is an error.
    """
    from django.conf import settings
    from django.db import DatabaseError, connection

    name = str(connection.settings_dict["NAME"])
    if not is_scratch_copy(name):
        raise RuntimeError(
            f"empty_macs_rows refused: {name!r} is not a scratch copy made by testdb.prepare"
            f" (expected <folder>/{FOLDER_PREFIX}xxxx/{COPY_NAME}); it would delete MACS data"
        )
    prefix = str(settings.HR_TABLE_PREFIX).upper()
    with connection.cursor() as cursor:
        cursor.execute(
            "select trim(rdb$relation_name) from rdb$relations"
            " where rdb$view_blr is null and coalesce(rdb$system_flag, 0) = 0"
        )
        names = [_plain(str(row[0])) for row in cursor.fetchall()]
        macs = sorted(name for name in names if not name.startswith(prefix))
        cursor.execute(
            "select trim(rdb$trigger_name), trim(rdb$relation_name), rdb$trigger_inactive from rdb$triggers"
            " where coalesce(rdb$system_flag, 0) = 0"
        )
        triggers = [
            _plain(str(name))
            for name, relation, inactive in cursor.fetchall()
            if not str(relation).startswith(prefix) and not inactive
        ]
        for name in triggers:
            cursor.execute(f"alter trigger {name} inactive")  # noqa: S608 (plain names, checked above)
        try:
            # A row that refers to a row of its own table cannot be deleted in one statement (Firebird checks each
            # parent row as it goes), so those reference columns are set to NULL first. Only nullable ones are handled.
            cursor.execute(
                "select trim(rc.rdb$relation_name), trim(seg.rdb$field_name), rf.rdb$null_flag"
                " from rdb$ref_constraints refc"
                " join rdb$relation_constraints rc on rc.rdb$constraint_name = refc.rdb$constraint_name"
                " join rdb$relation_constraints rc2 on rc2.rdb$constraint_name = refc.rdb$const_name_uq"
                " join rdb$index_segments seg on seg.rdb$index_name = rc.rdb$index_name"
                " join rdb$relation_fields rf on rf.rdb$relation_name = rc.rdb$relation_name"
                " and rf.rdb$field_name = seg.rdb$field_name"
                " where rc.rdb$relation_name = rc2.rdb$relation_name"
            )
            for table, column, not_null in cursor.fetchall():
                if str(table).startswith(prefix):
                    continue
                if not_null:
                    raise RuntimeError(f"self-reference {table}.{column} is NOT NULL; the copy cannot be emptied")
                cursor.execute(
                    f"update {_plain(str(table))} set {_plain(str(column))} = null"  # noqa: S608 (plain names)
                    f" where {_plain(str(column))} is not null"  # noqa: S608 (plain names)
                )
            pending = macs
            while pending:
                failed: list[tuple[str, DatabaseError]] = []
                for table in pending:
                    try:
                        cursor.execute(f"delete from {table}")  # noqa: S608 (plain names, checked above)
                    except DatabaseError as exc:
                        failed.append((table, exc))
                if failed and len(failed) == len(pending):
                    first_table, first_error = failed[0]
                    raise RuntimeError(f"cannot empty {len(failed)} tables; first {first_table}: {first_error}")
                pending = [table for table, _ in failed]
        finally:
            for name in triggers:
                cursor.execute(f"alter trigger {name} active")  # noqa: S608 (plain names, checked above)
        for table in macs:
            cursor.execute(f"select count(*) from {table}")  # noqa: S608 (plain names, checked above)
            left = int(cursor.fetchone()[0])
            if left:
                raise RuntimeError(f"{table} still has {left} rows after emptying")
    return len(macs)


def discard(clone: Path) -> None:
    """Delete a copy made by prepare, and its scratch folder once the copy is gone."""
    remove_copy(clone)
    if not clone.exists():
        try:
            clone.parent.rmdir()
        except OSError:
            pass
