from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from lists.usage import usage_count
from macs.models import EmployeeHistory, Movement

from employees.models import Department, DepartmentExt, Employee, Position, PositionExt
from employees.services import macs_writes


@pytest.fixture
def admin_client(client: Client, db: None) -> Client:
    client.force_login(User.objects.create_superuser("root", password="Root-pass-1"))  # noqa: S106
    return client


@pytest.mark.django_db
def test_admin_creates_department_with_ext(admin_client: Client) -> None:
    response = admin_client.post("/admin/macs/department/add/", {"name": "Санхүү", "active": "on"})
    assert response.status_code == 302
    assert Department.objects.get(name="Санхүү").ext.active


@pytest.mark.django_db
def test_admin_creates_position_with_ext(admin_client: Client) -> None:
    response = admin_client.post("/admin/macs/position/add/", {"name": "Нягтлан", "active": ""})
    assert response.status_code == 302
    assert PositionExt.objects.get(position__name="Нягтлан").active is False


@pytest.mark.django_db
def test_department_in_use_cannot_be_deleted(admin_client: Client, hired: Any) -> None:
    dep = hired.department
    response = admin_client.post(f"/admin/macs/department/{dep.pk}/delete/", {"post": "yes"})
    assert Department.objects.filter(pk=dep.pk).exists()
    assert response.status_code == 403


@pytest.mark.django_db
def test_unused_department_deleted_with_its_ext() -> None:
    dep = macs_writes.save_department("Туршилт")
    assert DepartmentExt.objects.filter(department=dep).exists()
    macs_writes.delete_department(dep)
    assert not Department.objects.filter(pk=dep.pk).exists()
    assert not DepartmentExt.objects.filter(department_id=dep.pk).exists()


@pytest.mark.django_db
def test_used_position_refused_by_service(hired: Any) -> None:
    position = hired.position
    with pytest.raises(ValueError):
        macs_writes.delete_position(position)
    assert Position.objects.filter(pk=position.pk).exists()


def _other_dep() -> Department:
    return macs_writes.save_department("Өөр хэлтэс")


def _other_pos() -> Position:
    return macs_writes.save_position("Өөр тушаал")


@pytest.mark.django_db
def test_usage_counts_department_in_history_only(hired: Any) -> None:
    dep = hired.department
    macs_writes.snapshot_history(hired)
    Employee.objects.filter(pk=hired.pk).update(department=_other_dep())
    assert EmployeeHistory.objects.filter(department_id_value=dep.pk).exists()
    assert usage_count(Department, dep.pk, exclude_tables=[DepartmentExt._meta.db_table]) > 0
    with pytest.raises(ValueError):
        macs_writes.delete_department(dep)
    assert Department.objects.filter(pk=dep.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["old_department_id_value", "new_department_id_value"])
def test_usage_counts_department_in_movement_only(hired: Any, field: str) -> None:
    dep = hired.department
    Movement.objects.create(
        employee=hired,
        kind="dep",
        date="2026-02-01",
        **{field: dep.pk},
    )
    assert usage_count(Department, dep.pk, exclude_tables=[DepartmentExt._meta.db_table]) > 0
    with pytest.raises(ValueError):
        macs_writes.delete_department(dep)
    assert Department.objects.filter(pk=dep.pk).exists()


@pytest.mark.django_db
def test_usage_counts_department_of_former_employee(hired: Any) -> None:
    # Job records keep the original department; only the (left) employee row points at the new one.
    dep = _other_dep()
    Employee.objects.filter(pk=hired.pk).update(department=dep, status="inactive")
    assert usage_count(Department, dep.pk, exclude_tables=[DepartmentExt._meta.db_table]) > 0
    with pytest.raises(ValueError):
        macs_writes.delete_department(dep)
    assert Department.objects.filter(pk=dep.pk).exists()


@pytest.mark.django_db
def test_usage_counts_position_in_history_only(hired: Any) -> None:
    position = hired.position
    macs_writes.snapshot_history(hired)
    Employee.objects.filter(pk=hired.pk).update(position=_other_pos())
    assert EmployeeHistory.objects.filter(position_id_value=position.pk).exists()
    assert usage_count(Position, position.pk, exclude_tables=[PositionExt._meta.db_table]) > 0
    with pytest.raises(ValueError):
        macs_writes.delete_position(position)
    assert Position.objects.filter(pk=position.pk).exists()
