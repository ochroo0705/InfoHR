"""fb_guard grants (plan 5, tasks 2 and 3): the GRANT script for the limited Firebird runtime user.

The first part (task 2) reads the printed statements only; no database is touched and the subprocess runs use a
path that does not exist.

The second part (task 3) runs the real HR write paths as the limited user on a migrated scratch copy of the
template (migrated_clone). The steps, in order:
  1. snapshot the existing objects with fb_guard (as SYSDBA);
  2. apply the output of `fb_guard grants --user SCRATCH5RT` to the copy as SYSDBA (the statements are executed
     one by one, then committed);
  3. run the work in a subprocess with FB_RUNTIME_USER=SCRATCH5RT, so the connection is made by that name;
  4. verify the snapshot again (fb_guard verify).

Limit of this machine (docs/migration/runtime-user-spike.md): CREATE USER is refused, and local file-path
connections accept any user name and any password. SCRATCH5RT is therefore a name that the grants are issued to,
not a password-protected login. The privilege checks are proven by name; password enforcement is NOT proven here.
No password is written in this module: the runtime password variable is read from the environment and is empty
when unset.
"""

import os
import re
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from infohr_firebird.management.commands.fb_guard import SPIKE_MACS_TABLES, UNPROVEN_TABLES, Command
from infohr_firebird.tests.test_migrations_fb import run_manage
from infohr_firebird.tests.test_settings_seam import APP_DIR, FIREBIRD_PATH, result_of, run_django

USER = "MACS_HR_RT"

# Runs inside a fresh interpreter with the Firebird settings. It also reports the table and generator
# names the models give (through the backend's own naming), so the test does not trust the command's output alone.
GRANTS_CODE = """
import json
import django
django.setup()
from io import StringIO
from django.apps import apps
from django.core.management import call_command
from django.db import connections
from infohr_firebird.operations import get_autoinc_sequence_name
out = StringIO()
call_command("fb_guard", "grants", "--user", __USER__, stdout=out)
ops = connections["default"].ops
models = [m for m in apps.get_models(include_auto_created=True)
          if m._meta.managed and not m._meta.proxy and m._meta.app_label != "macs"]
tables = sorted({ops.quote_name(m._meta.db_table) for m in models})
sequences = sorted({get_autoinc_sequence_name(ops, m._meta.db_table) for m in models if m._meta.auto_field is not None})
unmanaged = sorted({ops.quote_name(m._meta.db_table) for m in apps.get_models(include_auto_created=True)
                    if not m._meta.managed and not m._meta.proxy})
print("RESULT " + json.dumps({"out": out.getvalue(), "tables": tables, "sequences": sequences, "unmanaged": unmanaged}))
"""


def _grants_run(user: str) -> dict[str, Any]:
    proc = run_django(
        GRANTS_CODE.replace("__USER__", repr(user)),
        DB_ENGINE="firebird",
        FIREBIRD_NAME=FIREBIRD_PATH,
    )
    return result_of(proc)


# HR tables that get less than full rights (HR_TABLE_RIGHTS in fb_guard): their rights are tested exactly below.
RESTRICTED_TABLES = frozenset(
    {
        "IHR_ACCOUNTS_SYSTEMLOGENTRY",
        "IHR_EMPLOYEES_ACTIVITYENTRY",
        "IHR_DJANGO_ADMIN_LOG",
        "IHR_AUTH_PERMISSION",
        "IHR_DJANGO_CONTENT_TYPE",
        "IHR_ACCOUNTS_USER_GROUPS",
        "IHR_AUTH_GROUP_PERMISSIONS",
    }
)


def test_grants_script_covers_every_hr_table() -> None:
    data = _grants_run(USER)
    lines = set(str(data["out"]).splitlines())
    tables = list(data["tables"])
    assert tables, "the models gave no HR tables"
    assert all(table.startswith("IHR_") for table in tables)
    assert "IHR_ACCOUNTS_USER" in tables
    assert "IHR_EMPLOYEES_EVENT" in tables
    for table in tables:
        if table in RESTRICTED_TABLES:
            continue  # checked exactly, with their own rights, below
        assert f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {USER};" in lines, table
    for sequence in data["sequences"]:
        assert f"GRANT USAGE ON SEQUENCE {sequence} TO {USER};" in lines, sequence


def test_grants_macs_exceptions_and_generators_from_spike() -> None:
    lines = set(str(_grants_run(USER)["out"]).splitlines())
    assert f"GRANT USAGE ON EXCEPTION CANNOT_CHANGE_CUSTID TO {USER};" in lines
    assert f"GRANT USAGE ON EXCEPTION IHR_HISTORY_OVERLAP TO {USER};" in lines
    assert f"GRANT SELECT, INSERT, UPDATE ON CUSTOMER TO {USER};" in lines
    assert f"GRANT SELECT, INSERT, DELETE ON MOVEMENT TO {USER};" in lines
    assert f"GRANT USAGE ON SEQUENCE GEN_EMPLOYEEID TO {USER};" in lines


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "lower_case",
        "1STARTS_WITH_DIGIT",
        "HAS SPACE",
        "BAD;DROP",
        "BAD-NAME",
        "A" * 32,
        # Firebird keywords and built-in names: a grant to PUBLIC would give every login the rights.
        "PUBLIC",
        "SYSDBA",
        "SYSTEM",
        "RDB$ADMIN",
        "RDB$FOO",
    ],
)
def test_grants_refuses_a_bad_user_name(bad_name: str) -> None:
    with pytest.raises(CommandError, match="user name"):
        call_command(Command(), "grants", "--user", bad_name, stdout=StringIO())


def test_grants_never_grant_alter_or_drop() -> None:
    out = str(_grants_run(USER)["out"])
    statements = [line for line in out.splitlines() if line.startswith("GRANT ")]
    assert len(statements) > 100
    allowed = {"SELECT", "INSERT", "UPDATE", "DELETE", "USAGE"}
    for line in statements:
        match = re.fullmatch(r"GRANT (.+?) ON (?:SEQUENCE |EXCEPTION )?\S+ TO \S+;", line)
        assert match is not None, line
        rights_text = match.group(1)
        if "(" in rights_text:  # the column-level form: UPDATE on one named column, nothing else
            assert re.fullmatch(r"UPDATE \([A-Z0-9_$]+\)", rights_text), line
            rights_text = "UPDATE"
        rights = {right.strip() for right in rights_text.split(",")}
        assert rights <= allowed, line
        assert "REFERENCES" not in line, line


def _table_statements(out: str, table: str) -> list[str]:
    """GRANT statements on table for the test user, table-wide and column-level alike."""
    return [line for line in out.splitlines() if line.endswith(f" ON {table} TO {USER};")]


def _rights_on(out: str, table: str) -> set[str]:
    """The table-wide rights of table. Fails when there is no such statement or more than one."""
    found = [line for line in _table_statements(out, table) if "(" not in line]
    assert len(found) == 1, (table, found)
    rights = found[0][len("GRANT ") : found[0].index(" ON ")]
    return {right.strip() for right in rights.split(",")}


def _column_grants(out: str, table: str) -> list[str]:
    """The column-level GRANT statements on table, in script order."""
    return [line for line in _table_statements(out, table) if "(" in line]


APPEND_ONLY_TABLES = ("IHR_ACCOUNTS_SYSTEMLOGENTRY", "IHR_EMPLOYEES_ACTIVITYENTRY", "IHR_DJANGO_ADMIN_LOG")


def test_append_only_tables_never_get_update_or_delete() -> None:
    out = str(_grants_run(USER)["out"])
    for table in APPEND_ONLY_TABLES:
        # Log screens and the admin history read these, and the app inserts; nothing else.
        assert _rights_on(out, table) == {"SELECT", "INSERT"}, table


def test_per_table_rights_follow_the_rulings() -> None:
    out = str(_grants_run(USER)["out"])
    assert _rights_on(out, "IHR_AUTH_PERMISSION") == {"SELECT"}
    assert _rights_on(out, "IHR_DJANGO_CONTENT_TYPE") == {"SELECT"}
    assert _rights_on(out, "IHR_DJANGO_SESSION") == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert _rights_on(out, "IHR_AUTH_GROUP") == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert _rights_on(out, "IHR_AUTH_GROUP_PERMISSIONS") == {"SELECT", "INSERT", "DELETE"}
    assert _rights_on(out, "IHR_ACCOUNTS_USER_GROUPS") == {"SELECT", "INSERT", "DELETE"}
    assert _rights_on(out, "COMMAND") == {"SELECT", "INSERT", "UPDATE"}
    assert _rights_on(out, "NAZG") == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert f"GRANT USAGE ON SEQUENCE GEN_COMMAND_ID TO {USER};" in out.splitlines()
    assert f"GRANT USAGE ON SEQUENCE GEN_NAZG_ID TO {USER};" in out.splitlines()


def test_audit_logs_update_only_the_user_column() -> None:
    out = str(_grants_run(USER)["out"])
    # Deleting a user sets its reference to NULL: that one column, never the whole table.
    assert _column_grants(out, "IHR_ACCOUNTS_SYSTEMLOGENTRY") == [
        f"GRANT UPDATE (ACTOR_ID) ON IHR_ACCOUNTS_SYSTEMLOGENTRY TO {USER};"
    ]
    assert _column_grants(out, "IHR_EMPLOYEES_ACTIVITYENTRY") == [
        f"GRANT UPDATE (BY_ID) ON IHR_EMPLOYEES_ACTIVITYENTRY TO {USER};"
    ]
    assert _rights_on(out, "IHR_ACCOUNTS_SYSTEMLOGENTRY") == {"SELECT", "INSERT"}
    assert _rights_on(out, "IHR_EMPLOYEES_ACTIVITYENTRY") == {"SELECT", "INSERT"}
    assert _column_grants(out, "IHR_DJANGO_ADMIN_LOG") == []


GUARD_CODE = """
import json
import django
django.setup()
from io import StringIO
from django.core.management import call_command
from django.core.management.base import CommandError
from infohr_firebird.management.commands import fb_guard
fb_guard.__DICT__[__KEY__] = __VALUE__
message = ""
try:
    call_command("fb_guard", "grants", "--user", "MACS_HR_RT", stdout=StringIO())
except CommandError as exc:
    message = str(exc)
print("RESULT " + json.dumps({"message": message}))
"""


@pytest.mark.parametrize(
    ("dict_name", "key", "value", "expected"),
    [
        ("HR_TABLE_RIGHTS", "nosuch.model", "SELECT", "names no HR model: nosuch.model"),
        ("HR_COLUMN_UPDATE", "nosuch.model", "actor", "names no HR model: nosuch.model"),
        ("HR_COLUMN_UPDATE", "accounts.systemlogentry", "no_such_field", "has no field no_such_field"),
    ],
)
def test_unknown_override_is_refused(dict_name: str, key: str, value: str, expected: str) -> None:
    code = GUARD_CODE.replace("__DICT__", dict_name).replace("__KEY__", repr(key)).replace("__VALUE__", repr(value))
    proc = run_django(code, DB_ENGINE="firebird", FIREBIRD_NAME=FIREBIRD_PATH)
    message = str(result_of(proc)["message"])
    assert expected in message, message


def test_committed_script_equals_command_output() -> None:
    committed = (APP_DIR.parent / "scripts" / "grant_macs_fb.sql").read_text(encoding="utf-8")
    assert str(_grants_run(USER)["out"]) == committed


# ---- Task 3: the limited user runs the write paths (see the module docstring for the steps) ----

RUNTIME_USER = "SCRATCH5RT"  # a throwaway name for the scratch copy; no password is written anywhere

# SYSDBA: prints the grant script for RUNTIME_USER, executes its GRANT statements against the copy, then commits.
# The comment lines and the closing COMMIT in the script are not executed; the commit is done once here.
GRANT_AS_SYSDBA_CODE = """
import json
import django
django.setup()
from io import StringIO
from django.core.management import call_command
from django.db import connection
out = StringIO()
call_command("fb_guard", "grants", "--user", __USER__, stdout=out)
statements = [line.rstrip(";") for line in out.getvalue().splitlines() if line.startswith("GRANT ")]
with connection.cursor() as cursor:
    for statement in statements:
        cursor.execute(statement)
connection.commit()
print("RESULT " + json.dumps({"applied": len(statements)}))
"""


def _guarded(body: str) -> str:
    """Wrap a subprocess body so that a failure is printed as a RESULT line (JSON, ASCII-escaped).

    run_django reads stderr as cp1252, so a traceback with Cyrillic text would crash the reader; the message is
    passed on stdout instead, where json.dumps keeps it readable and safe."""
    indented = "\n".join(("    " + line) if line else line for line in body.splitlines())
    return (
        "import json\ntry:\n" + indented + "\nexcept Exception as exc:\n"
        '    print("RESULT " + json.dumps({"error": type(exc).__name__ + ": " + str(exc)}))\n'
    )


# The HR write paths, through the real services, as RUNTIME_USER. Each step runs in order; the first Firebird
# refusal ends the run and its text is reported in "error".
WRITES_AS_RUNTIME_USER_CODE = _guarded("""
import secrets
import uuid
import datetime as dt
from decimal import Decimal
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from employees.models import ContractType, Employee, EmployeeType, Event, EventType, HrOrder, JobStatus
from employees.services import events, history, personal_rows, personal_writes
from leave.models import LeaveAssign
from leave.services import records
from leave.services.writes import save_leave_type
from macs.models import Branch, City, Command, ContactType, Department, District, FamilyRelation, Position

User = get_user_model()
capture = CaptureQueriesContext(connection)
capture.__enter__()  # records every statement the app sends in this run, for the rights list below
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"rt_{tag}", password=secrets.token_urlsafe(16))
HIRE = dt.date(2026, 1, 5)
MOVE_NOW = dt.date(2026, 3, 2)
MOVE_LATER = dt.date(2035, 3, 1)
LEAVE_START = dt.date(2027, 2, 1)
LEAVE_END = dt.date(2027, 2, 2)
today = timezone.localdate()
dep1, dep2 = list(Department.objects.order_by("pk").values_list("pk", flat=True)[:2])
pos1 = Position.objects.order_by("pk").values_list("pk", flat=True).first()
br1 = Branch.objects.order_by("pk").values_list("pk", flat=True).first()
city = City.objects.order_by("pk").first()
district = District.objects.filter(city=city).order_by("pk").first()
if not ContactType.objects.filter(pk=4).exists():
    ContactType.objects.create(pk=4, name="Имэйл")
values = {
    "family_name": "Тест",
    "given_name": f"Рт{tag}",
    "gender": "M",
    "birth_date": dt.date(1990, 5, 17),
    "register_no": f"УБ90{int(tag, 16) % 1000000:06d}",
    "first_hire_date": HIRE,
    "work_conditions": 1,
    "branch_id": br1,
    "department_id": dep1,
    "position_id": pos1,
}

# 1. Hire: job, salary, an address, a contact of type 4, and an HR order that is registered (writes COMMAND).
emp = history.hire(
    values, {}, start=HIRE,
    job={
        "position_id": pos1, "department_id": dep1, "employee_type": EmployeeType.FULL_TIME,
        "status": JobStatus.ACTIVE, "contract_type": ContractType.OPEN_ENDED,
    },
    salary=Decimal("1500000.00"), by=by,
    address={"street": "Баянзүрх, 5-р хороо", "city_id": city.pk, "district_id": district.pk},
    contact={"contact_type_id": 4, "value": "mail@example.mn", "name": "Дорж", "relative": "Ах"},
    order_number=f"T{tag[:5]}H", order_date=HIRE, order_summary="t5 hire", order_issued_by="t5",
)
hire_department = history.job_on(emp, HIRE).department_id
hire_salary = str(history.salary_on(emp, HIRE).base_salary)

# 2. Department move: recorded with its registered order, then applied the way a signed order is (apply_waiting).
move_now = events.record(
    Employee.objects.get(pk=emp.pk), type=EventType.TRANSFER, effective=MOVE_NOW,
    changes={"department": Department.objects.get(pk=dep2)}, salary=None, reason="t5 move", note="t5", by=by,
    order_number=f"T{tag[:5]}M1", order_date=MOVE_NOW, order_summary="t5 move", order_issued_by="t5",
)
events.apply_waiting(Event.objects.get(pk=move_now.pk), by=by)
department_after_move = history.job_on(Employee.objects.get(pk=emp.pk), MOVE_NOW).department_id

# 3. A second department move, dated in 2035 (scheduled once applied), then cancelled. It is recorded after the
# first one is applied, so the department it changes from is dep2.
later = events.record(
    Employee.objects.get(pk=emp.pk), type=EventType.TRANSFER, effective=MOVE_LATER,
    changes={"department": Department.objects.get(pk=dep1)}, salary=None, reason="t5 later", note="t5", by=by,
    order_number=f"T{tag[:5]}M2", order_date=MOVE_LATER, order_summary="t5 later", order_issued_by="t5",
)
events.apply_waiting(Event.objects.get(pk=later.pk), by=by)
department_2035_before_cancel = history.job_on(Employee.objects.get(pk=emp.pk), MOVE_LATER).department_id
events.cancel(Event.objects.get(pk=later.pk), reason="t5 cancel", by=by)
department_2035_after_cancel = history.job_on(Employee.objects.get(pk=emp.pk), MOVE_LATER).department_id

# 4. A personal-list write: one family member (FAMILY), beside the contact and the address from the hire.
relation = FamilyRelation.objects.order_by("pk").first()
personal_writes.add(
    "family", Employee.objects.get(pk=emp.pk),
    {
        "relation_id": relation.pk, "given_name": "Ээж", "surname": "Тест",
        "birth_date": dt.date(1960, 1, 1), "job": "Багш", "phone": "99112233",
    },
    {}, by=by,
)

# 5. One leave record (LEAVE_TYPE, LEAVE_ASSIGN and their ledger rows).
leave_type = save_leave_type(
    "Тест амралт T5",
    {"is_paid": True, "uses_annual_balance": False, "is_active": True, "order": 0, "staff_may_request": True},
)
leave = records.record(
    records.Draft(
        employee=Employee.objects.get(pk=emp.pk), leave_type=leave_type,
        start_date=LEAVE_START, end_date=LEAVE_END, note="t5 leave",
    ),
    by,
    today,
)

with connection.cursor() as cursor:
    cursor.execute("select trim(current_user) from rdb$database")
    current_user = cursor.fetchone()[0]
employee_orders = HrOrder.objects.filter(employee_id=emp.pk)
command_ids = [order.command_id for order in employee_orders if order.command_id]
capture.__exit__(None, None, None)
import re
def used(sql):
    verb = sql.strip().split(None, 1)[0].upper()
    if verb == "SELECT":
        names = re.findall(r'(?:FROM|JOIN)\\s+"?([A-Za-z0-9_]+)"?', sql, re.IGNORECASE)
    elif verb == "INSERT":
        names = re.findall(r'INTO\\s+"?([A-Za-z0-9_]+)"?', sql, re.IGNORECASE)[:1]
    elif verb in ("UPDATE", "DELETE"):
        names = re.findall(r'(?:UPDATE|FROM)\\s+"?([A-Za-z0-9_]+)"?', sql, re.IGNORECASE)[:1]
    else:
        names = []
    return {(verb, name.upper()) for name in names}
rights_used = sorted(set().union(*(used(q["sql"]) for q in capture.captured_queries)))
print("RESULT " + json.dumps({
    "rights_used": [f"{verb} {table}" for verb, table in rights_used],
    "current_user": current_user,
    "dep1": dep1,
    "dep2": dep2,
    "hire_pk": emp.pk,
    "hire_department": hire_department,
    "hire_salary": hire_salary,
    "department_after_move": department_after_move,
    "department_2035_before_cancel": department_2035_before_cancel,
    "department_2035_after_cancel": department_2035_after_cancel,
    "contact_rows": len(personal_rows.rows("contact", Employee.objects.get(pk=emp.pk))),
    "address_rows": len(personal_rows.rows("address", Employee.objects.get(pk=emp.pk))),
    "family_rows": len(personal_rows.rows("family", Employee.objects.get(pk=emp.pk))),
    "leave_rows": LeaveAssign.objects.filter(pk=leave.pk).count(),
    "command_rows": Command.objects.filter(pk__in=command_ids).count(),
    "orders": employee_orders.count(),
}))
""")

# The three statements the spike refused for RUNTIME_USER, each run on its own. Each prints its Firebird text.
REFUSED_AS_RUNTIME_USER_CODE = """
import json
import django
django.setup()
from django.db import connection
from django.db.utils import DatabaseError
attempts = {
    "alter": "ALTER TABLE EMPLOYEE ADD SCR5_PROBE_COL INTEGER",
    "drop_table": "DROP TABLE CUSTOMER",
    "drop_trigger": "DROP TRIGGER TR_EMPLOYEEID",
}
outcome = {}
for label, sql in attempts.items():
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
        outcome[label] = "ALLOWED"
    except DatabaseError as exc:
        outcome[label] = str(exc)
with connection.cursor() as cursor:
    cursor.execute("select trim(current_user) from rdb$database")
    outcome["current_user"] = cursor.fetchone()[0]
print("RESULT " + json.dumps(outcome))
"""


def _as_runtime_user(clone: str, code: str) -> dict[str, Any]:
    """Run code in a subprocess connected by RUNTIME_USER (FB_RUNTIME_USER is set for that call only)."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("FB_RUNTIME_USER", RUNTIME_USER)
        return result_of(run_django(code, DB_ENGINE="firebird", FIREBIRD_NAME=clone))


@pytest.fixture(scope="module")
def granted_clone(migrated_clone: str, tmp_path_factory: pytest.TempPathFactory) -> tuple[str, Path]:
    """Snapshot the copy, apply the grant script as SYSDBA, and yield (copy path, snapshot path)."""
    snapshot = tmp_path_factory.mktemp("fb_guard") / "before_grants.json"
    taken = run_manage(["fb_guard", "snapshot", str(snapshot)], DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone)
    assert taken.returncode == 0, taken.stdout + taken.stderr
    code = GRANT_AS_SYSDBA_CODE.replace("__USER__", repr(RUNTIME_USER))
    granted = result_of(
        run_django(
            code,
            DB_ENGINE="firebird",
            FIREBIRD_NAME=migrated_clone,
            FIREBIRD_USER="SYSDBA",
            FIREBIRD_PASSWORD=os.environ.get("FIREBIRD_PASSWORD", ""),
        )
    )
    assert int(granted["applied"]) > 100, granted  # the script has 100+ GRANT statements
    return migrated_clone, snapshot


@pytest.fixture(scope="module")
def limited_writes(granted_clone: tuple[str, Path]) -> dict[str, Any]:
    clone, _snapshot = granted_clone
    return _as_runtime_user(clone, WRITES_AS_RUNTIME_USER_CODE)


def test_limited_user_runs_hire_move_cancel_contacts_and_leave(limited_writes: dict[str, Any]) -> None:
    w = limited_writes
    assert "error" not in w, w.get("error")
    assert w["current_user"] == RUNTIME_USER  # the connection really was made by the limited user
    # The statements the run sent (the app's own SQL; trigger work is not listed): the write paths really ran.
    assert {
        "INSERT EMPLOYEE",
        "INSERT COMMAND",
        "INSERT LEAVE_ASSIGN",
        "INSERT LEAVE_TYPE",
        "INSERT FAMILY",
        "UPDATE EMPLOYEE_HISTORY",
        "DELETE EMPLOYEE_HISTORY",
    } <= set(w["rights_used"]), w["rights_used"]
    assert w["hire_department"] == w["dep1"]
    assert w["hire_salary"] == "1500000.00"
    assert w["department_after_move"] == w["dep2"]
    assert w["department_2035_before_cancel"] == w["dep1"]
    assert w["department_2035_after_cancel"] == w["dep2"]  # the cancelled 2035 move is gone
    assert w["contact_rows"] == 1
    assert w["address_rows"] == 1
    assert w["family_rows"] == 1
    assert w["leave_rows"] == 1
    assert w["orders"] == 3  # hire order and the two moves
    assert w["command_rows"] >= 1  # a registered order writes its COMMAND row


def test_limited_user_cannot_alter_a_macs_table(granted_clone: tuple[str, Path]) -> None:
    clone, _snapshot = granted_clone
    refused = _as_runtime_user(clone, REFUSED_AS_RUNTIME_USER_CODE)
    assert refused["current_user"] == RUNTIME_USER
    assert "no permission for ALTER access to TABLE EMPLOYEE" in refused["alter"], refused
    assert "no permission for DROP access to TABLE CUSTOMER" in refused["drop_table"], refused
    assert "no permission for ALTER access to TABLE EMPLOYEE" in refused["drop_trigger"], refused
    assert "ALLOWED" not in refused.values()


def test_fb_guard_verify_is_green_after_the_grants(granted_clone: tuple[str, Path]) -> None:
    clone, snapshot = granted_clone
    verified = run_manage(["fb_guard", "verify", str(snapshot)], DB_ENGINE="firebird", FIREBIRD_NAME=clone)
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert "verify ok" in verified.stdout


def _all_rights_on(out: str, table: str) -> set[str]:
    """The table-wide rights of table over every statement that names it (a table may appear in two blocks)."""
    rights: set[str] = set()
    for line in _table_statements(out, table):
        if "(" not in line:
            rights |= {right.strip() for right in line[len("GRANT ") : line.index(" ON ")].split(",")}
    return rights


def test_every_unmanaged_table_is_readable_by_the_runtime_user() -> None:
    data = _grants_run(USER)
    out = str(data["out"])
    listed = {table for _rights, table in SPIKE_MACS_TABLES} | {table for _rights, table in UNPROVEN_TABLES}
    assert len(data["unmanaged"]) > 70, data["unmanaged"]
    for table in data["unmanaged"]:
        assert "SELECT" in _all_rights_on(out, table), table
        if table not in listed:  # a table that no list names gets read access and nothing more
            assert _all_rights_on(out, table) == {"SELECT"}, table


def test_migration_history_is_readable_and_not_writable() -> None:
    out = str(_grants_run(USER)["out"])
    assert _all_rights_on(out, "IHR_DJANGO_MIGRATIONS") == {"SELECT"}


# Runs as the limited user: reads one row of every unmanaged model, then the migration history, then the system
# checks and showmigrations (the startup path). Each step that fails is reported by name, not raised.
READS_AS_RUNTIME_USER_CODE = _guarded(
    """
import django
django.setup()
from io import StringIO
from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

failures = []


def attempt(label, step):
    try:
        step()
    except Exception as exc:
        failures.append(label + ": " + str(exc).splitlines()[0])


unmanaged = [m for m in apps.get_models(include_auto_created=True) if not m._meta.managed and not m._meta.proxy]
for model in unmanaged:
    attempt(model._meta.label, lambda model=model: list(model._base_manager.all()[:1]))
attempt("migration history", lambda: list(MigrationRecorder.Migration.objects.all()[:1]))
attempt("system checks", lambda: call_command("check", stdout=StringIO(), stderr=StringIO()))
attempt("showmigrations", lambda: call_command("showmigrations", stdout=StringIO()))
with connection.cursor() as cursor:
    cursor.execute("select trim(current_user) from rdb$database")
    current = cursor.fetchone()[0]
print("RESULT " + json.dumps({"read": len(unmanaged), "failures": failures, "current_user": current}))
"""
)


def test_limited_user_reads_every_unmanaged_table_and_starts(granted_clone: tuple[str, Path]) -> None:
    clone, _snapshot = granted_clone
    reads = _as_runtime_user(clone, READS_AS_RUNTIME_USER_CODE)
    assert "error" not in reads, reads.get("error")
    assert reads["current_user"] == RUNTIME_USER  # the reads really ran as the limited user
    assert reads["read"] > 70
    assert reads["failures"] == [], reads["failures"]
