"""Settings seam: DB_ENGINE picks PostgreSQL (default) or the Firebird backend (plan Task 10a).

The settings tests run Django in a subprocess, so config.settings is imported fresh with the
environment each test sets. No test opens a database connection. The Firebird path is a folder
that does not exist, the PostgreSQL URL is parsed but never used, and the firebird-mode checks
run with databases=["default"] and still pass, which shows no connection was needed. The check
function tests call the functions directly on synthetic model classes.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from django.db import models
from django.test.utils import isolate_apps
from pytest_django.fixtures import SettingsWrapper

APP_DIR = Path(__file__).resolve().parents[2]  # <repo>/app
PROJECT_TIME_ZONE = "Asia/Ulaanbaatar"
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
POSTGRES_URL = "postgres://x:x@127.0.0.1:1/x"  # parsed only; never used for a connection
FIREBIRD_PATH = str(APP_DIR / "no-such-folder" / "clone.fdb")  # a string only; the folder does not exist

SETTINGS_CODE = """
import json
from django.conf import settings
db = {key: value for key, value in settings.DATABASES["default"].items() if key != "PASSWORD"}
data = {
    "db": db,
    "password_set": bool(settings.DATABASES["default"].get("PASSWORD")),
    "prefix": settings.HR_TABLE_PREFIX,
    "installed": list(settings.INSTALLED_APPS),
    "tz": settings.TIME_ZONE,
}
print("RESULT " + json.dumps(data))
"""

ENV_PROBE_CODE = """
import json
from django.conf import settings
matches = settings.DATABASES["default"]["PASSWORD"] == "x-test"
print("RESULT " + json.dumps({"matches": matches}))
"""

PLAIN_CHECK_CODE = """
import json
import django
django.setup()
from django.core.checks import run_checks
print("RESULT " + json.dumps({"ids": sorted({i.id for i in run_checks() if i.id})}))
"""

# Scans the HR-owned models the same way the checks do, runs every check (database checks too),
# and reports what it found. Lists are compared with the messages, never with a hard-coded count.
CHECK_CODE = """
import json
import django
django.setup()
from django.apps import apps
from django.conf import settings
from django.core.checks import run_checks
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.db import models
from io import StringIO

hr_models = [m for m in apps.get_models(include_auto_created=True)
             if m._meta.managed and m._meta.app_label != "macs"]
wide = sorted(f"{m._meta.label}.{f.name}" for m in hr_models for f in m._meta.local_fields
              if isinstance(f, models.DecimalField) and f.max_digits > 9)
big = sorted(f"{m._meta.label}.{f.name}" for m in hr_models for f in m._meta.local_fields
             if isinstance(f, (models.BigIntegerField, models.PositiveBigIntegerField, models.DurationField))
             and not isinstance(f, (models.AutoField, models.BigAutoField, models.SmallAutoField)))
issues = run_checks(databases=["default"])
silenced = [i.id for i in issues if i.id in settings.SILENCED_SYSTEM_CHECKS]
check_raised = False
try:
    call_command("check", databases=["default"], stdout=StringIO(), stderr=StringIO())
except SystemCheckError:
    check_raised = True
print("RESULT " + json.dumps({
    "wide": wide,
    "big": big,
    "w001": [i.msg for i in issues if i.id == "infohr_firebird.W001"],
    "w002": [i.msg for i in issues if i.id == "infohr_firebird.W002"],
    "ids": sorted({i.id for i in issues if i.id}),
    "errors": [f"{i.id} {i.msg}" for i in issues if i.is_serious() and i.id not in settings.SILENCED_SYSTEM_CHECKS],
    "silenced": sorted(set(silenced)),
    "silenced_count": len(silenced),
    "check_raised": check_raised,
}))
"""


def run_django(code: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    """Run code in a fresh interpreter with the seam variables cleared, then set the overrides."""
    env = {key: value for key, value in os.environ.items() if key not in SEAM_VARS}
    env.update({"DJANGO_SETTINGS_MODULE": "config.settings", "PYTHONPATH": str(APP_DIR)})
    env.update(overrides)
    return subprocess.run(  # noqa: S603 (fixed argv, our own code string)
        [sys.executable, "-B", "-c", code],
        env=env,
        cwd=str(APP_DIR),
        capture_output=True,
        text=True,
        check=False,
    )


def result_of(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    lines = [line for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
    assert proc.returncode == 0 and len(lines) == 1, proc.stdout + proc.stderr
    loaded: dict[str, Any] = json.loads(lines[0][len("RESULT ") :])
    return loaded


def test_firebird_settings() -> None:
    data = result_of(run_django(SETTINGS_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH))
    db = data["db"]
    assert db["ENGINE"] == "infohr_firebird"
    assert db["NAME"] == FIREBIRD_PATH
    assert db["USER"] == "SYSDBA"
    assert db["HOST"] == "" and db["PORT"] == ""
    assert data["password_set"] is False
    assert db["TIME_ZONE"] == PROJECT_TIME_ZONE
    assert db["OPTIONS"] == {"charset": "UTF8", "lock_timeout": 3}
    assert data["prefix"] == "IHR_"
    assert data["tz"] == PROJECT_TIME_ZONE
    assert "infohr_firebird" in data["installed"]
    assert "django.contrib.postgres" not in data["installed"]


CLIENT_LIBRARY = r"C:\Tools\Firebird\fbclient.dll"  # a path string only; the file is never loaded here


def test_firebird_client_library_and_dialect_from_environment() -> None:
    data = result_of(
        run_django(
            SETTINGS_CODE,
            DB_ENGINE="firebird",
            FIREBIRD_NAME=FIREBIRD_PATH,
            FIREBIRD_CLIENT_LIBRARY=CLIENT_LIBRARY,
            FIREBIRD_DIALECT="1",
        )
    )
    assert data["db"]["OPTIONS"] == {
        "charset": "UTF8",
        "lock_timeout": 3,
        "fb_client_library": CLIENT_LIBRARY,
        "sql_dialect": 1,
    }


def test_firebird_driver_options_absent_when_not_set() -> None:
    # SEAM_VARS clears the two variables, so the defaults apply: only charset and lock_timeout
    data = result_of(run_django(SETTINGS_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH))
    assert data["db"]["OPTIONS"] == {"charset": "UTF8", "lock_timeout": 3}


def test_postgres_ignores_firebird_driver_settings() -> None:
    data = result_of(
        run_django(
            SETTINGS_CODE,
            DB_ENGINE="postgres",
            DATABASE_URL=POSTGRES_URL,
            FIREBIRD_CLIENT_LIBRARY=CLIENT_LIBRARY,
            FIREBIRD_DIALECT="1",
        )
    )
    assert data["db"]["OPTIONS"] == {"options": "-c search_path=hr,public"}


def test_firebird_requires_no_database_url_and_needs_a_name() -> None:
    proc = run_django(SETTINGS_CODE, DB_ENGINE="firebird")  # no FIREBIRD_NAME, no DATABASE_URL
    assert proc.returncode != 0
    assert "FIREBIRD_NAME" in proc.stderr


def test_database_url_is_ignored_in_firebird_mode() -> None:
    data = result_of(
        run_django(SETTINGS_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH, DATABASE_URL="bogus://nowhere")
    )
    assert data["db"]["ENGINE"] == "infohr_firebird"


def test_firebird_password_comes_from_environment() -> None:
    data = result_of(
        run_django(ENV_PROBE_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH, FIREBIRD_PASSWORD="x-test")  # noqa: S106 (dummy value)
    )
    assert data["matches"] is True


def test_postgres_default_unchanged() -> None:
    data = result_of(run_django(SETTINGS_CODE, DB_ENGINE="postgres", DATABASE_URL=POSTGRES_URL))
    db = data["db"]
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert db["OPTIONS"] == {"options": "-c search_path=hr,public"}
    assert data["prefix"] == ""
    assert "django.contrib.postgres" in data["installed"]
    assert "infohr_firebird" not in data["installed"]


def test_unknown_engine_is_a_clear_error() -> None:
    proc = run_django(SETTINGS_CODE, DB_ENGINE="oracle", DATABASE_URL=POSTGRES_URL)
    assert proc.returncode != 0
    assert "ImproperlyConfigured" in proc.stderr
    assert "DB_ENGINE" in proc.stderr and "oracle" in proc.stderr


def test_env_prefix_override_still_works() -> None:
    data = result_of(
        run_django(SETTINGS_CODE, DB_ENGINE="postgres", DATABASE_URL=POSTGRES_URL, DJANGO_HR_TABLE_PREFIX="IHR_")
    )
    assert data["prefix"] == "IHR_"


def test_check_reports_wide_decimals_and_big_integers() -> None:
    data = result_of(run_django(CHECK_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH))
    # the scan and the W001/W002 messages name exactly the same fields (both lists may be empty)
    assert sorted(msg.split(" is a ")[0] for msg in data["w001"]) == data["wide"], data["w001"]
    assert sorted(msg.split(" is a ")[0] for msg in data["w002"]) == data["big"], data["w002"]
    # no E001 and no fields.E180 error; check does not raise SystemCheckError
    assert data["errors"] == [], data["errors"]
    assert data["check_raised"] is False


def test_e001_when_prefix_empty() -> None:
    data = result_of(
        run_django(CHECK_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH, DJANGO_HR_TABLE_PREFIX="")
    )
    assert "infohr_firebird.E001" in [error.split(" ", 1)[0] for error in data["errors"]], data["errors"]
    assert data["check_raised"] is True


def test_postgres_mode_has_no_firebird_checks() -> None:
    data = result_of(run_django(PLAIN_CHECK_CODE, DB_ENGINE="postgres", DATABASE_URL=POSTGRES_URL))
    assert [i for i in data["ids"] if i.startswith("infohr_firebird.")] == []


def test_w001_flags_only_hr_decimals_wider_than_nine_digits() -> None:
    from infohr_firebird.checks import wide_decimal_messages

    with isolate_apps():

        class Wide(models.Model):  # noqa: DJ008 (test model, no __str__ needed)
            amount = models.DecimalField(max_digits=14, decimal_places=2)

            class Meta:
                app_label = "leave"

        class Narrow(models.Model):  # noqa: DJ008
            amount = models.DecimalField(max_digits=9, decimal_places=2)

            class Meta:
                app_label = "leave"

        class MacsWide(models.Model):  # noqa: DJ008
            amount = models.DecimalField(max_digits=15, decimal_places=2)

            class Meta:
                app_label = "macs"

        class LegacyWide(models.Model):  # noqa: DJ008
            amount = models.DecimalField(max_digits=15, decimal_places=2)

            class Meta:
                app_label = "leave"
                managed = False

        messages = wide_decimal_messages([Wide, Narrow, MacsWide, LegacyWide])
    assert [m.id for m in messages] == ["infohr_firebird.W001"]
    assert messages[0].msg.startswith("leave.Wide.amount is a DecimalField with max_digits=14")


def test_w002_flags_bigint_and_duration_only() -> None:
    from infohr_firebird.checks import big_integer_messages

    with isolate_apps():

        class WithBig(models.Model):  # noqa: DJ008
            value = models.BigIntegerField()

            class Meta:
                app_label = "leave"

        class WithDuration(models.Model):  # noqa: DJ008
            span = models.DurationField()

            class Meta:
                app_label = "leave"

        class WithBigPk(models.Model):  # noqa: DJ008
            id = models.BigAutoField(primary_key=True)

            class Meta:
                app_label = "leave"

        class Plain(models.Model):  # noqa: DJ008
            n = models.IntegerField()

            class Meta:
                app_label = "leave"

        messages = big_integer_messages([WithBig, WithDuration, WithBigPk, Plain])
    assert [m.id for m in messages] == ["infohr_firebird.W002", "infohr_firebird.W002"]
    hints = {m.msg.split(" is a ")[0]: str(m.hint) for m in messages}
    assert sorted(hints) == ["leave.WithBig.value", "leave.WithDuration.span"]
    assert "2,147,483,647" in hints["leave.WithBig.value"]
    assert "no BIGINT" in hints["leave.WithDuration.span"]
    assert "stored as a 32-bit INTEGER" not in hints["leave.WithDuration.span"]


def test_checks_do_nothing_outside_firebird(settings: SettingsWrapper, monkeypatch: pytest.MonkeyPatch) -> None:
    from django.apps import apps

    from infohr_firebird import checks

    engine = settings.DATABASES["default"]
    monkeypatch.setitem(engine, "ENGINE", "django.db.backends.postgresql")
    assert checks.check_wide_decimals(None) == []
    assert checks.check_big_integers(None) == []
    assert checks.check_table_prefix(None) == []

    # with the firebird engine, the wired checks report exactly what the pure functions report
    monkeypatch.setitem(engine, "ENGINE", "infohr_firebird")
    models_ = apps.get_models(include_auto_created=True)
    assert [m.msg for m in checks.check_wide_decimals(None)] == [m.msg for m in checks.wide_decimal_messages(models_)]
    assert [m.msg for m in checks.check_big_integers(None)] == [m.msg for m in checks.big_integer_messages(models_)]
