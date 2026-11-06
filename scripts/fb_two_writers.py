"""Two writers, one employee, one Firebird database: the history guard must let only one open-ended record in.

Run it against a MIGRATED CLONE, never against the real MACS database. It refuses to run unless the database file
name contains "clone" (case-insensitive). The flag --i-know-this-is-a-scratch-copy overrides that check; use it only
for a scratch copy whose name does not say so:

    set DB_ENGINE=firebird
    set FIREBIRD_NAME=<path to a migrated clone>
    .venv\\Scripts\\python scripts\\fb_two_writers.py [runs] [--fresh-lock] [--i-know-this-is-a-scratch-copy]

`--fresh-lock` deletes the chosen employee's HistoryLock row before each run, so the first writer has to create it
(the case where the bug was seen). That deletes a row that was already there; the script does not restore it.

What it does, per run:
  1. Picks a MACS employee who has no job record yet, and creates a throwaway user as the author.
  2. Starts two threads. Each thread has its own Django database connection (Django connections are per thread),
     waits at a barrier so both start together, and inside transaction.atomic() calls
     history_range.lock_employee, history_range.ensure_free(JobRecord, ...) and then creates an open-ended
     JobRecord that starts on the same day.
  3. Expected: exactly one thread succeeds. The other is refused with RecordBusy (a row held by the other
     transaction) or HistoryError (the period is already taken, or another writer created the lock row).
     Any other error, including IntegrityError, is FAIL. Afterwards the employee has exactly ONE
     open-ended record.
  4. Cleans up in a finally block: the job records, the HistoryLock rows it found missing (or that --fresh-lock
     removed), the Position and Department it created (with their Ext rows) and the throwaway user. Then it prints
     one RESULT line per run and a SUMMARY.

Exit code 0 when every run met the expectation, 1 otherwise. The process ends with os._exit, because the
firebird driver can hang when connections are closed at interpreter exit.
"""

import datetime as dt
import json
import os
import sys
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402
from employees import history_range  # noqa: E402
from employees.models import DepartmentExt, HistoryLock, JobRecord, PositionExt  # noqa: E402
from employees.services import macs_writes  # noqa: E402
from employees.services.history import HistoryError  # noqa: E402
from infohr_firebird.errors import RecordBusy, busy_error_for  # noqa: E402
from macs.models import Employee as MacsEmployee  # noqa: E402

START = dt.date(2026, 11, 6)
WRITERS = ("writer_a", "writer_b")
SCRATCH_FLAG = "--i-know-this-is-a-scratch-copy"


def _classify(exc: BaseException) -> str:
    """'busy' for a RecordBusy (directly or chained), 'history_error' for HistoryError, else 'unexpected'."""
    if isinstance(exc, RecordBusy) or busy_error_for(exc) is not None:
        return "busy"
    if exc.__cause__ is not None and busy_error_for(exc.__cause__) is not None:
        return "busy"
    if isinstance(exc, HistoryError):
        return "history_error"
    return f"unexpected:{type(exc).__name__}: {exc}"


def _writer(
    name: str,
    employee_id: int,
    author: Any,
    position: Any,
    department: Any,
    barrier: threading.Barrier,
    outcomes: dict[str, str],
) -> None:
    barrier.wait()  # both writers start at the same moment
    try:
        with transaction.atomic():
            history_range.lock_employee(employee_id)
            history_range.ensure_free(JobRecord, employee_id, START, None)
            JobRecord.objects.create(
                employee_id=employee_id,
                start_date=START,
                end_date=None,
                position=position,
                department=department,
                employee_type="full_time",
                status="active",
                contract_type="open_ended",
                change_type="hire",
                created_by=author,
            )
        outcomes[name] = "ok"
    except Exception as exc:  # the outcome is the result; the thread must not die silently
        outcomes[name] = _classify(exc)


def _one_run(
    author: Any, position: Any, department: Any, fresh_lock: bool, touched: dict[int, bool]
) -> dict[str, Any]:
    employee_id = (
        MacsEmployee.objects.exclude(pk__in=JobRecord.objects.values("employee_id"))
        .order_by("pk")
        .values_list("pk", flat=True)
        .first()
    )
    if employee_id is None:
        return {"error": "no MACS employee without job records"}
    # Remember whether the lock row existed before this script touched the employee (first sighting wins).
    touched.setdefault(employee_id, HistoryLock.objects.filter(employee_id=employee_id).exists())
    if fresh_lock:
        HistoryLock.objects.filter(employee_id=employee_id).delete()  # no lock row: the first writer creates it
    barrier = threading.Barrier(len(WRITERS))
    outcomes: dict[str, str] = {}
    threads = [
        threading.Thread(
            target=_writer, args=(name, employee_id, author, position, department, barrier, outcomes), daemon=True
        )
        for name in WRITERS
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    open_ended = JobRecord.objects.filter(employee_id=employee_id, end_date__isnull=True).count()
    winners = [name for name, value in outcomes.items() if value == "ok"]
    losers = [value for value in outcomes.values() if value != "ok"]
    expected = len(outcomes) == 2 and len(winners) == 1 and losers[0] in ("busy", "history_error")
    result = {
        "employee_id": employee_id,
        "outcomes": outcomes,
        "open_ended_records": open_ended,
        "expected": bool(expected and open_ended == 1),
    }
    JobRecord.objects.filter(employee_id=employee_id).delete()  # remove what this run wrote
    return result


def _cleanup(
    author: Any, position: Any, department: Any, touched: dict[int, bool], fresh_lock: bool
) -> list[str]:
    """Remove everything this script created. Each step runs even when an earlier one fails; returns the failures."""
    steps: list[tuple[str, Callable[[], Any]]] = []
    for employee_id, had_lock in touched.items():
        steps.append((f"job records of {employee_id}", _deleter(JobRecord.objects.filter(employee_id=employee_id))))
        if not had_lock or fresh_lock:
            steps.append((f"lock row of {employee_id}", _deleter(HistoryLock.objects.filter(employee_id=employee_id))))
    if department is not None:
        steps.append(("department ext", _deleter(DepartmentExt.objects.filter(department_id=department.pk))))
        steps.append(("department", department.delete))
    if position is not None:
        steps.append(("position ext", _deleter(PositionExt.objects.filter(position_id=position.pk))))
        steps.append(("position", position.delete))
    if author is not None:
        steps.append(("user", _deleter(get_user_model().objects.filter(pk=author.pk))))
    failures: list[str] = []
    for label, step in steps:
        try:
            step()
        except Exception as exc:  # keep going: the other rows must still go
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    return failures


def _deleter(queryset: Any) -> Callable[[], Any]:
    return queryset.delete


def main() -> int:
    if os.environ.get("DB_ENGINE") != "firebird":
        print("refused: set DB_ENGINE=firebird and FIREBIRD_NAME to a migrated clone")
        return 2
    args = sys.argv[1:]
    fresh_lock = "--fresh-lock" in args
    scratch_ok = SCRATCH_FLAG in args
    numbers = [arg for arg in args if arg not in ("--fresh-lock", SCRATCH_FLAG)]
    runs = int(numbers[0]) if numbers else 1
    db_name = str(settings.DATABASES["default"]["NAME"])
    if not scratch_ok and "clone" not in Path(db_name).name.lower():
        print(
            f"refused: the database file {db_name!r} has no 'clone' in its name. Use a migrated clone, or pass "
            f"{SCRATCH_FLAG} if this is a scratch copy."
        )
        return 2
    tag = uuid.uuid4().hex[:6]
    user_model = get_user_model()
    author: Any = None
    position: Any = None
    department: Any = None
    touched: dict[int, bool] = {}
    all_ok = True
    try:
        author = user_model.objects.create_user(f"two_writers_{tag}", password=uuid.uuid4().hex)
        position = macs_writes.save_position(f"two-writers {tag}")
        department = macs_writes.save_department(f"two-writers {tag}")
        for run in range(1, runs + 1):
            result = _one_run(author, position, department, fresh_lock, touched)
            result["run"] = run
            result["fresh_lock"] = fresh_lock
            print("RESULT " + json.dumps(result, ensure_ascii=False))
            sys.stdout.flush()
            all_ok = all_ok and bool(result.get("expected"))
    finally:
        failures = _cleanup(author, position, department, touched, fresh_lock)
        for failure in failures:
            print("CLEANUP FAILED " + failure)
        all_ok = all_ok and not failures
    print("SUMMARY " + json.dumps({"runs": runs, "all_expected": all_ok}))
    sys.stdout.flush()
    return 0 if all_ok else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
