"""Two writers on the same row, on Firebird: the talent and vacation-total row locks refuse the second writer.

Each scenario runs in a subprocess on the migrated clone (``migrated_clone``) and reports a JSON result. Writer A runs
the real locking code path inside an open transaction and keeps it open, so it holds the row lock. Writer B runs in a
thread (its own Django connection, so its own Firebird attachment) and must be refused with RecordBusy within the lock
timeout. After A commits, B retries and must succeed.
"""

from typing import Any, cast

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

PRELUDE = """
import json
import threading
import time
import uuid
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import OperationalError, connection, transaction
from employees.models import Employee
from employees.services import personal_writes
from infohr_firebird.errors import busy_error_for
from leave.services import writes as leave_writes
from macs.models import TalentKind

by = get_user_model().objects.create_user(f"twowriter_{uuid.uuid4().hex[:6]}", password="x-long-pass-123")


def describe(exc):
    # Django re-raises a driver error with the original as __cause__; the lock check reads the driver error.
    cause = exc.__cause__ or exc
    return {
        "err_type": type(exc).__name__,
        "is_operational": isinstance(exc, OperationalError),
        "lock_refusal": busy_error_for(cause) is not None,
        "message": str(exc)[:200],
    }
"""

TALENT_CODE = (
    PRELUDE
    + """
out = {}
emp = Employee.objects.get(pk=EMPLOYEE)
kind = TalentKind.objects.create(name=f"two-writer {uuid.uuid4().hex[:6]}")
personal_writes.add("talent", emp, {"talent_ident": kind.pk, "trained_year": 2020, "description": "original"}, {}, by)
loaded = personal_writes.load("talent", emp, kind.pk)
assert loaded is not None, "the talent row was not inserted"

with transaction.atomic():
    # Writer A changes the talent row through the real update path and keeps its transaction open: it holds the row.
    personal_writes.update("talent", emp, kind.pk, loaded, {"trained_year": 2021}, {}, by)
    out["a_wrote"] = True

    def attempt_b():
        # Writer B tries the same row twice, through the real update and delete paths, on its own attachment.
        try:
            def update_b():
                personal_writes.update("talent", emp, kind.pk, loaded, {"trained_year": 2022}, {}, by)

            def delete_b():
                personal_writes.delete("talent", emp, kind.pk, loaded, by)

            for label, action in (("b_update", update_b), ("b_delete", delete_b)):
                started = time.monotonic()
                try:
                    action()
                    out[label] = {"result": "ok"}
                except Exception as exc:
                    out[label] = {"result": "refused", **describe(exc)}
                out[label]["seconds"] = time.monotonic() - started
        finally:
            connection.close()

    thread = threading.Thread(target=attempt_b)
    thread.start()
    thread.join(30)
    out["b_finished"] = not thread.is_alive()
# Writer A has committed. Writer B reloads the row, as the form does, and retries the update: it must now succeed.
fresh = personal_writes.load("talent", emp, kind.pk)
personal_writes.update("talent", emp, kind.pk, fresh, {"description": "after B"}, {}, by)
out["b_retry"] = "ok"
out["final_year"] = str(personal_writes.load("talent", emp, kind.pk)["trained_year"])
print("RESULT " + json.dumps(out))
"""
)

VACATION_CODE = (
    PRELUDE
    + """
out = {}

with transaction.atomic():
    # Writer A runs the totals sync, whose SELECT ... WITH LOCK holds the emp_vacation row until A commits.
    leave_writes.sync_vacation(EMPLOYEE, YEAR)
    out["a_wrote"] = True

    def attempt_b():
        started = time.monotonic()
        try:
            leave_writes.sync_vacation(EMPLOYEE, YEAR)
            out["b"] = {"result": "ok"}
        except Exception as exc:
            out["b"] = {"result": "refused", **describe(exc)}
        finally:
            out["b"]["seconds"] = time.monotonic() - started
            connection.close()

    thread = threading.Thread(target=attempt_b)
    thread.start()
    thread.join(30)
    out["b_finished"] = not thread.is_alive()
# Writer A has committed. Writer B retries the same sync: it must now succeed.
leave_writes.sync_vacation(EMPLOYEE, YEAR)
out["b_retry"] = "ok"
print("RESULT " + json.dumps(out))
"""
)

# Looks up one emp_vacation row in the migrated clone, so the scenarios need no hard-coded employee or year.
# The scenario code gets them as EMPLOYEE and YEAR (see _with_ids).
LOOKUP_CODE = """
import json
import django
django.setup()
from django.db import connection
with connection.cursor() as cur:
    cur.execute(
        "SELECT FIRST 1 v.emp_ident, v.myear FROM emp_vacation v JOIN employee e ON e.employee_id = v.emp_ident"
        " ORDER BY v.emp_ident, v.myear"
    )
    row = cur.fetchone()
assert row is not None, "the clone holds no emp_vacation row for an existing employee"
print("RESULT " + json.dumps({"employee_id": int(row[0]), "year": int(row[1])}))
"""

# The lock timeout is 3 s; a refusal that came back instantly would not show that the second writer waited for the lock.
LOCK_WAIT_MIN_SECONDS = 2.5
# Above the longest expected wait, so a correct run never reaches it.
FINISHED_WITHIN_SECONDS = 8.0


def _with_ids(code: str, ids: dict[str, int]) -> str:
    return f"EMPLOYEE, YEAR = {ids['employee_id']}, {ids['year']}\n" + code


@pytest.fixture(scope="module")
def clone_ids(migrated_clone: str) -> dict[str, int]:
    return cast(dict[str, int], result_of(run_django(LOOKUP_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone)))


@pytest.fixture(scope="module")
def talent_writers(migrated_clone: str, clone_ids: dict[str, int]) -> dict[str, Any]:
    return result_of(run_django(_with_ids(TALENT_CODE, clone_ids), DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


@pytest.fixture(scope="module")
def vacation_writers(migrated_clone: str, clone_ids: dict[str, int]) -> dict[str, Any]:
    return result_of(
        run_django(_with_ids(VACATION_CODE, clone_ids), DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone)
    )


def _assert_lock_refused_in_time(attempt: dict[str, Any]) -> None:
    """The second writer was refused by a Firebird row-lock error after waiting for the lock timeout."""
    assert attempt["result"] == "refused", attempt
    assert attempt["lock_refusal"] is True, attempt
    assert LOCK_WAIT_MIN_SECONDS <= attempt["seconds"] < FINISHED_WITHIN_SECONDS, attempt


def _assert_record_busy(attempt: dict[str, Any]) -> None:
    """The refusal reaches the caller as RecordBusy (an OperationalError), the type the user-facing text relies on."""
    assert attempt["err_type"] == "RecordBusy", attempt
    assert attempt["is_operational"] is True, attempt


def test_talent_row_lock_blocks_second_writer(talent_writers: dict[str, Any]) -> None:
    assert talent_writers["a_wrote"] is True, talent_writers
    assert talent_writers["b_finished"] is True, talent_writers
    _assert_lock_refused_in_time(talent_writers["b_update"])
    _assert_lock_refused_in_time(talent_writers["b_delete"])
    assert talent_writers["b_retry"] == "ok", talent_writers
    assert talent_writers["final_year"] == "2021", talent_writers
    _assert_record_busy(talent_writers["b_update"])
    _assert_record_busy(talent_writers["b_delete"])


def test_vacation_totals_lock_blocks_second_writer(vacation_writers: dict[str, Any]) -> None:
    assert vacation_writers["a_wrote"] is True, vacation_writers
    assert vacation_writers["b_finished"] is True, vacation_writers
    _assert_lock_refused_in_time(vacation_writers["b"])
    assert vacation_writers["b_retry"] == "ok", vacation_writers
    _assert_record_busy(vacation_writers["b"])
