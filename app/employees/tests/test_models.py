from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from psycopg.types.range import DateRange

from employees.models import (
    ActivityEntry,
    ActivityKind,
    ChangeType,
    Department,
    Employee,
    JobRecord,
    Position,
    SalaryRecord,
)
from employees.validators import normalize_register_no, validate_register_no


@pytest.mark.django_db
def test_btree_gist_installed() -> None:
    with connection.cursor() as cursor:
        cursor.execute("select 1 from pg_extension where extname = 'btree_gist'")
        assert cursor.fetchone() is not None


@pytest.mark.django_db
def test_reference_lists_order_by_name() -> None:
    Department.objects.create(name="Санхүү")
    Department.objects.create(name="Борлуулалт")
    Position.objects.create(name="Нягтлан", active=False)
    assert [d.name for d in Department.objects.all()] == ["Борлуулалт", "Санхүү"]
    assert Position.objects.get().active is False


def make_employee(**overrides: object) -> Employee:
    data: dict[str, object] = {
        "code": Employee.next_code(),
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": "УБ99112233",
        "birth_date": date(1999, 11, 22),
        "gender": "female",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
    }
    data.update(overrides)
    return Employee.objects.create(**data)


def test_register_no_normalised() -> None:
    assert normalize_register_no(" уб 99112233 ") == "УБ99112233"


@pytest.mark.parametrize("bad", ["УБ9911223", "UB99112233", "У99112233", "УББ9911223"])
def test_register_no_format_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        validate_register_no(bad)


@pytest.mark.django_db
def test_next_code_increments() -> None:
    assert Employee.next_code() == "E0001"
    make_employee()
    assert Employee.next_code() == "E0002"


@pytest.mark.django_db
def test_register_no_unique_after_normalising() -> None:
    make_employee()
    duplicate = Employee(
        code="E0099",
        family_name="А",
        given_name="Б",
        register_no="уб 99112233",
        birth_date=date(2000, 1, 1),
        gender="male",
        work_phone="1",
        first_hire_date=date(2026, 1, 1),
    )
    with pytest.raises(ValidationError) as exc:
        duplicate.full_clean()
    errors = exc.value.error_dict["register_no"]
    assert [e.code for e in errors] == ["unique"]


@pytest.mark.django_db
def test_spaced_register_no_accepted() -> None:
    employee = Employee(
        code="E0050",
        family_name="А",
        given_name="Б",
        register_no="уб 88010122",
        birth_date=date(1988, 1, 1),
        gender="male",
        work_phone="1",
        first_hire_date=date(2026, 1, 1),
    )
    employee.full_clean()
    employee.save()
    employee.refresh_from_db()
    assert employee.register_no == "УБ88010122"


@pytest.mark.django_db
def test_create_normalises_register_no() -> None:
    assert make_employee(register_no="уб99112233").register_no == "УБ99112233"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_view_salary_migration_carries_over_existing_grants() -> None:
    old_state = [
        ("employees", "0002_employee_education_familymember_salaryinsurance"),
        ("accounts", "0005_alter_user_options"),
    ]
    executor = MigrationExecutor(connection)
    executor.migrate(old_state)
    try:
        apps = executor.loader.project_state(old_state).apps
        content_type = apps.get_model("contenttypes", "ContentType").objects.get_or_create(
            app_label="accounts", model="user"
        )[0]
        old = apps.get_model("auth", "Permission").objects.get_or_create(
            codename="view_salary", content_type=content_type, defaults={"name": "old"}
        )[0]
        hr = apps.get_model("auth", "Group").objects.get(name="HR")
        hr.permissions.add(old)
        user = apps.get_model("accounts", "User").objects.create(username="carry")
        user.user_permissions.add(old)
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    assert (
        Group.objects.get(name="HR")
        .permissions.filter(codename="view_salary", content_type__app_label="employees")
        .exists()
    )
    carried = Permission.objects.get(codename="view_salary", content_type__app_label="employees")
    assert carried.user_set.filter(username="carry").exists()
    assert not Permission.objects.filter(codename="view_salary", content_type__app_label="accounts").exists()


@pytest.mark.django_db
def test_full_name() -> None:
    assert make_employee().full_name == "Батын Сараа"


@pytest.mark.django_db
def test_view_salary_moved_to_employees_and_grants_kept() -> None:
    perm = Permission.objects.get(codename="view_salary")
    assert perm.content_type.app_label == "employees"
    assert Group.objects.get(name="Accountant").permissions.filter(pk=perm.pk).exists()
    assert Group.objects.get(name="Admin").permissions.filter(pk=perm.pk).exists()
    assert not Group.objects.get(name="HR").permissions.filter(pk=perm.pk).exists()


def make_job(employee: Employee, lower: date, upper: date | None = None) -> JobRecord:
    return JobRecord.objects.create(
        employee=employee,
        period=DateRange(lower, upper, "[)"),
        position=Position.objects.get_or_create(name="Нягтлан")[0],
        department=Department.objects.get_or_create(name="Санхүү")[0],
        employee_type="full_time",
        status="active",
        contract_type="open_ended",
        change_type=ChangeType.HIRE,
    )


@pytest.mark.django_db
def test_job_periods_may_touch_but_not_overlap() -> None:
    emp = make_employee()
    make_job(emp, date(2026, 1, 1), date(2026, 3, 1))
    make_job(emp, date(2026, 3, 1))  # touching is fine: [) bounds
    with pytest.raises(IntegrityError), transaction.atomic():
        make_job(emp, date(2026, 2, 1), date(2026, 2, 10))


@pytest.mark.django_db
def test_salary_periods_do_not_overlap() -> None:
    emp = make_employee()
    SalaryRecord.objects.create(
        employee=emp,
        period=DateRange(date(2026, 1, 1), None, "[)"),
        base_salary=Decimal("2500000.00"),
        change_type=ChangeType.HIRE,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        SalaryRecord.objects.create(
            employee=emp,
            period=DateRange(date(2026, 5, 1), None, "[)"),
            base_salary=Decimal("1"),
            change_type=ChangeType.HIRE,
        )


@pytest.mark.django_db
def test_other_employees_may_share_dates() -> None:
    make_job(make_employee(), date(2026, 1, 1))
    make_job(make_employee(code="E0002", register_no="УБ00000001"), date(2026, 1, 1))


@pytest.mark.django_db
def test_activity_is_append_only() -> None:
    entry = ActivityEntry.objects.create(employee=make_employee(), kind=ActivityKind.NOTE, message="x")
    entry.message = "y"
    with pytest.raises(PermissionError):
        entry.save()
    with pytest.raises(PermissionError):
        entry.delete()
    with pytest.raises(PermissionError):
        ActivityEntry.objects.all().update(message="z")
    with pytest.raises(PermissionError):
        ActivityEntry.objects.all().delete()


@pytest.mark.django_db
def test_history_is_read_only_in_admin(admin_client: Any) -> None:
    assert admin_client.get("/admin/employees/department/add/").status_code == 200
    assert admin_client.get("/admin/employees/jobrecord/add/").status_code == 403
    assert admin_client.get("/admin/employees/activityentry/add/").status_code == 403


@pytest.mark.django_db
def test_other_fields_round_trip_and_personal_split() -> None:
    from employees.models import PERSONAL_FIELDS

    from .conftest import new_employee

    values = {
        "blood_type": "II+",
        "social_origin": "Ажилчин",
        "military_service": "served",
        "housing_condition": "Өөрийн байр",
        "living_standard": "Дунд",
        "car_ownership": "Байхгүй",
        "clothing_size": "M",
        "shoe_size": "42",
        "elected_position": "Хорооны төлөөлөгч",
    }
    employee = new_employee()
    for name, value in values.items():
        setattr(employee, name, value)
    employee.save()
    employee.refresh_from_db()
    assert {name: getattr(employee, name) for name in values} == values
    assert PERSONAL_FIELDS >= set(values)  # all "other" fields are personal (D-010 as changed 2026-10-15)
