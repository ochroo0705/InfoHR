"""Contacts, addresses and the ERP customer row on Firebird (plan 3, Task 8).

The MACS triggers do part of the work: CONTACTING_AI0 (contact type 4 -> employee.email, type 2 -> employee.homephone),
CONTACTING_AU0 (type 2 only, on update) and ADDRESS_BI (a new address copies its street to every customer row of the
employee). HR refreshes the employee instance it was given instead of writing those values a second time, and skips
its own customer copy on address insert. Address update has no trigger, so HR still copies there.

Each scenario runs in a subprocess on the migrated clone (the same pattern as test_write_hire.py) and reports one JSON
result. Python UPDATE statements are counted with CaptureQueriesContext, so a second write by HR shows up as a count.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

PERSONAL_CODE = """
import json
import re
import uuid
import datetime as dt
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from employees.models import Employee
from employees.services import macs_writes, personal_writes
from macs.models import City, ContactRow, ContactType, District
User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"pw_{tag}", password="x-long-pass-123")
STREET = "Баянзүрх, 5-р хороо"
NEW_STREET = "Шинэ гудамж 7"

for pk, label in ((2, "Утас"), (3, "Бусад"), (4, "Имэйл")):
    if not ContactType.objects.filter(pk=pk).exists():
        ContactType.objects.create(pk=pk, name=label)

def values(n, register):
    return {
        "family_name": "Тест",
        "given_name": f"Пв{tag}{n}",
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": register,
        "first_hire_date": dt.date(2026, 1, 5),
        "work_conditions": 1,
    }

def hire(n, register):
    return macs_writes.create_employee(values(n, register), {}, code=f"PW{tag}{n}", by=by)

def hire_without_customer(n):
    e = Employee(**values(n, f"УБ9007{n:04d}"))
    e.code = f"PX{tag}{n}"
    e.hr_flag = "no"
    e.sector_years = 0
    e.emptype = 1
    e.save(force_insert=True)
    return e

def db_employee(pk):
    with connection.cursor() as c:
        c.execute("select TRIM(email), TRIM(homephone), TRIM(registerno) from employee where employee_id = %s", [pk])
        email, homephone, registerno = c.fetchone()
    return {"email": email, "homephone": homephone, "registerno": registerno}

def customer_addresses(pk):
    with connection.cursor() as c:
        c.execute(
            "select TRIM(address) from customer where employee_ident = %s and employee = 'yes' order by cust_id", [pk]
        )
        return [row[0] for row in c.fetchall()]

def updates_of(ctx, table):
    pattern = re.compile(r'^\\s*UPDATE\\s+"?' + table + r'"?\\s', re.IGNORECASE)
    return [q["sql"] for q in ctx.captured_queries if pattern.match(q["sql"])]

def contact_values(type_id, value):
    return {"contact_type_id": type_id, "value": value, "name": "Дорж", "relative": "Ах"}

def scen_contact_add():
    emp = hire(1, "УБ90051801")
    out = {"before": db_employee(emp.pk)}
    with CaptureQueriesContext(connection) as ctx:
        personal_writes.add("contact", emp, contact_values(4, "mail@example.mn"), {}, by=by)
    out["type4"] = {
        "in_memory_email": emp.email,
        "db_email": db_employee(emp.pk)["email"],
        "employee_updates_by_hr": len(updates_of(ctx, "employee")),
        "captured": len(ctx.captured_queries),
    }
    with CaptureQueriesContext(connection) as ctx:
        personal_writes.add("contact", emp, contact_values(2, "99112233"), {}, by=by)
    out["type2"] = {
        "in_memory_homephone": emp.private_phone,
        "db_homephone": db_employee(emp.pk)["homephone"],
        "employee_updates_by_hr": len(updates_of(ctx, "employee")),
        "captured": len(ctx.captured_queries),
    }
    with CaptureQueriesContext(connection) as ctx:
        personal_writes.add("contact", emp, contact_values(3, "77001122"), {}, by=by)
    out["type3"] = {
        "in_memory_email": emp.email,
        "in_memory_homephone": emp.private_phone,
        "db": db_employee(emp.pk),
        "employee_updates_by_hr": len(updates_of(ctx, "employee")),
        "captured": len(ctx.captured_queries),
    }
    return out

def scen_contact_update():
    emp = hire(2, "УБ90051802")
    key = personal_writes.add("contact", emp, contact_values(3, "55555555"), {}, by=by)
    loaded = personal_writes.load("contact", emp, key)
    with CaptureQueriesContext(connection) as ctx:
        personal_writes.update("contact", emp, key, loaded, contact_values(2, "88001122"), {}, by=by)
    return {
        "in_memory_homephone": emp.private_phone,
        "db_homephone": db_employee(emp.pk)["homephone"],
        "employee_updates_by_hr": len(updates_of(ctx, "employee")),
        "captured": len(ctx.captured_queries),
    }

def scen_address():
    emp = hire(3, "УБ90051803")
    city = City.objects.order_by("pk").first()
    district = District.objects.filter(city=city).order_by("pk").first()
    address = {"street": STREET, "city_id": city.pk, "district_id": district.pk}
    out = {"before": customer_addresses(emp.pk)}
    with CaptureQueriesContext(connection) as ctx:
        key = personal_writes.add("address", emp, address, {}, by=by)
    out["add"] = {
        "customer_addresses": customer_addresses(emp.pk),
        "customer_updates_by_hr": len(updates_of(ctx, "customer")),
        "captured": len(ctx.captured_queries),
    }
    loaded = personal_writes.load("address", emp, key)
    with CaptureQueriesContext(connection) as ctx:
        personal_writes.update("address", emp, key, loaded, {"street": NEW_STREET}, {}, by=by)
    out["update"] = {
        "customer_addresses": customer_addresses(emp.pk),
        "customer_updates_by_hr": len(updates_of(ctx, "customer")),
        "captured": len(ctx.captured_queries),
    }
    return out

def scen_address_without_customer():
    emp = hire_without_customer(4)
    city = City.objects.order_by("pk").first()
    district = District.objects.filter(city=city).order_by("pk").first()
    with connection.cursor() as c:
        c.execute("select count(*) from customer where employee_ident = %s", [emp.pk])
        before = c.fetchone()[0]
    personal_writes.add("address", emp, {"street": STREET, "city_id": city.pk, "district_id": district.pk}, {}, by=by)
    with connection.cursor() as c:
        c.execute("select count(*) from customer where employee_ident = %s", [emp.pk])
        after = c.fetchone()[0]
    return {"customer_rows_before": before, "customer_rows_after": after}

def scen_register_caveat():
    emp = hire(5, "УБ90051805")
    out = {"after_hire": db_employee(emp.pk)["registerno"]}
    city = City.objects.order_by("pk").first()
    district = District.objects.filter(city=city).order_by("pk").first()
    address = {"street": STREET, "city_id": city.pk, "district_id": district.pk}
    key = personal_writes.add("address", emp, address, {}, by=by)
    out["after_address_add"] = db_employee(emp.pk)["registerno"]
    loaded = personal_writes.load("address", emp, key)
    personal_writes.update("address", emp, key, loaded, {"street": NEW_STREET}, {}, by=by)
    out["after_address_update"] = db_employee(emp.pk)["registerno"]
    return out

def scen_contact_length():
    emp = hire(6, "УБ90051806")
    def contact_rows():
        return ContactRow.objects.filter(employee=emp).count()
    rows_before = contact_rows()
    phone_before = db_employee(emp.pk)["homephone"]
    out = {}
    try:
        personal_writes.add("contact", emp, contact_values(2, "12345678901234567890"), {}, by=by)
        out["long_error"] = None
    except personal_writes.PersonalConflict as exc:
        out["long_error"] = str(exc)
    out["long_rows_delta"] = contact_rows() - rows_before
    out["long_homephone_unchanged"] = db_employee(emp.pk)["homephone"] == phone_before
    personal_writes.add("contact", emp, contact_values(2, "11223344556677"), {}, by=by)
    out["ok_homephone"] = db_employee(emp.pk)["homephone"]
    out["ok_rows_delta"] = contact_rows() - rows_before
    return out

RESULT = {}
for name, scenario in (
    ("contact_add", scen_contact_add),
    ("contact_update", scen_contact_update),
    ("address", scen_address),
    ("address_without_customer", scen_address_without_customer),
    ("register_caveat", scen_register_caveat),
    ("contact_length", scen_contact_length),
):
    try:
        RESULT[name] = scenario()
    except Exception as exc:
        RESULT[name] = {"error": f"{type(exc).__name__}: {exc}"}
print("RESULT " + json.dumps(RESULT))
"""


@pytest.fixture(scope="module")
def personal(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(PERSONAL_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_contact_type_4_sets_employee_email_once_by_trigger(personal: dict[str, Any]) -> None:
    """(a) type 4 -> employee.email; the instance is refreshed; HR issues no UPDATE of employee itself."""
    row = personal["contact_add"]["type4"]
    assert "error" not in personal["contact_add"], personal["contact_add"]
    assert row["captured"] > 0, "query capture did not record anything; the zero-count check would be vacuous"
    assert row["db_email"] == "mail@example.mn"
    assert row["in_memory_email"] == "mail@example.mn"
    assert row["employee_updates_by_hr"] == 0


def test_contact_type_2_sets_employee_homephone_once_by_trigger(personal: dict[str, Any]) -> None:
    """(a) type 2 -> employee.homephone; the instance is refreshed; HR issues no UPDATE of employee itself."""
    row = personal["contact_add"]["type2"]
    assert row["captured"] > 0
    assert row["db_homephone"] == "99112233"
    assert row["in_memory_homephone"] == "99112233"
    assert row["employee_updates_by_hr"] == 0


def test_other_contact_type_leaves_email_and_phone_alone(personal: dict[str, Any]) -> None:
    """(a) a type that is neither 2 nor 4 changes neither employee.email nor employee.homephone."""
    row = personal["contact_add"]["type3"]
    assert row["db"]["email"] == "mail@example.mn"
    assert row["db"]["homephone"] == "99112233"
    assert row["in_memory_email"] == "mail@example.mn"
    assert row["in_memory_homephone"] == "99112233"
    assert row["employee_updates_by_hr"] == 0


def test_update_to_type_2_moves_homephone(personal: dict[str, Any]) -> None:
    """(b) CONTACTING_AU0: a type 2 row updated to a new value sets employee.homephone; HR does not write it."""
    row = personal["contact_update"]
    assert "error" not in row, row
    assert row["captured"] > 0
    assert row["db_homephone"] == "88001122"
    assert row["in_memory_homephone"] == "88001122"
    assert row["employee_updates_by_hr"] == 0


def test_address_add_copies_street_to_customer_by_trigger(personal: dict[str, Any]) -> None:
    """(c) ADDRESS_BI copies the street (cut to 90) to customer.address; HR does not copy it a second time."""
    row = personal["address"]
    assert "error" not in row, row
    assert row["add"]["captured"] > 0
    assert row["add"]["customer_addresses"] == ["Баянзүрх, 5-р хороо"[:90]]
    assert row["add"]["customer_updates_by_hr"] == 0


def test_address_update_copies_street_to_customer_in_python(personal: dict[str, Any]) -> None:
    """(c) no update trigger exists, so the Python copy stays on address update."""
    row = personal["address"]["update"]
    assert row["customer_addresses"] == ["Шинэ гудамж 7"]
    assert row["customer_updates_by_hr"] == 1


def test_address_without_customer_row_creates_nothing(personal: dict[str, Any]) -> None:
    """(d) an employee without an ERP customer row: the address is saved, no customer row appears."""
    row = personal["address_without_customer"]
    assert "error" not in row, row
    assert row["customer_rows_before"] == 0
    assert row["customer_rows_after"] == 0


def test_type_2_contact_longer_than_phone_column_is_refused_before_any_write(personal: dict[str, Any]) -> None:
    """(I-1) a 20-character type-2 value is refused with the user-facing text; no contact row, no employee change."""
    row = personal["contact_length"]
    assert "error" not in row, row
    assert row["long_error"] == "Утасны дугаар хэт урт байна (дээд тал нь 14 тэмдэгт)."
    assert row["long_rows_delta"] == 0
    assert row["long_homephone_unchanged"] is True


def test_type_2_contact_of_14_characters_is_accepted(personal: dict[str, Any]) -> None:
    """(I-1) a 14-character type-2 value fits homephone: it is saved and copied by the trigger."""
    row = personal["contact_length"]
    assert row["ok_homephone"] == "11223344556677"
    assert row["ok_rows_delta"] == 1


def test_register_number_survives_customer_copies(personal: dict[str, Any]) -> None:
    """Caveat, tested not fixed: TR_CUSTID / TR_UPDCUSTOMER copy customer.register into employee.registerno for
    employee='yes' rows. An address save on an employee with a register number must leave the number unchanged."""
    row = personal["register_caveat"]
    assert "error" not in row, row
    assert row["after_hire"] == "УБ90051805"
    assert row["after_address_add"] == "УБ90051805"
    assert row["after_address_update"] == "УБ90051805"
