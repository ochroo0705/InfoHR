"""The ERP customer row a hire creates (old trigger TR_EMPCUST) and the address copied onto it (ADDRESS_BI), D-024."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.db import connection
from macs.models import City, District

from employees.services import history, macs_writes
from employees.services import personal_writes as pw

from .conftest import hire_values

pytestmark = pytest.mark.django_db

COLUMNS = ("cust_id", "description", "code", "passport", "register", "employee", "address", "tax", "isorg")
SELECT_ROWS = (
    "select cust_id, description, code, passport, register, employee, address, tax, isorg"
    " from customer where employee_ident = %s"
)


def _rows(employee: Any) -> list[dict[str, Any]]:
    with connection.cursor() as c:
        c.execute(SELECT_ROWS, [employee.pk])
        return [dict(zip(COLUMNS, row, strict=True)) for row in c.fetchall()]


def _drop_rows(employee: Any) -> None:
    with connection.cursor() as c:
        c.execute("delete from customer where employee_ident = %s", [employee.pk])


def _create(actor: User, **extra: object):  # type: ignore[no-untyped-def]
    values = {**hire_values(str(extra.pop("register_no", "УБ99112233"))), **extra}
    return macs_writes.create_employee(values, {}, code=macs_writes.next_code(), by=actor)


@pytest.fixture
def place() -> dict[str, Any]:
    city = City.objects.create(name="Улаанбаатар")
    return {"city": city, "district": District.objects.create(name="Баянгол", city=city)}


def _address(place: dict[str, Any], street: str | None) -> dict[str, Any]:
    return {"city_id": place["city"].pk, "district_id": place["district"].pk, "street": street}


# Task 1: the row at hire


def test_hire_creates_customer_row(actor: User) -> None:
    employee = _create(actor, passport_no="AB123")
    [row] = _rows(employee)
    assert row["description"] == "Сараа.Б"
    assert row["code"] == employee.code
    assert row["passport"] == "AB123"
    assert row["register"] == "УБ99112233"
    assert row["employee"] == "yes"
    assert row["address"] is None
    assert row["tax"] == 0
    assert row["isorg"] == "no"


def test_create_customer_row_returns_the_id(actor: User) -> None:
    employee = _create(actor)
    _drop_rows(employee)
    cust_id = macs_writes.create_customer_row(employee)
    assert cust_id == _rows(employee)[0]["cust_id"]


def test_duplicate_description_gets_code_suffix(actor: User) -> None:
    first = _create(actor)
    second = _create(actor, register_no="УБ88112233")
    assert _rows(first)[0]["description"] == "Сараа.Б"
    assert _rows(second)[0]["description"] == f"Сараа.Б {second.code}"


def test_suffixed_name_also_taken_gets_a_counter(actor: User) -> None:
    code = macs_writes.next_code()
    with connection.cursor() as c:  # ERP rows typed by hand: the plain and the suffixed name are both taken
        for description in ("Сараа.Б", f"Сараа.Б {code}"):
            c.execute("insert into customer (description, employee) values (%s, 'no')", [description])
    employee = _create(actor)
    assert employee.code == code
    assert _rows(employee)[0]["description"] == f"Сараа.Б {code}-2"


def test_empty_family_name(actor: User) -> None:
    employee = _create(actor, family_name="")
    assert _rows(employee)[0]["description"] == "Сараа."


def test_no_second_row(actor: User) -> None:
    employee = _create(actor)
    assert macs_writes.create_customer_row(employee) is None
    assert len(_rows(employee)) == 1


def test_not_active_is_skipped(actor: User) -> None:
    employee = _create(actor)
    _drop_rows(employee)
    macs_writes.update_employee_columns(employee, {"status": "inactive"})
    assert macs_writes.create_customer_row(employee) is None
    assert _rows(employee) == []


# Task 2: the address copy


def test_address_add_copies_street(actor: User, place: dict[str, Any]) -> None:
    employee = _create(actor)
    pw.add("address", employee, _address(place, "1-р хороо, 5-р байр"), {}, by=actor)
    assert _rows(employee)[0]["address"] == "1-р хороо, 5-р байр"


def test_address_update_copies_street(actor: User, place: dict[str, Any]) -> None:
    employee = _create(actor)
    key = pw.add("address", employee, _address(place, "Хуучин"), {}, by=actor)
    loaded = pw.load("address", employee, key)
    assert loaded is not None
    pw.update("address", employee, key, loaded, {"street": "Шинэ хаяг"}, {}, by=actor)
    assert _rows(employee)[0]["address"] == "Шинэ хаяг"


def test_empty_street_keeps_customer_address(actor: User, place: dict[str, Any]) -> None:
    employee = _create(actor)
    key = pw.add("address", employee, _address(place, "Хуучин"), {}, by=actor)
    loaded = pw.load("address", employee, key)
    assert loaded is not None
    pw.update("address", employee, key, loaded, {"street": None}, {}, by=actor)
    assert _rows(employee)[0]["address"] == "Хуучин"


def test_long_street_truncated(actor: User) -> None:
    employee = _create(actor)
    macs_writes.copy_address_to_customer(employee, "х" * 120)
    assert _rows(employee)[0]["address"] == "х" * 90


def test_hire_with_address_fills_customer_address(
    actor: User, job_values: dict[str, Any], place: dict[str, Any]
) -> None:
    employee = history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=None,
        by=actor,
        address=_address(place, "Төв"),
    )
    assert _rows(employee)[0]["address"] == "Төв"


def test_address_without_customer_row_is_noop(actor: User, place: dict[str, Any]) -> None:
    employee = _create(actor)
    _drop_rows(employee)
    pw.add("address", employee, _address(place, "Төв"), {}, by=actor)
    assert _rows(employee) == []
