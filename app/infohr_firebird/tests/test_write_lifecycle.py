"""The whole employment lifecycle on Firebird, through the real service functions (plan 3, Task 11a).

Employee A, on one migrated clone, in one subprocess: hire -> department move -> position move -> termination ->
rehire (dated 2035, so it is still scheduled and events.cancel accepts it) -> cancel the rehire.

Employee B: hire -> a transfer dated 2035 that is applied through events.apply_waiting (the path a signed order takes),
checked before its effective date and on that day.

history.hire() and orders are not used (they take a PostgreSQL advisory lock, plan 4). The immediate steps follow
the same calls as test_write_cancel.py. Each step is compared with the EXPECTED table written below: the employee
row, the movement rows (kind and date), the employee_history row count and the newest history row's fired date,
and the customer rows. The table is the test's own statement of what HR and MACS should hold.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

LIFECYCLE_CODE = """
import json
import uuid
import datetime as dt
from decimal import Decimal
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone
from employees import history_range
from employees.models import (
    ContractType, Employee, EmployeeType, Event, EventType, JobRecord, JobStatus, SalaryRecord,
)
from employees.services import events, history, macs_writes
from macs.models import Branch, Department, EmployeeHistory, FiredReason, Movement, Position

User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"life_{tag}", password="x-long-pass-123")
dep1, dep2 = list(Department.objects.order_by("pk").values_list("pk", flat=True)[:2])
pos1, pos2 = list(Position.objects.order_by("pk").values_list("pk", flat=True)[:2])
br1 = Branch.objects.order_by("pk").values_list("pk", flat=True).first()
fired = FiredReason.objects.order_by("pk").first()
TODAY = timezone.localdate()
HIRE = dt.date(2026, 1, 5)
DEP = dt.date(2026, 3, 2)
OCC = dt.date(2026, 5, 4)
TERM = dt.date(2026, 6, 30)
REHIRE = dt.date(2035, 3, 1)
B_MOVE = dt.date(2035, 6, 1)

OBS = {}

def values(label, n):
    return {
        "family_name": "Test",
        "given_name": f"L{tag}{label}",
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": f"УБ9008{n:04d}",
        "first_hire_date": HIRE,
        "work_conditions": 1,
        "branch_id": br1,
        "department_id": dep1,
        "position_id": pos1,
    }

def start(label, n):
    e = macs_writes.create_employee(values(label, n), {}, code=f"LC{tag}{label}", by=by)
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
        note="t11a", by=by, event=event,
    )
    return finish(event, e)

def customers(pk):
    with connection.cursor() as c:
        c.execute("select cust_id from customer where employee_ident = %s order by cust_id", [pk])
        return [row[0] for row in c.fetchall()]

def observe(key, pk):
    e = Employee.objects.get(pk=pk)
    latest = EmployeeHistory.objects.filter(employee_id_value=pk).order_by("-id").first()
    OBS[key] = {
        "employee": {
            "department": e.department_id,
            "position": e.position_id,
            "branch": e.branch_id,
            "status": e.status,
            "emptype": e.emptype,
            "salary": str(e.salary),
            "changed_date": str(e.changed_date),
            "fired_reason_id": e.fired_reason_id,
            "died": e.died,
            "contract_flag": e.contract_flag,
            "wagetest": e.wagetest,
        },
        "movements": [[m.kind, str(m.date)] for m in Movement.objects.filter(employee_id=pk).order_by("pk")],
        "history_rows": EmployeeHistory.objects.filter(employee_id_value=pk).count(),
        "latest_history_fired_date": None if latest is None or latest.fired_date is None else str(latest.fired_date),
        "customer_ids": customers(pk),
    }

# Employee A: the lifecycle.
a = start("a", 1)
observe("a.hire", a.pk)

transfer(Employee.objects.get(pk=a.pk), DEP, {"department": Department.objects.get(pk=dep2)})
observe("a.department_move", a.pk)

transfer(Employee.objects.get(pk=a.pk), OCC, {"position": Position.objects.get(pk=pos2)})
observe("a.position_move", a.pk)

ev_term = Event.objects.create(
    employee=Employee.objects.get(pk=a.pk), type=EventType.TERMINATION, effective=TERM,
    fired_reason=fired, created_by=by,
)
history.change_job(
    Employee.objects.get(pk=a.pk), effective=TERM, changes={"status": JobStatus.LEFT},
    change_type=EventType.TERMINATION.change_type, note="t11a", by=by, event=ev_term,
)
finish(ev_term, Employee.objects.get(pk=a.pk))
observe("a.termination", a.pk)

# The rehire is a signed change that takes effect in 2035: applied through apply_waiting, so it can still be cancelled.
ev_rehire = Event.objects.create(
    employee=Employee.objects.get(pk=a.pk), type=EventType.REHIRE, effective=REHIRE, reason="",
    created_by=by, applied_at=None,
    proposed={"job": {"department": dep1, "position": pos1}, "salary": None},
)
events.apply_waiting(ev_rehire, by=by)
observe("a.rehire_applied", a.pk)

events.cancel(Event.objects.get(pk=ev_rehire.pk), reason="t11a cancel rehire", by=by)
observe("a.rehire_cancelled", a.pk)

# Employee B: a transfer dated 2035, applied the way apply_waiting applies a signed change.
b = start("b", 2)
observe("b.hire", b.pk)

ev_sched = Event.objects.create(
    employee=Employee.objects.get(pk=b.pk), type=EventType.TRANSFER, effective=REHIRE, reason="",
    created_by=by, applied_at=None, proposed={"job": {"department": dep2}, "salary": None},
)
events.apply_waiting(ev_sched, by=by)
observe("b.scheduled_applied", b.pk)

# The day the change takes effect: the daily sync (daily_sync.sync_all_employees) runs sync_current for that day.
macs_writes.sync_current(Employee.objects.get(pk=b.pk), REHIRE)
observe("b.effective_day", b.pk)

print("RESULT " + json.dumps({
    "today": str(TODAY),
    "ids": {"DEP1": dep1, "DEP2": dep2, "POS1": pos1, "POS2": pos2, "BR1": br1,
            "FR": None if fired is None else fired.pk},
    "obs": OBS,
}))
"""

# Expected values. Sentinels: DEP1/DEP2/POS1/POS2/BR1/FR are the ids the clone gives, TODAY is the run's local date.
# A cancelled rehire leaves the employee row's changed_date at the termination snapshot's date (2026-06-30): the
# trigger rewrites the row from the previous history row, and the undo's sync then finds nothing to change. Whether
# that is the right changed_date is an open question for the user (OQ-B in the report).
HIRE_EMP = {"department": "DEP1", "position": "POS1", "branch": "BR1", "status": "active", "emptype": 1,
            "salary": "1500000.00", "changed_date": "TODAY", "fired_reason_id": None, "died": "no",
            "contract_flag": "no", "wagetest": None}
DEP_EMP = {**HIRE_EMP, "department": "DEP2"}
OCC_EMP = {**DEP_EMP, "position": "POS2"}
LEFT_EMP = {**OCC_EMP, "status": "inactive", "emptype": 3, "fired_reason_id": "FR"}

EXPECTED = {
    "a.hire": {
        "employee": HIRE_EMP,
        "movements": [["in", "2026-01-05"]],
        "history_rows": 1,
        "latest_history_fired_date": None,
    },
    "a.department_move": {
        "employee": DEP_EMP,
        "movements": [["in", "2026-01-05"], ["dep", "2026-03-02"]],
        "history_rows": 2,
        "latest_history_fired_date": None,
    },
    "a.position_move": {
        "employee": OCC_EMP,
        "movements": [["in", "2026-01-05"], ["dep", "2026-03-02"], ["occ", "2026-05-04"]],
        "history_rows": 3,
        "latest_history_fired_date": None,
    },
    "a.termination": {
        "employee": LEFT_EMP,
        "movements": [["in", "2026-01-05"], ["dep", "2026-03-02"], ["occ", "2026-05-04"], ["out", "2026-06-30"]],
        "history_rows": 4,
        "latest_history_fired_date": "2026-06-30",
    },
    "a.rehire_applied": {  # the 2035 rehire is recorded but the employee row still shows the leaver today
        "employee": {**LEFT_EMP, "changed_date": "TODAY"},
        "movements": [["in", "2026-01-05"], ["dep", "2026-03-02"], ["occ", "2026-05-04"], ["out", "2026-06-30"],
                      ["in", "2035-03-01"]],
        "history_rows": 5,
        "latest_history_fired_date": None,
    },
    "a.rehire_cancelled": {
        "employee": {**LEFT_EMP, "changed_date": "2026-06-30"},  # OQ-B: trigger semantics
        "movements": [["in", "2026-01-05"], ["dep", "2026-03-02"], ["occ", "2026-05-04"], ["out", "2026-06-30"]],
        "history_rows": 4,
        "latest_history_fired_date": "2026-06-30",
    },
    "b.hire": {
        "employee": HIRE_EMP,
        "movements": [["in", "2026-01-05"]],
        "history_rows": 1,
        "latest_history_fired_date": None,
    },
    "b.scheduled_applied": {  # the 2035 transfer must not show on the employee row before its date
        "employee": HIRE_EMP,
        "movements": [["in", "2026-01-05"], ["dep", "2035-03-01"]],
        "history_rows": 2,
        "latest_history_fired_date": None,
    },
    "b.effective_day": {
        "employee": {**DEP_EMP, "changed_date": "2035-03-01"},
        "movements": [["in", "2026-01-05"], ["dep", "2035-03-01"]],
        "history_rows": 2,
        "latest_history_fired_date": None,
    },
}

STEPS = list(EXPECTED)


def _resolve(value: Any, ids: dict[str, Any], today: str) -> Any:
    if value == "TODAY":
        return today
    if value == "FR":
        return ids["FR"]
    if value in ("DEP1", "DEP2", "POS1", "POS2", "BR1"):
        return ids[value]
    if isinstance(value, dict):
        return {k: _resolve(v, ids, today) for k, v in value.items()}
    return value


@pytest.fixture(scope="module")
def lifecycle(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(LIFECYCLE_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


@pytest.mark.parametrize("step", STEPS)
def test_employee_row_matches_expected(lifecycle: dict[str, Any], step: str) -> None:
    expected = _resolve(EXPECTED[step]["employee"], lifecycle["ids"], lifecycle["today"])
    assert lifecycle["obs"][step]["employee"] == expected


@pytest.mark.parametrize("step", STEPS)
def test_movement_rows_match_expected(lifecycle: dict[str, Any], step: str) -> None:
    assert lifecycle["obs"][step]["movements"] == EXPECTED[step]["movements"]


@pytest.mark.parametrize("step", STEPS)
def test_history_rows_match_expected(lifecycle: dict[str, Any], step: str) -> None:
    observed = lifecycle["obs"][step]
    assert observed["history_rows"] == EXPECTED[step]["history_rows"]
    assert observed["latest_history_fired_date"] == EXPECTED[step]["latest_history_fired_date"]


@pytest.mark.parametrize("step", STEPS)
def test_exactly_one_customer_row_throughout(lifecycle: dict[str, Any], step: str) -> None:
    observed = lifecycle["obs"][step]["customer_ids"]
    assert len(observed) == 1
    first = lifecycle["obs"][step.split(".")[0] + ".hire"]["customer_ids"]
    assert observed == first


def test_scheduled_transfer_does_not_show_before_its_date(lifecycle: dict[str, Any]) -> None:
    before = lifecycle["obs"]["b.scheduled_applied"]["employee"]
    assert before["department"] == lifecycle["ids"]["DEP1"]
    assert before["changed_date"] == lifecycle["today"]


def test_scheduled_transfer_shows_on_its_date(lifecycle: dict[str, Any]) -> None:
    on_day = lifecycle["obs"]["b.effective_day"]["employee"]
    assert on_day["department"] == lifecycle["ids"]["DEP2"]
    assert on_day["changed_date"] == "2035-03-01"
