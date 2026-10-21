"""MACS keeps employee.fullname as RPAD(surname, 25) + ', ' + name, and it never rewrites that value or the
derived dates/year on an unrelated edit (QC 3a, 3b)."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.db.models import QuerySet

from employees.models import Employee
from employees.services import macs_writes


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("w_name_actor", password="x-long-pass-123")  # noqa: S106


def _padded(surname: str | None, given: str) -> str:
    return f"{(surname or '').ljust(25)}, {given}"


def _create(actor: User, **extra: Any) -> Employee:
    values: dict[str, Any] = {
        "given_name": "Сараа",
        "family_name": "Батын",
        "register_no": "УБ99112233",
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
        **extra,
    }
    return macs_writes.create_employee(values, {}, code=macs_writes.next_code(), by=actor)


def _columns(qs: QuerySet[Employee]) -> dict[str, Any]:
    return dict(
        qs.values("fullname", "birth_year", "birth_date", "first_hire_date", "contract_start", "work_phone").get()
    )


def _legacy(employee: Employee, **columns: Any) -> None:
    """Make the row look like a MACS-only row: the stored derived values are whatever MACS wrote."""
    Employee.objects.filter(pk=employee.pk).update(**columns)


@pytest.mark.django_db
def test_create_writes_fullname_padded_to_25(actor: User) -> None:
    e = _create(actor)
    e.refresh_from_db()
    assert e.fullname == _padded("Батын", "Сараа")
    assert len(e.fullname.split(",")[0]) == 25
    assert e.birth_year == 1999


@pytest.mark.django_db
def test_create_with_no_surname_pads_25_spaces(actor: User) -> None:
    e = _create(actor, family_name=None)
    e.refresh_from_db()
    assert e.fullname == " " * 25 + ", Сараа"


@pytest.mark.django_db
def test_hire_still_fills_contract_start_on_create(actor: User) -> None:
    e = _create(actor)
    e.refresh_from_db()
    assert e.contract_start == date(2026, 1, 5)


@pytest.mark.django_db
@pytest.mark.parametrize("stored_fullname", ["Old Format, Сараа", None])
def test_unrelated_update_leaves_legacy_columns_identical(actor: User, stored_fullname: str | None) -> None:
    e = _create(actor)
    _legacy(e, fullname=stored_fullname, contract_start=None, birth_year=1980, first_hire_date=date(2010, 3, 1))
    before = _columns(Employee.objects.filter(pk=e.pk))

    e.refresh_from_db()
    macs_writes.update_employee_columns(e, {"work_phone": "88001122"})

    after = _columns(Employee.objects.filter(pk=e.pk))
    assert after["work_phone"] == "88001122"
    for name in ("fullname", "birth_year", "first_hire_date", "contract_start", "birth_date"):
        assert after[name] == before[name], name
    assert after["fullname"] == stored_fullname
    assert after["contract_start"] is None


@pytest.mark.django_db
def test_update_does_not_copy_first_hire_into_contract_start(actor: User) -> None:
    e = _create(actor)
    _legacy(e, contract_start=None)
    e.refresh_from_db()
    macs_writes.update_employee_columns(e, {"first_hire_date": date(2012, 5, 1)})
    e.refresh_from_db()
    assert e.first_hire_date == date(2012, 5, 1)
    assert e.contract_start is None


@pytest.mark.django_db
def test_changing_surname_rewrites_fullname_padded(actor: User) -> None:
    e = _create(actor)
    _legacy(e, fullname="Old Format, Сараа", contract_start=None)
    e.refresh_from_db()
    macs_writes.update_employee_columns(e, {"family_name": "Дорж"})
    e.refresh_from_db()
    assert e.fullname == _padded("Дорж", "Сараа")
    assert e.contract_start is None


@pytest.mark.django_db
def test_changing_given_name_rewrites_fullname_padded(actor: User) -> None:
    e = _create(actor)
    e.refresh_from_db()
    macs_writes.update_employee_columns(e, {"given_name": "Номин"})
    e.refresh_from_db()
    assert e.fullname == _padded("Батын", "Номин")


@pytest.mark.django_db
def test_changing_birth_date_recomputes_only_birth_year(actor: User) -> None:
    e = _create(actor)
    _legacy(e, birth_year=1980)
    e.refresh_from_db()
    macs_writes.update_employee_columns(e, {"birth_date": date(2001, 2, 3)})
    e.refresh_from_db()
    assert e.birth_year == 2001
    assert e.fullname == _padded("Батын", "Сараа")
