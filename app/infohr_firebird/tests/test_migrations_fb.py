"""Firebird migration set (firebird3-foundation Task 12, ruling R26).

In Firebird mode eight apps use their own generated initial migrations (``migrations_fb``). The PostgreSQL
history creates columns named with Firebird reserved words and renames them later, so its first CreateModel
fails on Firebird. The PostgreSQL history is never edited. Every test runs Django in a subprocess, like
test_settings_seam.py, so config.settings is read fresh with the environment each test sets.
"""

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from infohr_firebird.reserved import RESERVED_WORDS
from infohr_firebird.testdb import run_manage
from infohr_firebird.tests.copies import remove_copy
from infohr_firebird.tests.test_settings_seam import FIREBIRD_PATH, POSTGRES_URL, result_of, run_django

APP_DIR = Path(__file__).resolve().parents[2]  # <repo>/app
WORK_DIR = APP_DIR.parent / "db" / "work"  # scratch copies live here (git-ignored), never in the template's place
FB_APPS = ("accounts", "lists", "leave", "recruitment", "reports", "employees", "checklists", "assistant")
FB_MODULES = {app: f"{app}.migrations_fb" for app in FB_APPS}

SETTING_CODE = """
import json
import django
django.setup()
from django.conf import settings
print("RESULT " + json.dumps({"setting": settings.MIGRATION_MODULES}))
"""

# Loads the migration files the way the migrate command does (no database) and lists, per app,
# the migration names and the column of every CreateModel field and AddField (M2M fields have no column here).
LOAD_CODE = """
import json
import django
django.setup()
from django.db import models
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations import AddField, CreateModel

FB_APPS = ["accounts", "lists", "leave", "recruitment", "reports", "employees", "checklists", "assistant"]
loader = MigrationLoader(None, load=False)
loader.load_disk()
names = {app: sorted(name for label, name in loader.disk_migrations if label == app) for app in FB_APPS}
columns = {app: [] for app in FB_APPS}
for (label, name), migration in loader.disk_migrations.items():
    if label not in FB_APPS:
        continue
    for operation in migration.operations:
        if isinstance(operation, CreateModel):
            pairs = operation.fields
        elif isinstance(operation, AddField):
            pairs = [(operation.name, operation.field)]
        else:
            continue
        for field_name, field in pairs:
            if isinstance(field, models.ManyToManyField):
                continue
            if field.db_column:
                column = field.db_column
            elif isinstance(field, models.ForeignKey):
                column = field_name + "_id"
            else:
                column = field_name
            columns[label].append(name + ":" + column)
print("RESULT " + json.dumps({"names": names, "columns": columns}))
"""

# Lists every identifier the Firebird initials create that Firebird limits to 31 characters: constraint names,
# index names, explicit db_table and explicit db_column. Each entry is "kind name: identifier".
NAMES_CODE = """
import json
import django
django.setup()
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations import AddConstraint, AddField, AddIndex, CreateModel

FB_APPS = ["accounts", "lists", "leave", "recruitment", "reports", "employees", "checklists", "assistant"]
loader = MigrationLoader(None, load=False)
loader.load_disk()
found = {app: [] for app in FB_APPS}
models = {app: [] for app in FB_APPS}
for (label, name), migration in loader.disk_migrations.items():
    if label not in FB_APPS:
        continue
    for operation in migration.operations:
        if isinstance(operation, CreateModel):
            models[label].append(operation.name)
            options = operation.options
            if options.get("db_table"):
                found[label].append("table " + options["db_table"])
            for constraint in options.get("constraints", []):
                found[label].append("constraint " + constraint.name)
            for index in options.get("indexes", []):
                found[label].append("index " + index.name)
            for field_name, field in operation.fields:
                if field.db_column:
                    found[label].append("column " + field.db_column)
        elif isinstance(operation, AddField):
            if operation.field.db_column:
                found[label].append("column " + operation.field.db_column)
        elif isinstance(operation, AddConstraint):
            found[label].append("constraint " + operation.constraint.name)
        elif isinstance(operation, AddIndex):
            found[label].append("index " + operation.index.name)
print("RESULT " + json.dumps({"found": found, "models": models}))
"""

PG_CODE = """
import json
import django
django.setup()
from django.conf import settings
from django.db.migrations.loader import MigrationLoader
loader = MigrationLoader(None, load=False)
loader.load_disk()
apps = ["accounts", "lists", "leave", "recruitment", "reports", "employees", "checklists", "assistant"]
print("RESULT " + json.dumps({
    "setting": getattr(settings, "MIGRATION_MODULES", {}),
    "modules": {app: MigrationLoader.migrations_module(app)[0] for app in apps},
    "accounts": sorted(name for label, name in loader.disk_migrations if label == "accounts"),
}))
"""


@pytest.fixture
def work_copy() -> Iterator[str]:
    """Copy the Firebird template into a folder under db/work and yield the copy's path.

    The copy and its folder are deleted at teardown. The template itself is never opened.
    """
    template_text = os.environ.get("FB_TEMPLATE_FDB", "")
    if not template_text:
        pytest.skip("FB_TEMPLATE_FDB is not set")
    template = Path(template_text)
    if not template.is_file():
        pytest.skip(f"Firebird template not found: {template}")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="t12_", dir=WORK_DIR))
    clone = folder / "check.fdb"
    try:
        shutil.copyfile(template, clone)
        yield str(clone)
    finally:
        remove_copy(clone)
        if not clone.exists():
            try:
                folder.rmdir()
            except OSError:
                pass


def test_firebird_mode_uses_the_firebird_migration_modules() -> None:
    data = result_of(run_django(SETTING_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH))
    assert data["setting"] == FB_MODULES


# The second migration of each Firebird set that has one (plan Task 7b): the overlap trigger and the emulated rules.
SECOND_MIGRATIONS = {"employees": "0002_history_overlap_guard", "checklists": "0002_emulated_unique"}
# The starter-data migration (plans Task 8a, 8b): roles, permissions and starter rows, on every app that has one.
# employees and checklists already have a second migration, so their seed is the third.
SEED_MIGRATIONS = {app: "0002_seed" for app in ("accounts", "lists", "leave", "recruitment", "reports", "assistant")}
SEED_MIGRATIONS.update({app: "0003_seed" for app in ("employees", "checklists")})
# The change_text column of the two log tables (plan 5, task 5b), added after the seed migrations.
CHANGE_TEXT_MIGRATIONS = {"employees": "0004_activityentry_change_text", "accounts": "0003_systemlogentry_change_text"}
# The SavedView visibility, default flag and longer query (reports part 1, task 8), added after the seed.
VISIBILITY_MIGRATIONS = {"reports": "0003_savedview_visibility_default"}


def _expected_names(app: str) -> list[str]:
    second = [SECOND_MIGRATIONS[app]] if app in SECOND_MIGRATIONS else []
    seed = [SEED_MIGRATIONS[app]] if app in SEED_MIGRATIONS else []
    change_text = [CHANGE_TEXT_MIGRATIONS[app]] if app in CHANGE_TEXT_MIGRATIONS else []
    visibility = [VISIBILITY_MIGRATIONS[app]] if app in VISIBILITY_MIGRATIONS else []
    return ["0001_initial", *second, *seed, *change_text, *visibility]


def test_every_firebird_app_has_a_real_initial_set() -> None:
    for app in FB_APPS:
        folder = APP_DIR / app / "migrations_fb"
        assert (folder / "__init__.py").is_file(), folder
        expected = [f"{name}.py" for name in _expected_names(app)]
        assert sorted(p.name for p in folder.glob("*.py") if p.name != "__init__.py") == sorted(expected), folder


def test_firebird_sets_have_the_second_migrations() -> None:
    for app, name in [*SECOND_MIGRATIONS.items(), *SEED_MIGRATIONS.items(), *CHANGE_TEXT_MIGRATIONS.items()]:
        assert (APP_DIR / app / "migrations_fb" / f"{name}.py").is_file(), (app, name)
    data = result_of(run_django(LOAD_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH))
    assert data["names"]["employees"] == [
        "0001_initial",
        "0002_history_overlap_guard",
        "0003_seed",
        "0004_activityentry_change_text",
    ]
    assert data["names"]["checklists"] == ["0001_initial", "0002_emulated_unique", "0003_seed"]
    assert data["names"]["assistant"] == ["0001_initial", "0002_seed"]
    assert data["names"]["leave"] == ["0001_initial", "0002_seed"]


def test_assistant_initial_present() -> None:
    folder = APP_DIR / "assistant" / "migrations_fb"
    assert (folder / "__init__.py").is_file(), folder
    assert (folder / "0001_initial.py").is_file(), folder
    assert (folder / "__init__.py").read_bytes() == b""


def test_postgres_mode_keeps_normal_migrations() -> None:
    data = result_of(run_django(PG_CODE, DB_ENGINE="postgres", DATABASE_URL=POSTGRES_URL))
    assert not data["setting"]
    assert data["modules"] == {app: f"{app}.migrations" for app in FB_APPS}  # every app keeps its PostgreSQL history
    assert "0001_initial" in data["accounts"]
    assert "0011_firebird_reserved_columns" in data["accounts"]


def test_each_firebird_initial_has_no_reserved_column() -> None:
    data = result_of(run_django(LOAD_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH))
    for app in FB_APPS:
        assert data["names"][app] == _expected_names(app), (app, data["names"][app])
        assert data["columns"][app], f"{app}: no columns found, the check would pass for nothing"
        reserved = [entry for entry in data["columns"][app] if entry.split(":", 1)[1].upper() in RESERVED_WORDS]
        assert reserved == [], (app, reserved)


def test_makemigrations_check_is_clean_in_firebird_mode(work_copy: str) -> None:
    proc = run_manage(
        ["makemigrations", "--check", "--dry-run", *FB_APPS],
        DB_ENGINE="firebird",
        FIREBIRD_NAME=work_copy,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "No changes detected" in proc.stdout, proc.stdout


def test_no_identifier_over_31_characters_in_any_firebird_initial() -> None:
    data = result_of(run_django(NAMES_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH))
    for app in FB_APPS:
        assert data["models"][app], f"{app}: no models found, the check would pass for nothing"
        long_names = [entry for entry in data["found"][app] if len(entry.split(" ", 1)[1]) > 31]
        assert long_names == [], (app, long_names)
