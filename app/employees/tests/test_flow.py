from decimal import Decimal

import pytest
from django.test import Client

from employees.models import ActivityEntry, Department, Employee, Position

from .test_views import login_as

pytestmark = pytest.mark.django_db


def test_end_to_end_flow(client: Client) -> None:
    position = Position.objects.create(name="Нягтлан")
    department = Department.objects.create(name="Санхүү")

    # 1. HR adds an employee (no salary: HR cannot manage salary)
    hr = login_as(client, "HR", "hr1")
    response = client.post(
        "/employees/new/",
        {
            "family_name": "Батын",
            "given_name": "Сараа",
            "register_no": "уб 99112233",
            "birth_date": "1999-11-22",
            "gender": "female",
            "work_phone": "99112233",
            "citizenship": "Монгол",
            "first_hire_date": "2026-01-05",
            "work_conditions": "normal",
            "prior_service_years": "0",
            "prior_service_months": "0",
            "start": "2026-01-05",
            "position": position.pk,
            "department": department.pk,
            "employee_type": "full_time",
            "status": "active",
            "contract_type": "open_ended",
            "base_salary": "2500000",
            "family-TOTAL_FORMS": "0",
            "family-INITIAL_FORMS": "0",
            "education-TOTAL_FORMS": "0",
            "education-INITIAL_FORMS": "0",
            "talents-TOTAL_FORMS": "0",
            "talents-INITIAL_FORMS": "0",
            "gifts-TOTAL_FORMS": "0",
            "gifts-INITIAL_FORMS": "0",
        },
    )
    assert response.status_code == 302, [response.context[k].errors for k in ("person", "job", "extras")]
    employee = Employee.objects.get()
    assert employee.register_no == "УБ99112233"
    assert employee.job_records.count() == 1
    assert employee.salary_records.count() == 0  # HR's salary input is ignored

    # 2. detail page
    detail = f"/employees/{employee.pk}/"
    body = client.get(detail).content.decode()
    assert employee.full_name in body
    assert "2 500 000" not in body

    # 3. edit work phone on the page
    data = {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": "УБ99112233",
        "birth_date": "1999-11-22",
        "gender": "female",
        "work_phone": "88001122",
        "citizenship": "Монгол",
        "first_hire_date": "2026-01-05",
        "work_conditions": "normal",
        "prior_service_years": "0",
        "prior_service_months": "0",
    }
    response = client.post(f"{detail}save/", data)
    assert response.status_code == 303 and response["Location"] == detail
    employee.refresh_from_db()
    assert employee.work_phone == "88001122"

    # 4. note
    response = client.post(f"{detail}note/", {"text": "Туршилтын тэмдэглэл"})
    assert response.status_code == 200 and "Туршилтын тэмдэглэл" in response.content.decode()

    # 5. job correction with a reason
    record = employee.job_records.get()
    other = Position.objects.create(name="Ахлах нягтлан")
    response = client.post(
        f"{detail}job/{record.pk}/correct/",
        {
            "position": other.pk,
            "department": department.pk,
            "employee_type": "full_time",
            "status": "active",
            "contract_type": "open_ended",
            "reason": "Буруу бүртгэсэн",
        },
    )
    assert response.status_code == 204
    record.refresh_from_db()
    assert record.position == other
    assert ActivityEntry.objects.filter(employee=employee, message__contains="Буруу бүртгэсэн").exists()
    assert client.get("/employees/").status_code == 200

    # 6. Accountant sees the salary tab, sets then corrects the salary
    login_as(client, "Accountant", "acc1")
    body = client.get(detail).content.decode()
    assert "Цалин, даатгал" in body
    assert client.get(f"{detail}salary/set/").status_code == 200
    response = client.post(f"{detail}salary/set/", {"effective": "2026-01-05", "amount": "2500000"})
    assert response.status_code == 204
    salary = employee.salary_records.get()
    assert salary.base_salary == Decimal("2500000.00")
    assert "2 500 000" in client.get(detail).content.decode()
    response = client.post(f"{detail}salary/{salary.pk}/correct/", {"amount": "2600000", "reason": "Алдаа"})
    assert response.status_code == 204
    salary.refresh_from_db()
    assert salary.base_salary == Decimal("2600000.00")
    # a second "set" is refused: later changes go through corrections
    assert client.get(f"{detail}salary/set/").status_code == 403

    # 7. Employee role: own page without notes or salary, other page 404
    me = login_as(client, "Employee", "emp1")
    employee.user = me
    employee.save(update_fields=["user"])
    own = client.get(detail)
    assert own.status_code == 200
    text = own.content.decode()
    assert "Туршилтын тэмдэглэл" not in text and "2 600 000" not in text and "2600000" not in text
    stranger = Employee.objects.create(
        family_name="Дорж",
        given_name="Болд",
        register_no="УБ11223344",
        birth_date="1990-01-01",
        gender="male",
        work_phone="99000000",
        first_hire_date="2026-01-05",
    )
    assert client.get(f"/employees/{stranger.pk}/").status_code == 404

    # 8. list page, default and left filter
    client.force_login(hr)
    assert employee.code in client.get("/employees/").content.decode()
    left = client.get("/employees/?state=left")
    assert left.status_code == 200 and employee.code not in left.content.decode()
