"""Hire on Firebird through macs_writes.create_employee, with the real MACS triggers (plan 3, Task 5).

The MACS triggers set the employee ID, loginpass, birth year, status flags and the ERP customer row. A second hire
with the same given name and surname initial makes TR_EMPCUST fail (CUST_DSCX); create_employee then inserts with
hr_flag='no' and adds the suffixed customer row itself. Each scenario runs in a subprocess on the migrated clone and
reports a JSON result; the tests assert on it.
"""

from typing import Any

import pytest

from infohr_firebird.tests.test_settings_seam import result_of, run_django

HIRE_CODE = """
import json
import uuid
import datetime as dt
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection
from employees.models import EmployeeExt, Employee
from employees.services import macs_writes
from employees.services.macs_writes import EMPTYPE_FLAGS
User = get_user_model()
tag = uuid.uuid4().hex[:6]
by = User.objects.create_user(f"hire_{tag}", password="x-long-pass-123")

def values(register_no):
    return {
        "family_name": "Пробный",
        "given_name": "Бат",
        "gender": "M",
        "birth_date": dt.date(1990, 5, 17),
        "register_no": register_no,
        "first_hire_date": dt.date(2026, 1, 5),
        "work_conditions": 1,
    }

def customers(pk):
    with connection.cursor() as c:
        c.execute(
            "select cust_id, TRIM(description), TRIM(code), TRIM(employee), employee_ident, TRIM(register)"
            " from customer where employee_ident = %s order by cust_id",
            [pk],
        )
        return [list(row) for row in c.fetchall()]

def snapshot(employee):
    fresh = Employee.objects.get(pk=employee.pk)
    return {
        "pk": employee.pk,
        "loginpass": fresh.loginpass,
        "birth_year": fresh.birth_year,
        "fullname": fresh.fullname,
        "status": fresh.status,
        "contract_flag": fresh.contract_flag,
        "wagetest": fresh.wagetest,
        "emptype": fresh.emptype,
        "hr_flag": fresh.hr_flag,
        "code": fresh.code,
        "account_no": fresh.account_no,
        "in_memory_loginpass": employee.loginpass,
        "in_memory_status": employee.status,
        "ext_rows": EmployeeExt.objects.filter(employee_id=employee.pk).count(),
        "customers": customers(employee.pk),
    }

first = macs_writes.create_employee(values("УБ90051701"), {}, code="T5A001", by=by)
first_data = snapshot(first)
first_customers_before = first_data["customers"]
second = macs_writes.create_employee(values("УБ90051702"), {}, code="T5B002", by=by)
second_data = snapshot(second)
first_after = customers(first.pk)
print("RESULT " + json.dumps({
    "first": first_data,
    "second": second_data,
    "first_customers_unchanged": first_customers_before == first_after,
    "expected_flags": list(EMPTYPE_FLAGS[1]),
}))
"""


@pytest.fixture(scope="module")
def hired(migrated_clone: str) -> dict[str, Any]:
    return result_of(run_django(HIRE_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))


def test_hire_returns_pk_login_status_and_one_customer_row(hired: dict[str, Any]) -> None:
    first = hired["first"]
    assert isinstance(first["pk"], int) and first["pk"] > 0
    assert first["loginpass"] == str(first["pk"])
    assert first["in_memory_loginpass"] == str(first["pk"])
    assert "Пробный" in first["fullname"] and "Бат" in first["fullname"]
    assert first["status"] == "active"
    assert first["in_memory_status"] == "active"
    assert len(first["customers"]) == 1
    cust_id, description, _code, employee_flag, ident, _register = first["customers"][0]
    assert description == "Бат.П"
    assert employee_flag == "yes"
    assert ident == first["pk"]


def test_second_hire_with_same_name_gets_suffixed_customer(hired: dict[str, Any]) -> None:
    first, second = hired["first"], hired["second"]
    assert second["pk"] != first["pk"]
    assert second["hr_flag"] == "yes"
    assert len(second["customers"]) == 1
    assert second["customers"][0][1] == "Бат.П T5B002"
    assert second["customers"][0][4] == second["pk"]
    assert hired["first_customers_unchanged"] is True


def test_hire_creates_ext_row(hired: dict[str, Any]) -> None:
    assert hired["first"]["ext_rows"] == 1
    assert hired["second"]["ext_rows"] == 1


def test_birth_year_comes_from_birth_date(hired: dict[str, Any]) -> None:
    assert hired["first"]["birth_year"] == 1990
    assert hired["second"]["birth_year"] == 1990


def test_trigger_values_match_emptype_one(hired: dict[str, Any]) -> None:
    status, contract_flag, wagetest = hired["expected_flags"]
    for key in ("first", "second"):
        assert hired[key]["emptype"] == 1
        assert hired[key]["status"] == status
        assert hired[key]["contract_flag"] == contract_flag
        assert hired[key]["wagetest"] == wagetest


def test_customer_code_mapping_is_reported(hired: dict[str, Any]) -> None:
    """Concern, not a fix: the trigger copies EMPLOYEE.ECODE (HR account_no) into customer.code, while HR's
    employee.code is EMPNO. The first hire here has no account_no, so customer.code stays NULL."""
    first = hired["first"]
    assert first["code"] == "T5A001"
    assert first["account_no"] is None
    assert first["customers"][0][2] is None
