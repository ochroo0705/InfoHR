"""ORM paths that plan 2 added, run on the Firebird clone (plan Task 9).

Each test runs its ORM code in a subprocess in Firebird mode, against the module clone of the template
(``migrated_clone``), and reports a JSON result. The subprocess sees the real app code: the accounts signal, the
history services, the assistant admin queryset. Nothing here is a copy of the app logic.
"""

from typing import Any

from infohr_firebird.tests.test_settings_seam import result_of, run_django

DELETE_USER_CODE = """
import json
import uuid
import django
django.setup()
from django.contrib.auth import get_user_model
from employees.models import AttentionDismissal, Employee
User = get_user_model()
suffix = uuid.uuid4().hex[:8]
employee = Employee.objects.order_by("pk").first()
user = User.objects.create_user(f"orm_probe_{suffix}", password="x-long-pass-123")
dismissal = AttentionDismissal.objects.create(user=user, employee=employee, key=f"probe {suffix}")
dismissal_pk = dismissal.pk
user.delete()
print("RESULT " + json.dumps({
    "dismissal_left": AttentionDismissal.objects.filter(pk=dismissal_pk).exists(),
    "user_left": User.objects.filter(username=f"orm_probe_{suffix}").exists(),
}))
"""

SIGNAL_CODE = """
import json
import uuid
import django
django.setup()
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
User = get_user_model()
user = User.objects.create_user(f"orm_signal_{uuid.uuid4().hex[:8]}", password="x-long-pass-123")
fresh = User.objects.get(pk=user.pk)
print("RESULT " + json.dumps({
    "groups": sorted(fresh.groups.values_list("name", flat=True)),
    "employee_group_exists": Group.objects.filter(name="Employee").exists(),
}))
"""

# A first job and salary period on an existing template employee, then a salary change through the service.
# history.hire() is not used: it takes a PostgreSQL advisory lock and creating an EMPLOYEE row on the clone fails
# (see the report). Dates are read back from the database.
HISTORY_CODE = """
import json
import uuid
import datetime as dt
from decimal import Decimal
import django
django.setup()
from django.contrib.auth import get_user_model
from employees import history_range
from employees.models import Employee, HistoryLock, JobRecord, SalaryRecord
from employees.services import history, macs_writes
from employees.services.history import HistoryError
User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"orm_history_{tag}", password="x-long-pass-123")
employee = Employee.objects.exclude(pk__in=JobRecord.objects.values("employee_id")).order_by("pk").first()
history_range.lock_employee(employee.pk)
job_record_kwargs = {
    "position": macs_writes.save_position(f"Нягтлан {tag}"),
    "department": macs_writes.save_department(f"Санхүү {tag}"),
    "employee_type": "full_time",
    "status": "active",
    "contract_type": "open_ended",
}
JobRecord.objects.create(
    employee=employee,
    start_date=dt.date(2026, 1, 5),
    end_date=None,
    change_type="hire",
    created_by=by,
    **job_record_kwargs,
)
SalaryRecord.objects.create(
    employee=employee,
    start_date=dt.date(2026, 1, 5),
    end_date=None,
    base_salary=Decimal("2500000.37"),
    change_type="hire",
    created_by=by,
)
history.change_salary(
    employee, effective=dt.date(2026, 7, 1), amount=Decimal("3000000.05"), change_type="correction", note="", by=by
)
job_record = JobRecord.objects.get(employee=employee)
salary_records = list(SalaryRecord.objects.filter(employee=employee).order_by("start_date"))
first_salary, second_salary = salary_records
overlap_refused = False
try:
    history_range.ensure_free(SalaryRecord, employee.pk, dt.date(2026, 2, 1), dt.date(2026, 3, 1))
except HistoryError:
    overlap_refused = True
lock = HistoryLock.objects.get(employee_id=employee.pk)
print("RESULT " + json.dumps({
    "employee_id": employee.pk,
    "job_start_type": type(job_record.start_date).__name__,
    "job_end_type": type(job_record.end_date).__name__,
    "job_contains_hire_day": dt.date(2026, 1, 5) in job_record.period,
    "salary_start_type": type(first_salary.start_date).__name__,
    "salary_end_type": type(first_salary.end_date).__name__,
    "salary_end": first_salary.end_date.isoformat() if first_salary.end_date else None,
    "salary_first": str(first_salary.base_salary),
    "salary_second": str(second_salary.base_salary),
    "salary_base_type": type(first_salary.base_salary).__name__,
    "overlap_refused": overlap_refused,
    "lock_counter": lock.counter,
}))
"""

ADMIN_EXISTS_CODE = """
import json
import uuid
import django
django.setup()
from django.db.models import Exists, OuterRef
from assistant.models import HelpExample, HelpQuestion
tag = uuid.uuid4().hex[:8]
corrected_source = HelpQuestion.objects.create(question=f"probe corrected {tag}", outcome="none")
plain_source = HelpQuestion.objects.create(question=f"probe plain {tag}", outcome="none")
HelpExample.objects.create(question=f"probe example {tag}", entry="", source=corrected_source, active=True)
rows = HelpQuestion.objects.annotate(
    corrected=Exists(HelpExample.objects.filter(source=OuterRef("pk"), active=True))
).filter(pk__in=[corrected_source.pk, plain_source.pk])
values = {row.pk: row.corrected for row in rows}
print("RESULT " + json.dumps({
    "corrected_value": values[corrected_source.pk],
    "plain_value": values[plain_source.pk],
    "corrected_type": type(values[corrected_source.pk]).__name__,
    "plain_type": type(values[plain_source.pk]).__name__,
}))
"""


def _firebird(migrated_clone: str, code: str) -> dict[str, Any]:
    return result_of(run_django(code, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_delete_user_with_attention_dismissals(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, DELETE_USER_CODE)
    assert data["user_left"] is False
    assert data["dismissal_left"] is False


def test_user_create_adds_group_through_signal(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, SIGNAL_CODE)
    assert data["employee_group_exists"] is True
    assert "Employee" in data["groups"]


def test_job_and_salary_history_round_trip_dates_as_date(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, HISTORY_CODE)
    assert data["job_start_type"] == "date"
    assert data["job_end_type"] == "NoneType"
    assert data["job_contains_hire_day"] is True
    assert data["salary_start_type"] == "date"
    assert data["salary_end"] == "2026-07-01"
    assert data["salary_end_type"] == "date"
    assert data["salary_first"] == "2500000.37"
    assert data["salary_second"] == "3000000.05"
    assert data["salary_base_type"] == "Decimal"
    assert data["overlap_refused"] is True


def test_history_lock_row_created_per_employee(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, HISTORY_CODE)
    assert data["lock_counter"] >= 1


def test_assistant_admin_exists_annotation(migrated_clone: str) -> None:
    data = _firebird(migrated_clone, ADMIN_EXISTS_CODE)
    assert data["corrected_type"] == "bool"
    assert data["plain_type"] == "bool"
    assert data["corrected_value"] is True
    assert data["plain_value"] is False
