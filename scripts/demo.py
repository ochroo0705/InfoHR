"""Demo database helper: a separate database `info_hr_demo` filled with Mongolian demo data.

Usage (from the repo root, venv active):
    python scripts/demo.py reset   # drop + create info_hr_demo, migrate, seed_demo
    python scripts/demo.py run     # runserver on http://localhost:8001 against info_hr_demo

Your real dev database (info_hr) is never touched.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DB = "info_hr_demo"
PORT = "8001"


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
    # Connect to the main database to drop/create the demo one (the app role has CREATEDB and owns it).
    with psycopg.connect(
        host=db["HOST"],
        port=db["PORT"] or 5432,
        dbname=db["NAME"],
        user=db["USER"],
        password=db["PASSWORD"],
        autocommit=True,
    ) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{DEMO_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{DEMO_DB}"')
    manage("migrate", "-v", "0")
    manage("seed_demo")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "reset":
        reset()
    elif command == "run":
        manage("runserver", PORT)
    else:
        print(__doc__)
        sys.exit(1)
