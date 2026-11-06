"""A movement carries the branch, so MOVEMENT_AI0 does not clear employee.branch_ident (plan 3, Task 6).

MOVEMENT_AI0 (after insert, kinds dep and occ) copies NEW_DEPID, NEW_OCCUPID and NEW_BRANCHID onto the employee.
HR's movement rows used to leave NEW_BRANCHID NULL, which wiped the branch. Each scenario runs in a subprocess on
the migrated clone (the same pattern as test_write_hire.py) and reports a JSON result; the tests assert on it.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

MOVEMENT_CODE = """
import json
import uuid
import datetime as dt
import django
django.setup()
from django.contrib.auth import get_user_model
from employees.models import Employee
from employees.services import macs_writes
from employees.services.macs_writes import EMPTYPE_FLAGS
from macs.models import Branch, Department, Position
User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"mv_{tag}", password="x-long-pass-123")
dep1, dep2 = list(Department.objects.order_by("pk").values_list("pk", flat=True)[:2])
pos1, pos2 = list(Position.objects.order_by("pk").values_list("pk", flat=True)[:2])
br1, br2 = list(Branch.objects.order_by("pk").values_list("pk", flat=True)[:2])
DAY = dt.date(2026, 3, 2)

def hire(n):
    values = {
        "family_name": "Test",
        "given_name": f"Mv{tag}{n}",
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": f"УБ9006{n:04d}",
        "first_hire_date": dt.date(2026, 1, 5),
        "work_conditions": 1,
        "branch_id": br1,
        "department_id": dep1,
        "position_id": pos1,
    }
    return macs_writes.create_employee(values, {}, code=f"MV{tag}{n}", by=by)

def state(pk):
    e = Employee.objects.get(pk=pk)
    return {
        "branch": e.branch_id,
        "dep": e.department_id,
        "occ": e.position_id,
        "emptype": e.emptype,
        "status": e.status,
        "contract_flag": e.contract_flag,
    }

def movement_branches(movement_id):
    from django.db import connection
    with connection.cursor() as c:
        c.execute("select old_branchid, new_branchid from movement where movement_id = %s", [movement_id])
        return list(c.fetchone())

def same(d):
    return {"department_id": dep1, "position_id": pos1, "emptype": 1, **d}

out = {"dep1": dep1, "dep2": dep2, "pos1": pos1, "pos2": pos2, "br1": br1, "br2": br2}

e = hire(1)
before = state(e.pk)
mid = macs_writes.record_movement(e, "dep", DAY, old=same({}), new=same({"department_id": dep2}))
out["dep"] = {"before": before, "after": state(e.pk), "movement_branches": movement_branches(mid)}

e = hire(2)
before = state(e.pk)
mid = macs_writes.record_movement(e, "occ", DAY, old=same({}), new=same({"position_id": pos2}))
out["occ"] = {"before": before, "after": state(e.pk), "movement_branches": movement_branches(mid)}

e = hire(3)
before = state(e.pk)
macs_writes.record_movement(e, "in", DAY)
macs_writes.record_movement(e, "out", DAY)
out["in_out"] = {"before": before, "after": state(e.pk)}

e = hire(4)
before = state(e.pk)
mid = macs_writes.record_movement(e, "dep", DAY, old=same({}), new=same({"department_id": dep2, "emptype": 3}))
out["emptype"] = {
    "before": before,
    "after": state(e.pk),
    "expected_flags": list(EMPTYPE_FLAGS[3]),
    "movement_branches": movement_branches(mid),
}

e = hire(5)
mid = macs_writes.record_movement(e, "dep", DAY, old=same({}), new=same({"department_id": dep2, "branch_id": br2}))
out["explicit_branch"] = {"after": state(e.pk), "movement_branches": movement_branches(mid)}

print("RESULT " + json.dumps(out))
"""


@pytest.fixture(scope="module")
def moved(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(MOVEMENT_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_department_movement_keeps_branch_and_sets_department(moved: dict[str, Any]) -> None:
    dep = moved["dep"]
    assert dep["before"]["branch"] == moved["br1"]
    assert dep["after"]["branch"] == moved["br1"]
    assert dep["after"]["dep"] == moved["dep2"]
    assert dep["after"]["occ"] == moved["pos1"]
    assert dep["after"]["status"] == "active"


def test_department_movement_row_stores_the_branch(moved: dict[str, Any]) -> None:
    assert moved["dep"]["movement_branches"] == [moved["br1"], moved["br1"]]


def test_position_movement_keeps_branch_and_sets_position(moved: dict[str, Any]) -> None:
    occ = moved["occ"]
    assert occ["after"]["branch"] == moved["br1"]
    assert occ["after"]["dep"] == moved["dep1"]
    assert occ["after"]["occ"] == moved["pos2"]
    assert occ["movement_branches"] == [moved["br1"], moved["br1"]]


def test_hire_and_leave_movements_change_nothing(moved: dict[str, Any]) -> None:
    before, after = moved["in_out"]["before"], moved["in_out"]["after"]
    assert after == before
    assert after["branch"] == moved["br1"]


def test_emptype_change_to_inactive_matches_sync_current_flags(moved: dict[str, Any]) -> None:
    status, contract_flag, _wagetest = moved["emptype"]["expected_flags"]
    after = moved["emptype"]["after"]
    assert after["status"] == status == "inactive"
    assert after["contract_flag"] == contract_flag
    assert after["branch"] == moved["br1"]
    assert after["dep"] == moved["dep2"]


def test_explicit_branch_in_new_is_written(moved: dict[str, Any]) -> None:
    explicit = moved["explicit_branch"]
    assert explicit["after"]["branch"] == moved["br2"]
    assert explicit["movement_branches"] == [moved["br1"], moved["br2"]]
