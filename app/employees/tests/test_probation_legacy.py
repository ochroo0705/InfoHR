"""Probation months (production test_month) for employees that exist only in MACS (QC 1f)."""

from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User

from employees.models import Employee, ensure_ext
from employees.services import macs_writes, records

from .conftest import hire_values

pytestmark = pytest.mark.django_db


def _legacy(actor: User) -> Employee:
    """A MACS-only employee: production row plus HR ext, no HR hire job and no rehire event."""
    emp = macs_writes.create_employee(
        hire_values() | {"first_hire_date": date(2018, 1, 1)}, {}, code=macs_writes.next_code(), by=actor
    )
    ensure_ext(emp)
    Employee.objects.filter(pk=emp.pk).update(contract_start=date(2026, 1, 5), salary=Decimal("1800000"))
    return Employee.objects.get(pk=emp.pk)


def test_legacy_probation_counts_from_contract_start_not_first_hire(actor: User) -> None:
    emp = _legacy(actor)
    records.update_employee(emp, {"probation_end": date(2026, 4, 5)}, actor)
    # 2026-01-05 to 2026-04-05 is 90 days, about 3 months. From first_hire_date it would be over 100 months.
    assert Employee.objects.get(pk=emp.pk).probation_months == 3


def test_legacy_without_probation_end_keeps_existing_test_month(actor: User) -> None:
    emp = _legacy(actor)
    Employee.objects.filter(pk=emp.pk).update(probation_months=2)
    records.update_employee(emp, {"work_phone": "99887766"}, actor)
    assert Employee.objects.get(pk=emp.pk).probation_months == 2


def test_current_employment_start_order_for_legacy(actor: User) -> None:
    emp = _legacy(actor)
    assert macs_writes.current_employment_start(emp) == date(2026, 1, 5)
    Employee.objects.filter(pk=emp.pk).update(contract_start=None)
    assert macs_writes.current_employment_start(Employee.objects.get(pk=emp.pk)) == date(2018, 1, 1)
