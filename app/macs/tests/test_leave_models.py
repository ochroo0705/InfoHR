from datetime import date

import pytest
from django.db import IntegrityError, transaction

from macs.models import Employee, Entitlement, LeaveAssign, LeaveTypeRow


@pytest.fixture
def employee(db: None) -> Employee:
    return Employee.objects.create(given_name="Т", family_name="Б")


@pytest.fixture
def leave_type(db: None) -> LeaveTypeRow:
    return LeaveTypeRow.objects.create(name="Ээлжийн")


@pytest.mark.django_db
def test_insert_uses_sequence(leave_type: LeaveTypeRow) -> None:
    assert isinstance(leave_type.pk, int)
    assert leave_type.pk > 0


@pytest.mark.django_db
def test_assign_roundtrip_dates(employee: Employee, leave_type: LeaveTypeRow) -> None:
    a = LeaveAssign.objects.create(
        employee=employee,
        leave_type=leave_type,
        date1=date(2025, 7, 1),
        date2=date(2025, 7, 14),
        adays=10,
        status=LeaveAssign.APPROVED,
    )
    a.refresh_from_db()
    assert a.date1 == date(2025, 7, 1)
    assert a.date2 == date(2025, 7, 14)


@pytest.mark.django_db
def test_unique_key_enforced(employee: Employee, leave_type: LeaveTypeRow) -> None:
    kwargs = {
        "employee": employee,
        "leave_type": leave_type,
        "date1": date(2025, 7, 1),
        "date2": date(2025, 7, 14),
    }
    LeaveAssign.objects.create(**kwargs)
    with pytest.raises(IntegrityError), transaction.atomic():
        LeaveAssign.objects.create(**kwargs)


@pytest.mark.django_db
def test_entitlement_negative_days_allowed(employee: Employee, leave_type: LeaveTypeRow) -> None:
    e = Entitlement.objects.create(
        employee=employee,
        leave_type=leave_type,
        date1=date(2025, 1, 1),
        date2=date(2025, 12, 31),
        ent_days=-3,
    )
    e.refresh_from_db()
    assert e.ent_days == -3
