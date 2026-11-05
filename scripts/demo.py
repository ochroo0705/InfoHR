"""The one HR database, `info_hr_demo`, filled with Mongolian demo data (the project's only database since 2026-11-03).

Usage (from the repo root, venv active):
    python scripts/demo.py reset                # drop + create info_hr_demo, migrate, seed_demo
    python scripts/demo.py run                  # runserver on http://localhost:8001 against info_hr_demo
    python scripts/demo.py assistant-data       # add the help assistant's Mongolian demo staff (idempotent)

`assistant-data` runs `seed_assistant_demo`, which checks PostgreSQL, DEBUG and the info_hr_demo* name itself.
There is no removal (the activity log is append-only). To start over: `python scripts/demo.py reset`, then
`python scripts/demo.py assistant-data`.

`.env` DATABASE_URL points at the same database, so `manage.py` and the tests (test_info_hr_demo) use it too.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DB = os.environ.get("DEMO_DB", "info_hr_demo")  # e.g. info_hr_demo_scale for the 300-person check
PORT = os.environ.get("PORT", "8001")  # the preview tool may assign another port


def manage(*args: str) -> None:
    env = {**os.environ, "DJANGO_DB_NAME": DEMO_DB, "DJANGO_DEBUG": "true", "PYTHONIOENCODING": "utf-8"}
    subprocess.run([sys.executable, str(ROOT / "app" / "manage.py"), *args], env=env, check=True)  # noqa: S603


def reset() -> None:
    sys.path.insert(0, str(ROOT / "app"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    from django.conf import settings

    django.setup()
    import psycopg

    db = settings.DATABASES["default"]
    # Connect to the maintenance database to drop/create the demo one (the app role has CREATEDB and owns it);
    # it cannot drop the database it is connected to.
    with psycopg.connect(
        host=db["HOST"],
        port=db["PORT"] or 5432,
        dbname="postgres",
        user=db["USER"],
        password=db["PASSWORD"],
        autocommit=True,
    ) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{DEMO_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{DEMO_DB}"')
    # Production MACS structure first (the HR app writes these tables), then the HR schema and grants.
    schema = (ROOT / "db" / "schema" / "macs_public.sql").read_text(encoding="utf-8")
    grants = (ROOT / "scripts" / "grant_macs_pg.sql").read_text(encoding="utf-8")
    with psycopg.connect(
        host=db["HOST"],
        port=db["PORT"] or 5432,
        dbname=DEMO_DB,
        user=db["USER"],
        password=db["PASSWORD"],
        autocommit=True,
    ) as conn:
        conn.execute(schema)
        conn.execute("create schema if not exists hr")
        conn.execute(grants)
    manage("migrate", "-v", "0")
    manage("seed_demo")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "reset":
        reset()
    elif command == "run":
        manage("runserver", PORT)
    elif command == "assistant-data":
        manage("seed_assistant_demo")
    else:
        print(__doc__)
        sys.exit(1)
