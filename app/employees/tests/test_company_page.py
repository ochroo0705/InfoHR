# ruff: noqa: F811  (the reused fixtures are imported, then named as test arguments)
"""The company analytics page (employees:company): HR sees the block, a user without the employee-list right is
refused, and Today keeps one summary line instead of the charts."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from employees.models import Employee

from .conftest import link_login
from .test_today import frozen_today  # noqa: F401
from .test_views import login_as

pytestmark = pytest.mark.django_db


def test_company_page_renders_charts(client: Client, hired: Employee, frozen_today: date) -> None:
    login_as(client, "HR")
    response = client.get(reverse("employees:company"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "data-company" in body
    assert "Компанийн байдал" in body


def test_company_page_needs_right(client: Client, hired: Employee, frozen_today: date) -> None:
    own = login_as(client, "Employee", "emp_company_page")
    link_login(hired, own)
    response = client.get(reverse("employees:company"))
    assert response.status_code == 403
    assert "data-company" not in response.content.decode()


def test_company_page_redirects_anonymous_to_login(client: Client) -> None:
    response = client.get(reverse("employees:company"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_today_no_longer_renders_charts(client: Client, hired: Employee, frozen_today: date) -> None:
    login_as(client, "HR")
    body = client.get(reverse("employees:today")).content.decode()
    assert "data-company" not in body
    assert "Энэ сард орсон 0 · Гарсан 0 · " in body
    assert f'href="{reverse("employees:company")}"' in body
    assert "Компанийн байдал →" in body
