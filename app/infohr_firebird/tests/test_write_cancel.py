"""Cancelling a change on Firebird against EMPLOYEE_HISTORY_BD0 (plan 3, Task 7).

Deleting the newest employee_history row fires EMPLOYEE_HISTORY_BD0 (BEFORE DELETE), which rewrites 18 columns of the
employee row from the previous history row. HR then recomputes the row from its own job and salary history. The
scenarios run the real service functions (events.cancel, macs_writes.delete_event_rows, history.change_job,
history.change_salary, macs_writes.write_event_rows) on the migrated clone, in a subprocess, and report JSON.
history.hire() is not used: it takes a PostgreSQL advisory lock. Its steps are repeated here without that lock.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

CANCEL_CODE = """
import json
import uuid
import datetime as dt
from decimal import Decimal
import django
django.setup()
from django.contrib.auth import get_user_model
from django.utils import timezone
from employees import history_range
from employees.models import (
    ContractType, Employee, EmployeeType, Event, EventType, JobRecord, JobStatus, SalaryRecord,
)
from employees.services import events, history, macs_writes
from employees.services.events import EventError
from macs.models import Branch, Department, EmployeeHistory, Position

User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"cancel_{tag}", password="x-long-pass-123")
dep1, dep2 = list(Department.objects.order_by("pk").values_list("pk", flat=True)[:2])
pos1, pos2 = list(Position.objects.order_by("pk").values_list("pk", flat=True)[:2])
br1 = Branch.objects.order_by("pk").values_list("pk", flat=True).first()
TODAY = timezone.localdate()
HIRE = TODAY  # hired today: sync_current stamps changed_date with today, so it matches the hire history row
FUT1 = dt.date(2035, 3, 1)
FUT2 = dt.date(2035, 9, 1)

def values(n):
    return {
        "family_name": "Test",
        "given_name": f"C7{tag}{n}",
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": f"УБ9007{n:04d}",
        "first_hire_date": HIRE,
        "work_conditions": 1,
        "branch_id": br1,
        "department_id": dep1,
        "position_id": pos1,
    }

def start(n):
    e = macs_writes.create_employee(values(n), {}, code=f"C7{tag}{n}", by=by)
    history_range.lock_employee(e.pk)
    JobRecord.objects.create(
        employee=e, **history_range.span_kwargs(HIRE, None), position_id=pos1, department_id=dep1,
        employee_type=EmployeeType.FULL_TIME, emptype=1, status=JobStatus.ACTIVE,
        contract_type=ContractType.OPEN_ENDED, change_type="hire", created_by=by,
    )
    SalaryRecord.objects.create(
        employee=e, **history_range.span_kwargs(HIRE, None), base_salary=Decimal("1500000.00"),
        change_type="hire", created_by=by,
    )
    macs_writes.sync_current(e, TODAY)
    macs_writes.record_movement(e, "in", HIRE)
    macs_writes.snapshot_history(e, HIRE)
    return Employee.objects.get(pk=e.pk)

def finish(event, e):
    event.applied_at = timezone.now()
    event.save(update_fields=["applied_at"])
    macs_writes.sync_current(e, TODAY)
    e.refresh_from_db()
    event.employee = e
    macs_writes.write_event_rows(event)
    return event

def transfer(e, effective, changes):
    event = Event.objects.create(employee=e, type=EventType.TRANSFER, effective=effective, created_by=by)
    history.change_job(
        e, effective=effective, changes=changes, change_type=EventType.TRANSFER.change_type,
        note="t7", by=by, event=event,
    )
    return finish(event, e)

def raise_salary(e, effective, amount):
    event = Event.objects.create(employee=e, type=EventType.SALARY_CHANGE, effective=effective, created_by=by)
    history.change_salary(
        e, effective=effective, amount=Decimal(amount), change_type=EventType.SALARY_CHANGE.change_type,
        note="t7", by=by, event=event,
    )
    return finish(event, e)

def snap(pk):
    e = Employee.objects.get(pk=pk)
    return {
        "department": e.department_id,
        "position": e.position_id,
        "salary": str(e.salary),
        "status": e.status,
        "changed_date": str(e.changed_date),
        "command_ident": e.command_id_value,
        "move_type": e.move_type,
        "emptype": e.emptype,
        "contract_flag": e.contract_flag,
        "wagetest": e.wagetest,
        "contract_start": str(e.contract_start),
        "contract_end": str(e.contract_end),
    }

def rows(pk):
    return [
        {
            "id": r["id"],
            "changed_date": str(r["changed_date"]),
            "department": r["department_id_value"],
            "salary": str(r["salary"]),
            "status": r["status"],
        }
        for r in EmployeeHistory.objects.filter(employee_id_value=pk).order_by("id").values(
            "id", "changed_date", "department_id_value", "salary", "status"
        )
    ]

def recomputed(pk):
    e = Employee.objects.get(pk=pk)
    job = history.job_on(e, TODAY)
    sal = history.salary_on(e, TODAY)
    return {"department": job.department_id, "position": job.position_id, "salary": str(sal.base_salary)}

out = {}

# Case A: the newest change, cancelled through the real cancel flow.
e1 = start(1)
before = snap(e1.pk)
ev = transfer(e1, FUT1, {"department": Department.objects.get(pk=dep2)})
applied = snap(e1.pk)
rows_before = rows(e1.pk)
events.cancel(ev, reason="t7 case a", by=by)
out["a"] = {
    "before": before,
    "applied": applied,  # MOVEMENT_AI0 already moves the department on apply (recorded, not asserted)
    "after": snap(e1.pk),
    "rows_before": rows_before,
    "rows_after": rows(e1.pk),
    "recomputed": recomputed(e1.pk),
    "hire_row_id": rows_before[0]["id"],
}

# Case A2: the caller holds the employee instance; delete_event_rows then sync_current on that same instance.
e2 = start(2)
before2 = snap(e2.pk)
ev2 = transfer(e2, FUT1, {"department": Department.objects.get(pk=dep2)})
macs_writes.delete_event_rows(ev2)
macs_writes.sync_current(ev2.employee, TODAY)
out["a2"] = {
    "before": before2,
    "after": snap(e2.pk),
    "held_instance": {
        "department": ev2.employee.department_id,
        "salary": str(ev2.employee.salary),
        "changed_date": str(ev2.employee.changed_date),
    },
    "recomputed": recomputed(e2.pk),
}

# Case B: a change that is NOT the newest history row.
e3 = start(3)
before3 = snap(e3.pk)
ev_a = transfer(e3, FUT1, {"department": Department.objects.get(pk=dep2)})
transfer(e3, FUT2, {"position": Position.objects.get(pk=pos2)})
applied3 = snap(e3.pk)
rows3 = rows(e3.pk)
try:
    events.cancel(ev_a, reason="t7 case b", by=by)
    refused = None
except EventError as exc:
    refused = str(exc.errors)
out["b"] = {
    "before": applied3,
    "after_refused_cancel": snap(e3.pk),
    "refused": refused,
    "rows_before": rows3,
    "rows_after_refused": rows(e3.pk),
}
macs_writes.delete_event_rows(ev_a)
out["b"]["after_direct_delete"] = snap(e3.pk)
out["b"]["rows_after_direct_delete"] = rows(e3.pk)
out["b"]["recomputed_after_direct_delete"] = recomputed(e3.pk)  # not asserted: apply-time move

# Case D: two future changes. The caller holds an Employee read before either change (HR state = hire state), then
# cancels the newer change with delete_event_rows and syncs the SAME instance it passed in on the Event. The trigger
# restores the OLDER transfer's row, so the database differs from HR's state today; the sync must then save.
held = start(7)
transfer(Employee.objects.get(pk=held.pk), FUT1, {"department": Department.objects.get(pk=dep2)})
ev_f2 = transfer(Employee.objects.get(pk=held.pk), FUT2, {"position": Position.objects.get(pk=pos2)})
ev_d = Event.objects.get(pk=ev_f2.pk)
ev_d.employee = held
before7 = snap(held.pk)
macs_writes.delete_event_rows(ev_d)
macs_writes.sync_current(ev_d.employee, TODAY)
out["d"] = {
    "before": before7,
    "after": snap(held.pk),
    "held_instance": {"department": ev_d.employee.department_id, "position": ev_d.employee.position_id},
    "recomputed": recomputed(held.pk),
}

# Case D2: the same two changes, cancelled through events.cancel (undo re-reads the employee before syncing).
e6 = start(6)
transfer(e6, FUT1, {"department": Department.objects.get(pk=dep2)})
ev_g2 = transfer(e6, FUT2, {"position": Position.objects.get(pk=pos2)})
events.cancel(ev_g2, reason="t7 case d2", by=by)
out["d2"] = {"after": snap(e6.pk), "recomputed": recomputed(e6.pk)}

# Case C: two history rows with the same changed_date (a transfer and a salary change both on FUT1).
e4 = start(4)
ev_t = transfer(e4, FUT1, {"department": Department.objects.get(pk=dep2)})
ev_s = raise_salary(e4, FUT1, "1700000.00")
before4 = snap(e4.pk)
rows4 = rows(e4.pk)
events.cancel(ev_s, reason="t7 case c", by=by)
out["c"] = {
    "before": before4,
    "after": snap(e4.pk),
    "rows_before": rows4,
    "rows_after": rows(e4.pk),
    "recomputed": recomputed(e4.pk),
    "hire_row_id": rows4[0]["id"],
}

print("RESULT " + json.dumps(out, default=str))
"""


@pytest.fixture(scope="module")
def cancelled(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(CANCEL_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_newest_cancel_restores_every_employee_column(cancelled: dict[str, Any]) -> None:
    a = cancelled["a"]
    assert a["after"] == a["before"]


def test_newest_cancel_matches_recomputed_state(cancelled: dict[str, Any]) -> None:
    a = cancelled["a"]
    assert a["recomputed"]["department"] == a["after"]["department"]
    assert a["recomputed"]["position"] == a["after"]["position"]
    assert a["recomputed"]["salary"] == a["after"]["salary"]


def test_held_instance_after_direct_delete_matches_database(cancelled: dict[str, Any]) -> None:
    a2 = cancelled["a2"]
    assert a2["after"] == a2["before"]
    assert a2["held_instance"]["department"] == a2["after"]["department"]
    assert a2["held_instance"]["salary"] == a2["after"]["salary"]


def test_not_newest_cancel_is_refused_and_leaves_row_alone(cancelled: dict[str, Any]) -> None:
    b = cancelled["b"]
    assert b["refused"] is not None  # history.undo refuses: a later change exists
    assert b["after_refused_cancel"] == b["before"]
    assert b["rows_after_refused"] == b["rows_before"]


def test_not_newest_delete_fires_trigger_as_no_op(cancelled: dict[str, Any]) -> None:
    b = cancelled["b"]
    assert b["after_direct_delete"] == b["before"]
    assert b["rows_after_direct_delete"] != b["rows_before"]  # the row itself was deleted


def test_tied_changed_date_cancel_matches_recomputed_state(cancelled: dict[str, Any]) -> None:
    c = cancelled["c"]
    assert c["after"]["department"] == c["recomputed"]["department"]
    assert c["after"]["position"] == c["recomputed"]["position"]
    assert c["after"]["salary"] == c["recomputed"]["salary"]
    assert c["after"]["salary"] == c["before"]["salary"]


def test_direct_cancel_then_sync_on_held_instance_repairs_the_row(cancelled: dict[str, Any]) -> None:
    d = cancelled["d"]
    assert d["held_instance"]["department"] == d["recomputed"]["department"]
    assert d["after"]["department"] == d["recomputed"]["department"]
    assert d["after"]["position"] == d["recomputed"]["position"]


def test_events_cancel_of_newer_change_repairs_the_row(cancelled: dict[str, Any]) -> None:
    d2 = cancelled["d2"]
    assert d2["after"]["department"] == d2["recomputed"]["department"]
    assert d2["after"]["position"] == d2["recomputed"]["position"]
