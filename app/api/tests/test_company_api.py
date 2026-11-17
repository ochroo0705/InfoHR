"""GET /api/v1/company: the company figures page, as company_page renders it (403 without the employee-list right)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from django.utils.formats import localize
from employees import access, company_stats
from employees.listing import employee_rows
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("company_api_hr", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.HR)[0])
    return user


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def hired(hr_user: User, job_values: dict[str, Any]) -> Employee:
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def test_company_without_the_employee_list_right_is_403(hired: Employee) -> None:
    plain = User.objects.create_user("company_api_plain", password=PASSWORD)  # no groups: no view_employees
    assert _client(plain).get("/api/v1/company").status_code == 403


def test_company_anonymous_is_401() -> None:
    assert Client().get("/api/v1/company").status_code == 401


def test_company_for_hr_is_200_with_the_headcount_of_company_stats(hr_user: User, hired: Employee) -> None:
    today = timezone.localdate()
    response = _client(hr_user).get("/api/v1/company")
    assert response.status_code == 200
    body = response.json()
    rows = employee_rows(access.visible_employees(hr_user).filter(ext__isnull=False), today)
    expected = company_stats.company(hr_user, rows, today)
    assert expected is not None
    assert body["headcount"]["head"] == localize(expected.headcount[-1].value)
    assert body["today"] == today.isoformat()
    assert body["title"] == "Компанийн байдал"
    assert body["hires_text"] == f"Энэ сард орсон {localize(expected.hires_month)}"
    assert body["leavers_text"] == f"Гарсан {localize(expected.leavers_month)}"
    assert body["partial_scope"] is False
    assert body["scope_label"] == ""
    assert body["headcount"]["title"] == "Ажилтны тоо, 12 сар"
    assert len(body["headcount"]["polylines"]) >= 1
    assert body["headcount"]["no_data_text"] == "Мэдээлэл алга"
    assert body["departments"]["bars"][0]["label"] == "Санхүү"
    assert body["departments"]["bars"][0]["width"] == "100%"
    assert body["tenure"]["title"] == "Ажилласан хугацаа"
    assert body["turnover_note"] == "Сарын эргэлт = гарсан ÷ сарын дундаж ажилтны тоо"
