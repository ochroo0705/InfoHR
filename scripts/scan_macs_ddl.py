"""Scan: Info HR must never change the structure (DDL) of a production MACS table (D-017).

Run from the app/ folder:
    ..\\.venv\\Scripts\\python.exe ..\\scripts\\scan_macs_ddl.py          # static checks, no database needed
    ..\\.venv\\Scripts\\python.exe ..\\scripts\\scan_macs_ddl.py --live   # also asks the database

Row writes into production tables are allowed (only the write layers in
tests_guard/test_writes.py may do them). This scan is about table STRUCTURE.

Static checks
  1. Every model of the `macs` app is managed = False (Django never creates/alters it).
  2. No HR-owned (managed) model uses a table name that a macs model uses.
  3. Every migration of every app: RunSQL / RunPython are read for DDL that names a
     production table; schema operations aimed at a macs model are listed.
  4. The models and migration files agree (nothing pending).
Live checks (--live)
  5. Production tables (schema public) are not owned by the HR database role, and the
     role is not a superuser - so Postgres itself would refuse an ALTER/DROP.
  6. HR tables live in schema `hr`, none in `public`.
Exit code 0 = clean, 1 = at least one FAIL.
"""

import inspect
import os
import re
import sys

sys.path.insert(0, ".")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection, migrations  # noqa: E402
from django.db.migrations.loader import MigrationLoader  # noqa: E402

DDL = re.compile(r"\b(alter|drop|create|truncate|rename|comment\s+on|grant|revoke)\b", re.I)
fails: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    fails.append(msg)
    print(f"  FAIL  {msg}")


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


macs_models = [m for m in apps.get_app_config("macs").get_models(include_auto_created=True)]
macs_tables = {m._meta.db_table for m in macs_models}

print("1. macs models are unmanaged")
managed = [m._meta.label for m in macs_models if m._meta.managed]
for lbl in managed:
    fail(f"{lbl} is managed=True: Django would create/alter its table")
if not managed:
    ok(f"{len(macs_models)} macs models, all managed=False")

print("2. HR models never reuse a production table name")
clash = sorted(
    m._meta.label
    for m in apps.get_models()
    if m._meta.app_label != "macs" and m._meta.managed and m._meta.db_table in macs_tables
)
for lbl in clash:
    fail(f"{lbl} is managed and uses a production table name")
if not clash:
    ok("no name clash")

print("3. migrations")
loader = MigrationLoader(None, ignore_no_migrations=True)
n_mig = 0
review: list[str] = []
for (app, name), mig in sorted(loader.disk_migrations.items()):
    n_mig += 1
    for op in mig.operations:
        where = f"{app}.{name}"
        if isinstance(op, migrations.RunSQL):
            stmts = op.sql if isinstance(op.sql, (list, tuple)) else [op.sql]
            text = " ".join(s if isinstance(s, str) else str(s[0]) for s in stmts)
            hit = [t for t in macs_tables if re.search(rf"\b{re.escape(t)}\b", text, re.I)]
            if hit and DDL.search(text):
                fail(f"{where}: RunSQL with DDL naming production table(s) {sorted(hit)}")
            elif hit:
                review.append(f"{where}: RunSQL mentions {sorted(hit)} (no DDL keyword)")
        elif isinstance(op, migrations.RunPython):
            src = ""
            for fn in (op.code, op.reverse_code):
                if callable(fn):
                    try:
                        src += inspect.getsource(fn)
                    except (OSError, TypeError):
                        pass
            if re.search(r"schema_editor\.(execute|alter|add|remove|delete|create)|cursor\(\)", src):
                hit = [t for t in macs_tables if re.search(rf"\b{re.escape(t)}\b", src)]
                if hit:
                    fail(f"{where}: RunPython raw schema/cursor code naming production table(s) {sorted(hit)}")
                else:
                    review.append(f"{where}: RunPython uses schema_editor/cursor - read it")
        elif isinstance(op, (migrations.CreateModel, migrations.DeleteModel, migrations.RenameModel)):
            model = op.name.lower()
            if app != "macs" and any(m._meta.model_name == model and m._meta.app_label == app for m in macs_models):
                fail(f"{where}: {type(op).__name__} {op.name} on a macs model outside the macs app")
        elif isinstance(op, migrations.AlterModelOptions) and app == "macs":
            if op.options.get("managed") is True:
                fail(f"{where}: sets managed=True on macs model {op.name}")
    if app == "macs":
        for op in mig.operations:
            if isinstance(op, migrations.CreateModel) and op.options.get("managed", True) is not False:
                fail(f"{app}.{name}: CreateModel {op.name} without managed=False")
ok(f"{n_mig} migrations read")
for r in review:
    print(f"  note  {r}")

print("4. nothing pending (models == migrations, read from files, not the database)")
from django.db.migrations.autodetector import MigrationAutodetector  # noqa: E402
from django.db.migrations.state import ProjectState  # noqa: E402

changes = MigrationAutodetector(loader.project_state(), ProjectState.from_apps(apps)).changes(graph=loader.graph)
if changes:
    for app, migs in changes.items():
        for m in migs:
            ops = [type(o).__name__ for o in m.operations][:6]
            if app == "macs":
                fail(f"macs: models differ from migrations {ops}")
            else:
                print(f"  note  {app}: models differ from migrations {ops} (not a production table; review before migrating)")
    if "macs" not in changes:
        ok("macs models match their migrations")
else:
    ok("no pending model changes")

if "--live" in sys.argv:
    print("5. database role cannot alter production tables")
    try:
        with connection.cursor() as c:
            c.execute("select current_user, rolsuper from pg_roles where rolname=current_user")
            user, is_super = c.fetchone()
            if is_super:
                fail(f"role {user} is a SUPERUSER: it can alter any table")
            c.execute(
                "select tablename from pg_tables where schemaname='public' and tableowner=current_user"
            )
            owned = [r[0] for r in c.fetchall()]
            if owned:
                fail(f"role {user} OWNS {len(owned)} production tables (can ALTER/DROP): {owned[:8]}...")
            elif not is_super:
                c.execute("select count(*) from pg_tables where schemaname='public'")
                n_pub = c.fetchone()[0]
                if n_pub == 0:
                    print(f"  note  database {connection.settings_dict['NAME']} has NO public tables: this check proves nothing here, run it against the MACS-connected database")
                else:
                    ok(f"role {user} owns none of the {n_pub} public tables and is not superuser")
            c.execute("select app, name from django_migrations")
            applied = {(r[0], r[1]) for r in c.fetchall()}
            gone = [k for k in loader.disk_migrations if k not in applied and k[0] == "macs"]
            if gone:
                print(f"  note  {len(gone)} macs migrations are not recorded as applied (state-only, no DDL; "
                      "makemigrations/migrate will complain about history order)")
            print("6. HR tables live in schema hr")
            hr = {m._meta.db_table for m in apps.get_models() if m._meta.managed and m._meta.app_label != "macs"}
            c.execute("select tablename from pg_tables where schemaname='public'")
            stray = sorted(hr & {r[0] for r in c.fetchall()})
            for t in stray:
                fail(f"HR table {t} exists in schema public")
            if not stray:
                ok("no HR table in public")
    except Exception as exc:  # noqa: BLE001
        fail(f"live check could not run: {exc}")
else:
    print("5-6. live checks skipped (use --live)")

print()
print("RESULT:", "FAIL" if fails else "PASS", f"({len(fails)} fail)")
sys.exit(1 if fails else 0)
