"""MACS-side saves against a migrated clone: what the MACS program writes, and what HR shows afterwards.

Run it against a MIGRATED CLONE, never against the real MACS database. It refuses to run unless the database file
name contains "clone" (case-insensitive). The flag --i-know-this-is-a-scratch-copy overrides that check; use it only
for a scratch copy whose name does not say so:

    set DB_ENGINE=firebird
    set FIREBIRD_NAME=<path to a migrated clone>
    .venv\\Scripts\\python scripts\\fb_macs_side_saves.py [--i-know-this-is-a-scratch-copy]

The script writes with RAW SQL ONLY (no HR model writes), the way the MACS program does, one transaction per numbered
save. After each save it prints OBSERVED lines: what HR's own read code (employees.listing.row_for and the employee
row) gives for the employee. Save 6 is the one exception: it ends with HR's own write service
(macs_writes.update_employee_columns and sync_current), because that is what "HR saves the same person" means.

It asserts no rule for the open questions (OQ-C, OQ-E1 to OQ-E3). It only prints what happened. A statement that
crashes is caught, printed as FAILED with the SQL step, and the next save still runs.

Every row the script created is deleted in a finally block, in reverse order of creation. Delete steps that fail are
printed as CLEANUP FAILED, and a final check prints LEFT BEHIND for any row still there. The script exits 0 unless
it breaks itself; leftover rows are printed loudly but do not change the exit code.

The process ends with os._exit, because the firebird driver can hang when connections are closed at interpreter exit.
"""

import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from django.utils import timezone  # noqa: E402
from employees.listing import row_for  # noqa: E402
from employees.models import EmployeeExt  # noqa: E402
from employees.services import macs_writes  # noqa: E402
from macs.models import Employee, EmployeeHistory  # noqa: E402
from macs.triggers import missing  # noqa: E402

SCRATCH_FLAG = "--i-know-this-is-a-scratch-copy"


@dataclass
class Ctx:
    """What the saves create, so cleanup can find it. `step` names the SQL statement that runs now."""

    tag: str
    today: Any
    step: str = "setup"
    emp: int | None = None
    departments: list[int] = field(default_factory=list)
    positions: list[int] = field(default_factory=list)
    contact_ids: list[int] = field(default_factory=list)
    movement_ids: list[int] = field(default_factory=list)
    dep_a: int | None = None
    dep_b: int | None = None
    pos_a: int | None = None
    pos_b: int | None = None
    shift_id: int | None = None
    contact_types_added: list[int] = field(default_factory=list)  # temporary contact_type rows (ids 2 and 4)
    shift_added: int | None = None  # temporary shifts row for the schedule test
    notes: list[str] = field(default_factory=list)


def _fetch(sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, list(params))
        return [tuple(row) for row in cursor.fetchall()]


def _exec(cursor: Any, ctx: Ctx, label: str, sql: str, params: list[Any]) -> Any:
    ctx.step = label
    cursor.execute(sql, params)
    return cursor


def _observed_hr(ctx: Ctx, label: str) -> str:
    """What HR's read code gives for the employee now: the job row the employee list uses, and the employee row."""
    employee = Employee.objects.get(pk=ctx.emp)
    row = row_for(employee, ctx.today)
    job = row.job
    dep = job.department_id if job is not None else None
    pos = job.position_id if job is not None else None
    line = (
        f"{label}: HR state={row.state} legacy_job={row.legacy} department_id={dep} position_id={pos} "
        f"employee.dep={employee.department_id} employee.occupation={employee.position_id}"
    )
    print("OBSERVED " + line)
    return line


def save_1_hire(ctx: Ctx) -> str:
    """MACS hire: employee row with hr='yes'. TR_EMPLOYEEID sets the ID and status, TR_EMPCUST the customer row."""
    with transaction.atomic(), connection.cursor() as cursor:
        _exec(
            cursor,
            ctx,
            "insert employee (hr='yes', emptype=1)",
            "INSERT INTO employee (name, surname, empno, hr, emptype, working_year, salary, contract_emp, died,"
            " workyear_sector, grade_perc, perc1, perc2, grade_amount, sal_percent, sal_amount, inworkdate, g_date)"
            " VALUES (%s, %s, %s, 'yes', 1, 0, 0, 'no', 'no', 0, 0, 0, 0, 0, 0, 0, %s, %s)"
            " RETURNING employee_id",
            [f"Macs{ctx.tag}", "Sanaa", f"MS{ctx.tag}", ctx.today, ctx.today],
        )
        ctx.emp = int(cursor.fetchone()[0])
    customers = _fetch("SELECT cust_id, description, code, employee FROM customer WHERE employee_ident = %s", [ctx.emp])
    print(f"OBSERVED save 1: customer rows made by TR_EMPCUST for employee {ctx.emp}: {customers}")
    in_list = EmployeeExt.objects.filter(employee_id=ctx.emp).exists()
    print(f"OBSERVED save 1: HR employee list shows this person (list rule ext__isnull=False): {in_list}")
    _observed_hr(ctx, "save 1")
    return f"customer rows {len(customers)} ({customers[0][1] if customers else 'none'}); HR list shows: {in_list}"


def save_2_department_position(ctx: Ctx) -> str:
    """MACS registered change, in the order the MACS program does it (trace in trigger-parity.md): the employee row
    gets the new department and position, then INS_EMPHISTORY copies the row into employee_history."""
    with transaction.atomic(), connection.cursor() as cursor:
        _exec(
            cursor,
            ctx,
            "update employee dep/occupation/changed_date/move_type",
            "UPDATE employee SET dep_ident = %s, occupation_ident = %s, changed_date = %s, move_type = 2"
            " WHERE employee_id = %s",
            [ctx.dep_a, ctx.pos_a, ctx.today, ctx.emp],
        )
        _exec(
            cursor,
            ctx,
            "EXECUTE PROCEDURE INS_EMPHISTORY (employee_history insert)",
            "EXECUTE PROCEDURE INS_EMPHISTORY(%s)",
            [ctx.emp],
        )
    history = EmployeeHistory.objects.filter(employee_id_value=ctx.emp).order_by("-id")
    print(f"OBSERVED save 2: employee_history rows for {ctx.emp}: {history.count()}")
    for row in history[:1]:
        print(
            f"OBSERVED save 2: newest history row dep_ident={row.department_id_value}"
            f" occupation_ident={row.position_id_value} changed_date={row.changed_date}"
        )
    return _observed_hr(ctx, "save 2")


def save_3_contacts(ctx: Ctx) -> str:
    """Contact type 2 (home phone) then type 4 (email). CONTACTING_AI0 copies each onto the employee row."""
    phone = f"77{ctx.tag[:6]}"[:14]
    email = f"ms{ctx.tag}@ex.test"
    with transaction.atomic(), connection.cursor() as cursor:
        for kind, value in ((2, phone), (4, email)):
            # A savepoint per insert: a refused type 2 must not stop the type 4 insert from being tried.
            try:
                with transaction.atomic():
                    _exec(
                        cursor,
                        ctx,
                        f"insert contacting type {kind}",
                        "INSERT INTO contacting (employee_ident, contacttype_ident, contacting, contact_name,"
                        " contact_relative) VALUES (%s, %s, %s, %s, %s) RETURNING contacting_id",
                        [ctx.emp, kind, value, "MS contact", "test"],
                    )
                    ctx.contact_ids.append(int(cursor.fetchone()[0]))
            except Exception as exc:
                print(f"FAILED save 3 at step [{ctx.step}]: {type(exc).__name__}: {exc}")
                ctx.notes.append(f"type {kind} refused")
    employee = Employee.objects.get(pk=ctx.emp)
    print(
        f"OBSERVED save 3: employee own phone (homephone)={employee.private_phone!r}"
        f" work_phone={employee.work_phone!r} email={employee.email!r}"
    )
    summary = f"employee.homephone={employee.private_phone!r}, employee.email={employee.email!r}"
    if ctx.notes:
        raise RuntimeError("; ".join(ctx.notes) + f"; shown above: {summary}")  # the table marks this save as no
    return summary


def save_4_rename_department(ctx: Ctx) -> str:
    """Rename the department of the employee. DEPS_BU0 (BEFORE UPDATE on deps) copies deps.schedule onto every
    employee with that department. The employee's schedule is first set to a different shift so the copy shows."""
    staff_sql = "SELECT employee_id, schedule FROM employee WHERE dep_ident = %s"
    dep_sql = "SELECT schedule, name FROM deps WHERE dep_id = %s"
    print(f"OBSERVED save 4: staff of dep {ctx.dep_a} before: {_fetch(staff_sql, [ctx.dep_a])}")
    with transaction.atomic(), connection.cursor() as cursor:
        if ctx.shift_id is not None:
            _exec(
                cursor,
                ctx,
                "set employee.schedule to another shift (MACS field edit)",
                "UPDATE employee SET schedule = %s WHERE employee_id = %s",
                [ctx.shift_id, ctx.emp],
            )
        print(f"OBSERVED save 4: staff of dep {ctx.dep_a} after the schedule edit: {_fetch(staff_sql, [ctx.dep_a])}")
        _exec(
            cursor,
            ctx,
            "rename department (UPDATE deps)",
            "UPDATE deps SET name = %s WHERE dep_id = %s",
            [f"MSR{ctx.tag}", ctx.dep_a],
        )
        dep_now = _fetch(dep_sql, [ctx.dep_a])
        print(f"OBSERVED save 4: deps.schedule of dep {ctx.dep_a} after the rename: {dep_now}")
        print(f"OBSERVED save 4: staff of dep {ctx.dep_a} after rename: {_fetch(staff_sql, [ctx.dep_a])}")
    if ctx.shift_id is None:
        print("OBSERVED save 4: no shift row in this copy, so the schedule copy could not be shown")
    return f"staff schedule after rename: {_fetch(staff_sql, [ctx.dep_a])}"


def save_5_back_dated_movement(ctx: Ctx) -> str:
    """A MACS movement with a move_date 30 days ago. MOVEMENT_AI0 copies the new department and position onto the
    employee row at insert, whatever the date. changed_date is read before and after."""
    before = _fetch("SELECT changed_date FROM employee WHERE employee_id = %s", [ctx.emp])
    with transaction.atomic(), connection.cursor() as cursor:
        _exec(
            cursor,
            ctx,
            "insert back-dated movement 'dep'",
            "INSERT INTO movement (emp_id, movement, move_date, description, old_depid, old_occupid, old_emptype,"
            " new_depid, new_occupid, new_emptype) VALUES (%s, 'dep', %s, %s, %s, %s, 1, %s, %s, 1)"
            " RETURNING movement_id",
            [
                ctx.emp,
                ctx.today - timedelta(days=30),
                f"back-dated {ctx.tag}",
                ctx.dep_a,
                ctx.pos_a,
                ctx.dep_b,
                ctx.pos_b,
            ],
        )
        ctx.movement_ids.append(int(cursor.fetchone()[0]))
    after = _fetch("SELECT changed_date, dep_ident, occupation_ident FROM employee WHERE employee_id = %s", [ctx.emp])
    print(f"OBSERVED save 5: employee changed_date and dep/occupation before={before} after={after}")
    print(f"OBSERVED save 5: employee.changed_date before={before[0][0] if before else None} after={after[0][0]}")
    return _observed_hr(ctx, "save 5")


def save_6_macs_then_hr(ctx: Ctx) -> str:
    """The same person saved by MACS, then by HR. MACS: an email field edit and a 'dep' movement to dep_a (today).
    HR: its own write service sets the work phone, then sync_current runs. Each effect should appear once."""
    with transaction.atomic(), connection.cursor() as cursor:
        _exec(
            cursor,
            ctx,
            "MACS field edit (email)",
            "UPDATE employee SET email = %s WHERE employee_id = %s",
            [f"macs6{ctx.tag}@ex.test", ctx.emp],
        )
        _exec(
            cursor,
            ctx,
            "MACS movement 'dep' today",
            "INSERT INTO movement (emp_id, movement, move_date, description, old_depid, old_occupid, old_emptype,"
            " new_depid, new_occupid, new_emptype) VALUES (%s, 'dep', %s, %s, %s, %s, 1, %s, %s, 1)"
            " RETURNING movement_id",
            [ctx.emp, ctx.today, f"save6 {ctx.tag}", ctx.dep_b, ctx.pos_b, ctx.dep_a, ctx.pos_a],
        )
        ctx.movement_ids.append(int(cursor.fetchone()[0]))
    ctx.step = "HR save: macs_writes.update_employee_columns (work_phone)"
    employee = Employee.objects.get(pk=ctx.emp)
    macs_writes.update_employee_columns(employee, {"work_phone": f"HR{ctx.tag[:6]}"})
    ctx.step = "HR save: macs_writes.sync_current"
    employee = Employee.objects.get(pk=ctx.emp)
    changed = macs_writes.sync_current(employee, ctx.today)
    print(f"OBSERVED save 6: sync_current returned {changed} (True means it changed a value)")
    employee = Employee.objects.get(pk=ctx.emp)
    print(
        f"OBSERVED save 6: after both saves email={employee.email!r} work_phone={employee.work_phone!r}"
        f" dep={employee.department_id} occupation={employee.position_id}"
    )
    movements = _fetch("SELECT COUNT(*) FROM movement WHERE emp_id = %s", [ctx.emp])[0][0]
    customers = _fetch("SELECT COUNT(*) FROM customer WHERE employee_ident = %s AND employee = 'yes'", [ctx.emp])[0][0]
    print(
        f"OBSERVED save 6: movement rows for the employee in total={movements} (save 5 and save 6 each wrote one),"
        f" ERP customer rows={customers}"
    )
    _observed_hr(ctx, "save 6")
    return f"email={employee.email!r}, work_phone={employee.work_phone!r}, movements={movements}, customers={customers}"


def setup(ctx: Ctx) -> None:
    """Two departments and two positions for the saves. Created by raw SQL, like the MACS program does."""
    with transaction.atomic(), connection.cursor() as cursor:
        ctx.step = "setup: insert department A"
        cursor.execute("INSERT INTO deps (name) VALUES (%s) RETURNING dep_id", [f"MSA{ctx.tag}"])
        ctx.dep_a = int(cursor.fetchone()[0])
        ctx.departments.append(ctx.dep_a)
        ctx.step = "setup: insert department B"
        cursor.execute("INSERT INTO deps (name) VALUES (%s) RETURNING dep_id", [f"MSB{ctx.tag}"])
        ctx.dep_b = int(cursor.fetchone()[0])
        ctx.departments.append(ctx.dep_b)
        ctx.step = "setup: insert position A"
        cursor.execute("INSERT INTO occupation (description) VALUES (%s) RETURNING occupation_id", [f"MSPA{ctx.tag}"])
        ctx.pos_a = int(cursor.fetchone()[0])
        ctx.positions.append(ctx.pos_a)
        ctx.step = "setup: insert position B"
        cursor.execute("INSERT INTO occupation (description) VALUES (%s) RETURNING occupation_id", [f"MSPB{ctx.tag}"])
        ctx.pos_b = int(cursor.fetchone()[0])
        ctx.positions.append(ctx.pos_b)
    # This copy's list tables can be empty: contact_type (the FK of CONTACTING) and shifts (the schedule). Without
    # rows the MACS trigger test cannot run, so the script adds temporary rows and deletes them in cleanup. Only
    # ids 2 and 4 are added, because the triggers test those literal ids.
    with transaction.atomic(), connection.cursor() as cursor:
        for kind in (2, 4):
            ctx.step = f"setup: contact type {kind} (temporary, if missing)"
            cursor.execute("SELECT COUNT(*) FROM contact_type WHERE contacttype_id = %s", [kind])
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO contact_type (contacttype_id, description) VALUES (%s, %s)",
                    [kind, f"MS test type {kind} {ctx.tag}"],
                )
                ctx.contact_types_added.append(kind)
        ctx.step = "setup: temporary shift for the schedule test"
        shift_id = 9000 + (int(ctx.tag, 16) % 900)
        cursor.execute("INSERT INTO shifts (id, name) VALUES (%s, %s)", [shift_id, f"MS {ctx.tag}"])
        # Recorded only after the INSERT succeeded: if the id already exists, the INSERT raises, shift_added stays
        # None, and cleanup never deletes the pre-existing shift.
        ctx.shift_added = shift_id
    ctx.shift_id = ctx.shift_added
    print(
        f"setup: departments {ctx.dep_a}, {ctx.dep_b}; positions {ctx.pos_a}, {ctx.pos_b};"
        f" temporary contact types added {ctx.contact_types_added}; temporary shift {ctx.shift_added}"
    )


def cleanup(ctx: Ctx) -> list[str]:
    """Delete what the saves created, in reverse order. Every step runs even when an earlier one fails."""
    steps: list[tuple[str, str, list[Any]]] = []
    if ctx.emp is not None:
        steps += [
            ("contacting", "DELETE FROM contacting WHERE employee_ident = %s", [ctx.emp]),
            ("movement", "DELETE FROM movement WHERE emp_id = %s", [ctx.emp]),
            ("employee_history", "DELETE FROM employee_history WHERE employee_ident = %s", [ctx.emp]),
            ("customer", "DELETE FROM customer WHERE employee_ident = %s AND employee = 'yes'", [ctx.emp]),
            ("employee", "DELETE FROM employee WHERE employee_id = %s", [ctx.emp]),
        ]
    for pos in ctx.positions:
        steps.append(("occupation", "DELETE FROM occupation WHERE occupation_id = %s", [pos]))
    for dep in ctx.departments:
        steps.append(("deps", "DELETE FROM deps WHERE dep_id = %s", [dep]))
    # The shift and contact types go after the employee (its schedule refers to a shift; CONTACTING to contact_type).
    if ctx.shift_added is not None:
        steps.append(("shifts", "DELETE FROM shifts WHERE id = %s", [ctx.shift_added]))
    for kind in ctx.contact_types_added:
        steps.append(("contact_type", "DELETE FROM contact_type WHERE contacttype_id = %s", [kind]))
    failures: list[str] = []
    if ctx.emp is not None:
        try:
            with transaction.atomic():
                EmployeeExt.objects.filter(employee_id=ctx.emp).delete()  # made by sync_current in save 6
        except Exception as exc:  # keep going: the other rows must still go
            failures.append(f"employees_employeeext: {type(exc).__name__}: {exc}")
    for label, sql, params in steps:
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql, params)
        except Exception as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    return failures


def left_behind(ctx: Ctx) -> list[str]:
    """Rows of this run that are still in the copy after cleanup, so the report can name them."""
    checks: list[tuple[str, str, list[Any]]] = []
    if ctx.emp is not None:
        checks += [
            ("employee", "SELECT COUNT(*) FROM employee WHERE employee_id = %s", [ctx.emp]),
            ("customer", "SELECT COUNT(*) FROM customer WHERE employee_ident = %s", [ctx.emp]),
            ("contacting", "SELECT COUNT(*) FROM contacting WHERE employee_ident = %s", [ctx.emp]),
            ("movement", "SELECT COUNT(*) FROM movement WHERE emp_id = %s", [ctx.emp]),
            ("employee_history", "SELECT COUNT(*) FROM employee_history WHERE employee_ident = %s", [ctx.emp]),
        ]
    for pos in ctx.positions:
        checks.append(("occupation", "SELECT COUNT(*) FROM occupation WHERE occupation_id = %s", [pos]))
    for dep in ctx.departments:
        checks.append(("deps", "SELECT COUNT(*) FROM deps WHERE dep_id = %s", [dep]))
    if ctx.shift_added is not None:
        checks.append(("shifts", "SELECT COUNT(*) FROM shifts WHERE id = %s", [ctx.shift_added]))
    for kind in ctx.contact_types_added:
        checks.append(("contact_type", "SELECT COUNT(*) FROM contact_type WHERE contacttype_id = %s", [kind]))
    left = []
    for label, sql, params in checks:
        count = _fetch(sql, params)[0][0]
        if count:
            left.append(f"{label} ({count} row(s), key {params[0]})")
    return left


def triggers_present() -> None:
    """Which MACS triggers this save script depends on are active on this copy (OBSERVED only)."""
    gone = missing("EMPLOYEE", "MOVEMENT", "EMPLOYEE_HISTORY", "CONTACTING", "CUSTOMER")
    print(f"OBSERVED triggers missing or inactive before the saves: {gone or 'none'}")


def main() -> int:
    if os.environ.get("DB_ENGINE") != "firebird":
        print("refused: set DB_ENGINE=firebird and FIREBIRD_NAME to a migrated clone")
        return 2
    args = sys.argv[1:]
    scratch_ok = SCRATCH_FLAG in args
    db_name = str(settings.DATABASES["default"]["NAME"])
    if not scratch_ok and "clone" not in Path(db_name).name.lower():
        print(
            f"refused: the database file {db_name!r} has no 'clone' in its name. Use a migrated clone, or pass "
            f"{SCRATCH_FLAG} if this is a scratch copy."
        )
        return 2
    ctx = Ctx(tag=uuid.uuid4().hex[:6], today=timezone.localdate())
    saves: list[tuple[str, Any]] = [
        ("1 hire (hr=yes)", save_1_hire),
        ("2 department and position (history)", save_2_department_position),
        ("3 contacts type 2 and 4", save_3_contacts),
        ("4 rename department (schedule)", save_4_rename_department),
        ("5 back-dated movement", save_5_back_dated_movement),
        ("6 MACS save then HR save", save_6_macs_then_hr),
    ]
    table: list[tuple[str, bool, str]] = []
    failures: list[str] = []
    try:
        triggers_present()
        try:
            setup(ctx)
        except Exception as exc:
            print(f"FAILED setup at {ctx.step}: {type(exc).__name__}: {exc}")
            saves = []
        for name, fn in saves:
            ctx.step = "start"
            try:
                summary = fn(ctx)
                table.append((name, True, summary))
            except Exception as exc:
                print(f"FAILED save {name} at step [{ctx.step}]: {type(exc).__name__}: {exc}")
                table.append((name, False, f"SQL failed at [{ctx.step}]: {exc}"))
    finally:
        failures = cleanup(ctx)
        for failure in failures:
            print("CLEANUP FAILED " + failure)
        for item in left_behind(ctx):
            print("LEFT BEHIND " + item)
    print()
    print("| save | SQL ok | what HR showed |")
    print("|---|---|---|")
    for name, ok, summary in table:
        print(f"| {name} | {'yes' if ok else 'no'} | {summary} |")
    if not table:
        print("(no saves ran)")
    print(f"cleanup failures: {len(failures)}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
