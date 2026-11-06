"""sync_current on an unchanged employee changes nothing on Firebird (plan 3, Review Focus 5).

A hire with a job and a salary gets a first sync_current, which copies the job and salary onto the production row. A
second sync_current, on a freshly loaded employee with nothing changed, must return False, write no UPDATE of the
employee row, and keep changed_date as the first sync left it. Runs in a subprocess on the migrated clone, the same
pattern as test_write_hire.py, and reports one JSON result.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

SYNC_CODE = """
import json
import re
import uuid
import datetime as dt
from decimal import Decimal
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from employees import history_range
from employees.models import ContractType, Employee, EmployeeType, JobRecord, JobStatus, SalaryRecord
from employees.services import macs_writes
from macs.models import Branch, Department, Position
User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"sync_{tag}", password="x-long-pass-123")
dep1 = Department.objects.order_by("pk").values_list("pk", flat=True).first()
pos1 = Position.objects.order_by("pk").values_list("pk", flat=True).first()
br1 = Branch.objects.order_by("pk").values_list("pk", flat=True).first()
TODAY = timezone.localdate()
HIRE = dt.date(2026, 1, 5)
values = {
    "family_name": "Sync",
    "given_name": f"Sy{tag}",
    "gender": "M",
    "birth_date": dt.date(1990, 5, 17),
    "register_no": "УБ90130001",
    "first_hire_date": HIRE,
    "work_conditions": 1,
    "branch_id": br1,
    "department_id": dep1,
    "position_id": pos1,
}
e = macs_writes.create_employee(values, {}, code=f"SY{tag}", by=by)
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
first = macs_writes.sync_current(e, TODAY)
after_first = Employee.objects.get(pk=e.pk)
changed_after_first = after_first.changed_date
fresh = Employee.objects.get(pk=e.pk)
with CaptureQueriesContext(connection) as ctx:
    second = macs_writes.sync_current(fresh, TODAY)
pattern = re.compile(r'^\\s*UPDATE\\s+"?EMPLOYEE"?\\s', re.IGNORECASE)
updates = [q["sql"] for q in ctx.captured_queries if pattern.match(q["sql"])]
after_second = Employee.objects.get(pk=e.pk)
print("RESULT " + json.dumps({
    "first": first,
    "second": second,
    "changed_date_after_first": str(changed_after_first),
    "changed_date_after_second": str(after_second.changed_date),
    "employee_updates_in_second": len(updates),
    "captured": len(ctx.captured_queries),
    "salary": str(after_second.salary),
    "status": after_second.status,
}))
"""


@pytest.fixture(scope="module")
def sync_result(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(SYNC_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_first_sync_current_copies_the_job_and_salary(sync_result: dict[str, Any]) -> None:
    """Precondition: the first sync really changes the row, so the next test is not vacuous."""
    assert sync_result["first"] is True
    assert sync_result["salary"] == "1500000.00"


def test_second_sync_current_on_unchanged_employee_returns_false(sync_result: dict[str, Any]) -> None:
    assert sync_result["captured"] > 0, "query capture recorded nothing; the zero-UPDATE check would be vacuous"
    assert sync_result["second"] is False
    assert sync_result["employee_updates_in_second"] == 0


def test_second_sync_current_keeps_changed_date(sync_result: dict[str, Any]) -> None:
    assert sync_result["changed_date_after_second"] == sync_result["changed_date_after_first"]
