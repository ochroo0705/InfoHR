"""HR write functions refuse to run when a MACS trigger they rely on is inactive (plan 3, Review M-2).

One private copy of the migrated clone is made for this module. Each refusal test deactivates one trigger on that copy,
in its own subprocess, and checks that the write raises MacsTriggerMissing and writes no row. The triggers are never
reactivated: the copy is thrown away at the end of the module. The shared migrated_clone is never changed.

Order matters for one test only: the MOVEMENT positive control must run before the MOVEMENT refusal (file order). The
ALTER TRIGGER runs inside transaction.atomic so it is committed; an uncommitted one is rolled back when a write's
atomic block raises, which would make the trigger look active again.
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from infohr_firebird.tests.copies import remove_copy
from infohr_firebird.tests.test_settings_seam import result_of, run_django

HIRE_VALUES = """
import uuid
import datetime as dt
import django
django.setup()
from django.contrib.auth import get_user_model
from employees.services import macs_writes
from macs.models import Branch, Department, Position
User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"rf_{tag}", password="x-long-pass-123")
dep1 = Department.objects.order_by("pk").values_list("pk", flat=True).first()
pos1 = Position.objects.order_by("pk").values_list("pk", flat=True).first()
br1 = Branch.objects.order_by("pk").values_list("pk", flat=True).first()
DAY = dt.date(2026, 3, 2)

def hire(register_no):
    values = {
        "family_name": "Refuse",
        "given_name": f"Rf{tag}",
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": register_no,
        "first_hire_date": dt.date(2026, 1, 5),
        "work_conditions": 1,
        "branch_id": br1,
        "department_id": dep1,
        "position_id": pos1,
    }
    return macs_writes.create_employee(values, {}, code=f"RF{tag[:4]}{register_no[-4:]}", by=by)
"""

# Positive control, in its own process: with MOVEMENT_AI0 active the write goes through. A process caches a passed
# require() (macs.triggers), so the refusal below must run in a process that never passed it.
CONTROL_CODE = (
    HIRE_VALUES
    + """
import json
from macs.models import Movement
emp = hire("УБ90120001")
control_id = macs_writes.record_movement(emp, "in", DAY)
print("RESULT " + json.dumps({"control_id": control_id, "rows": Movement.objects.filter(employee=emp).count()}))
"""
)

MOVEMENT_CODE = (
    HIRE_VALUES
    + """
import json
from django.db import connection, transaction
from macs.models import Movement
from macs.triggers import MacsTriggerMissing, missing
emp = hire("УБ90120004")
with transaction.atomic():
    with connection.cursor() as c:
        c.execute("ALTER TRIGGER MOVEMENT_AI0 INACTIVE")
inactive = missing("MOVEMENT")
refused = None
try:
    macs_writes.record_movement(emp, "dep", DAY)
except MacsTriggerMissing as exc:
    refused = str(exc)
print("RESULT " + json.dumps({
    "missing": inactive,
    "refused": refused,
    "rows_after": Movement.objects.filter(employee=emp).count(),
}))
"""
)

DELETE_CODE = (
    HIRE_VALUES
    + """
import json
from django.db import connection, transaction
from employees.models import Event, EventProdRow, EventType
from macs.models import EmployeeHistory
from macs.triggers import MacsTriggerMissing, missing
emp = hire("УБ90120002")
history_id = macs_writes.snapshot_history(emp, DAY)
event = Event.objects.create(employee=emp, type=EventType.TRANSFER, effective=DAY, created_by=by)
EventProdRow.objects.create(event=event, movement_id=None, history_id=history_id)
with transaction.atomic():
    with connection.cursor() as c:
        c.execute("ALTER TRIGGER EMPLOYEE_HISTORY_BD0 INACTIVE")
inactive = missing("EMPLOYEE_HISTORY")
refused = None
try:
    macs_writes.delete_event_rows(event)
except MacsTriggerMissing as exc:
    refused = str(exc)
print("RESULT " + json.dumps({
    "missing": inactive,
    "refused": refused,
    "history_row_kept": EmployeeHistory.objects.filter(pk=history_id).count(),
    "prod_row_kept": event.prod_rows.count(),
}))
"""
)

CONTACT_BODY = """
import json
from django.db import connection, transaction
from employees.services import personal_writes
from macs.models import ContactRow, ContactType
from macs.triggers import MacsTriggerMissing, missing
if not ContactType.objects.filter(pk=2).exists():
    ContactType.objects.create(pk=2, name="Утас")
emp = hire("УБ90120003")
def homephone():
    with connection.cursor() as c:
        c.execute("select TRIM(homephone) from employee where employee_id = %s", [emp.pk])
        return c.fetchone()[0]
rows_before = ContactRow.objects.filter(employee=emp).count()
phone_before = homephone()
with transaction.atomic():
    with connection.cursor() as c:
        c.execute("ALTER TRIGGER CONTACTING_AI0 INACTIVE")
inactive = missing("CONTACTING")
refused = None
try:
    contact = {"contact_type_id": 2, "value": "99112233", "name": "Дорж", "relative": "Ах"}
    personal_writes.add("contact", emp, contact, {}, by=by)
except MacsTriggerMissing as exc:
    refused = str(exc)
print("RESULT " + json.dumps({
    "missing": inactive,
    "refused": refused,
    "rows_before": rows_before,
    "rows_after": ContactRow.objects.filter(employee=emp).count(),
    "phone_unchanged": homephone() == phone_before,
}))
"""
CONTACT_CODE = HIRE_VALUES + CONTACT_BODY


@pytest.fixture(scope="module")
def private_copy(migrated_clone: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """One private copy of the migrated clone for this module; its triggers are deactivated here only."""
    folder: Path = tmp_path_factory.mktemp("refusal")
    clone = folder / "private.fdb"
    shutil.copyfile(migrated_clone, clone)
    try:
        yield str(clone)
    finally:
        remove_copy(clone)


def test_record_movement_writes_while_movement_trigger_is_active(private_copy: str) -> None:
    """(M-2) positive control, run first in this module (pytest keeps file order): the write works while active."""
    data = result_of(run_django(CONTROL_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=private_copy))
    assert isinstance(data["control_id"], int)
    assert data["rows"] == 1


def test_record_movement_refused_when_movement_trigger_is_inactive(private_copy: str) -> None:
    """(M-2) with MOVEMENT_AI0 inactive, record_movement raises MacsTriggerMissing and inserts no movement row."""
    data = result_of(run_django(MOVEMENT_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=private_copy))
    assert data["missing"] == ["MOVEMENT_AI0"]
    assert data["refused"] is not None
    assert "MOVEMENT_AI0" in data["refused"]
    assert data["rows_after"] == 0


def test_delete_event_rows_refused_when_employee_history_trigger_is_inactive(private_copy: str) -> None:
    """(M-2) with EMPLOYEE_HISTORY_BD0 inactive, delete_event_rows raises and deletes neither row."""
    data = result_of(run_django(DELETE_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=private_copy))
    assert data["missing"] == ["EMPLOYEE_HISTORY_BD0"]
    assert data["refused"] is not None
    assert "EMPLOYEE_HISTORY_BD0" in data["refused"]
    assert data["history_row_kept"] == 1
    assert data["prod_row_kept"] == 1


def test_contact_add_refused_when_contacting_trigger_is_inactive(private_copy: str) -> None:
    """(M-2) with CONTACTING_AI0 inactive, a type-2 contact add raises and writes no contact row or employee change."""
    data = result_of(run_django(CONTACT_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=private_copy))
    assert data["missing"] == ["CONTACTING_AI0"]
    assert data["refused"] is not None
    assert "CONTACTING_AI0" in data["refused"]
    assert data["rows_after"] == data["rows_before"]
    assert data["phone_unchanged"] is True
