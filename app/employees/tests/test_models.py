from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from macs.models import EducRow, EduType, PresentRow, PresentType
from psycopg.types.range import DateRange

from employees.models import (
    ActivityEntry,
    ActivityKind,
    ChangeType,
    Department,
    DepartmentExt,
    EducationExt,
    Employee,
    EmployeeExt,
    GiftExt,
    JobRecord,
    Position,
    SalaryRecord,
    ensure_ext,
    normalize_register_no,
    validate_register_no,
)


@pytest.mark.django_db
def test_employee_is_the_production_table() -> None:
    assert Employee._meta.db_table == "employee"
    assert Department._meta.db_table == "deps"
    assert Position._meta.db_table == "occupation"


@pytest.mark.django_db
def test_ext_rows_live_in_hr_and_point_at_production_ids() -> None:
    e = Employee.objects.create(given_name="Сараа", family_name="Батын", birth_date=date(1999, 1, 1))
    ext = ensure_ext(e)
    assert ensure_ext(e) == ext
    assert EmployeeExt._meta.db_table == "employees_employeeext"
    assert e.ext.employee_id == e.pk
    d = Department.objects.create(name="Санхүү")
    DepartmentExt.objects.create(department=d)
    assert d.ext.active is True


@pytest.mark.django_db
def test_employee_permissions_belong_to_macs() -> None:
    codes = set(Permission.objects.filter(content_type__app_label="macs").values_list("codename", flat=True))
    assert {"view_employees", "manage_employees", "view_personal", "view_salary", "manage_salary"} <= codes
    assert not Permission.objects.filter(content_type__app_label="employees", codename="view_salary").exists()


def make_employee(**overrides: Any) -> Employee:
    data: dict[str, Any] = {"family_name": "Батын", "given_name": "Сараа", "birth_date": date(1999, 11, 22)}
    data.update(overrides)
    return Employee.objects.create(**data)


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
def test_btree_gist_installed() -> None:
    with connection.cursor() as cursor:
        cursor.execute("select 1 from pg_extension where extname = 'btree_gist'")
        assert cursor.fetchone() is not None


def test_register_no_normalised() -> None:
    assert normalize_register_no(" уб 99112233 ") == "УБ99112233"


@pytest.mark.parametrize("bad", ["УБ9911223", "UB99112233", "У99112233", "УББ9911223"])
def test_register_no_format_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        validate_register_no(bad)


@pytest.mark.django_db
def test_full_name() -> None:
    assert make_employee().full_name == "Батын Сараа"


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
    make_job(make_employee(given_name="Болд"), date(2026, 1, 1))


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
def test_view_salary_moved_to_macs_and_grants_kept() -> None:
    perm = Permission.objects.get(codename="view_salary")
    assert perm.content_type.app_label == "macs"
    assert Group.objects.get(name="Accountant").permissions.filter(pk=perm.pk).exists()
    assert Group.objects.get(name="Admin").permissions.filter(pk=perm.pk).exists()
    assert not Group.objects.get(name="HR").permissions.filter(pk=perm.pk).exists()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_view_salary_migration_carries_over_existing_grants() -> None:
    old_state = [("employees", "0001_initial"), ("accounts", "0002_role_groups")]
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
        Group.objects.get(name="HR").permissions.filter(codename="view_salary", content_type__app_label="macs").exists()
    )
    carried = Permission.objects.get(codename="view_salary", content_type__app_label="macs")
    assert carried.user_set.filter(username="carry").exists()
    assert not Permission.objects.filter(codename="view_salary", content_type__app_label="accounts").exists()


@pytest.mark.django_db
def test_education_ext_keyed_by_educ_id() -> None:
    emp = make_employee()
    row = EducRow.objects.create(employee=emp, edu_type=EduType.objects.create(name="Бакалавр"), start_year=2010)
    ext = EducationExt.objects.create(educ=row, school="МУИС", field="Нягтлан", graduation_year=2014)
    assert ext.pk == row.pk
    assert EducationExt._meta.pk.column == "educ_id"
    assert row.ext.school == "МУИС"


@pytest.mark.django_db
def test_gift_ext_keyed_by_present_id() -> None:
    emp = make_employee()
    row = PresentRow.objects.create(
        employee=emp,
        childqty=1,
        price=1000,
        given_year=2026,
        pdate=date(2026, 3, 1),
        present_type=PresentType.objects.create(name="Төрсөн өдөр"),
        child_age=5,
        given=1,
    )
    ext = GiftExt.objects.create(present=row, note="Бэлэг")
    assert ext.pk == row.pk
    assert GiftExt._meta.pk.column == "present_id"
    assert row.ext.note == "Бэлэг"


def test_old_personal_models_gone() -> None:
    import employees.models as models

    for name in ("FamilyMember", "Education", "Talent", "Gift"):
        assert hasattr(models, name) is False
    fields = {f.name for f in EmployeeExt._meta.get_fields()}
    assert not {"address", "emergency_name", "emergency_phone"} & fields
