from collections.abc import Callable

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee

pytestmark = pytest.mark.django_db


def test_page_shows_the_old_sheet_columns_for_hr(client: Client, login_hr: User, hired: Employee) -> None:
    response = client.get("/reports/employee-info/")
    assert response.status_code == 200
    page = response.content.decode()
    assert "Төрсөн огноо" in page
    assert hired.full_name in page


def test_accountant_sees_no_personal_columns(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "Accountant", "acc")
    response = client.get("/reports/employee-info/")
    assert response.status_code == 200
    page = response.content.decode()
    assert "Регистрийн дугаар" not in page
    assert hired.full_name in page


def test_employee_role_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee", "emp")
    assert client.get("/reports/employee-info/").status_code == 403


def test_column_picker_is_offered(client: Client, login_hr: User) -> None:
    assert "Багана" in client.get("/reports/employee-info/").content.decode()


def test_filter_bar_has_only_the_four_filters(client: Client, login_hr: User) -> None:
    page = client.get("/reports/employee-info/").content.decode()
    assert 'name="state"' in page
    assert 'name="branch"' in page
    assert 'name="department"' in page
    assert 'name="as_of"' in page
    assert 'name="position"' not in page
    assert 'name="gender"' not in page
