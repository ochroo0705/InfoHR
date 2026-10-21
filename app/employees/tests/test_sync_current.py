from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.core.management import call_command
from django.utils import timezone
from macs.models import EmployeeHistory, Movement

from employees.models import Department
from employees.services import history


@pytest.mark.django_db
def test_hire_copies_current_job_and_writes_movement(hired: Any) -> None:
    hired.refresh_from_db()
    assert hired.department is not None and hired.position is not None
    assert hired.salary == Decimal("2500000")
    assert hired.emptype == 1 and hired.status == "active"
    assert Movement.objects.filter(employee=hired, kind="in").exists()
    assert EmployeeHistory.objects.filter(employee_id_value=hired.pk).exists()


@pytest.mark.django_db
def test_future_transfer_reaches_production_on_its_day(hired: Any, actor: User, monkeypatch: Any) -> None:
    other = Department.objects.create(name="Борлуулалт")
    tomorrow = timezone.localdate() + timedelta(days=1)
    history.change_job(
        hired, effective=tomorrow, changes={"department": other}, change_type="transfer", note="", by=actor
    )
    hired.refresh_from_db()
    assert hired.department_id != other.pk  # not yet
    monkeypatch.setattr(timezone, "localdate", lambda: tomorrow)
    call_command("sync_current_jobs")
    hired.refresh_from_db()
    assert hired.department_id == other.pk  # Review Focus 1


@pytest.mark.django_db
def test_sync_is_idempotent_and_reports_changes(hired: Any) -> None:
    from io import StringIO

    from macs.models import Employee as ProductionEmployee

    before = ProductionEmployee.objects.get(pk=hired.pk).changed_date
    out = StringIO()
    call_command("sync_current_jobs", stdout=out)
    assert out.getvalue().startswith("0 ")
    assert ProductionEmployee.objects.get(pk=hired.pk).changed_date == before


@pytest.mark.django_db
def test_legacy_employee_without_job_or_salary_is_left_alone(actor: User) -> None:
    from io import StringIO

    from employees.models import ensure_ext
    from employees.services import macs_writes
    from employees.tests.conftest import hire_values

    legacy = macs_writes.create_employee(hire_values(), {}, code=macs_writes.next_code(), by=actor)
    ensure_ext(legacy)  # ext row only: no HR job or salary record (a plain edit of a legacy employee does this)
    legacy.refresh_from_db()
    before = (legacy.emptype, legacy.status, legacy.salary, legacy.department_id, legacy.position_id)
    assert macs_writes.sync_current(legacy, timezone.localdate()) is False
    legacy.refresh_from_db()
    assert (legacy.emptype, legacy.status, legacy.salary, legacy.department_id, legacy.position_id) == before
    out = StringIO()
    call_command("sync_current_jobs", stdout=out)
    assert out.getvalue().startswith("0 ")
