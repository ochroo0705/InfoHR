"""Company name and director: one admin-editable row (CompanySettings), used by orders."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.contrib.admin.sites import site
from django.test import Client, RequestFactory

from employees.forms import OrderFieldsForm
from employees.models import CompanySettings, HrOrder
from employees.services import history, orders

from .conftest import hire_values
from .test_views import login_as

pytestmark = pytest.mark.django_db


def _company(name: str = "Инфосистемс-1 ХХК", director: str = "Б. Батболд") -> CompanySettings:
    row = CompanySettings.get()
    row.name, row.director_name = name, director
    row.save()
    return row


def test_get_creates_one_blank_row() -> None:
    first = CompanySettings.get()
    assert (first.pk, first.name, first.director_name) == (1, "", "")
    assert CompanySettings.get().pk == 1
    assert CompanySettings.objects.count() == 1


def test_order_form_defaults_issued_by_to_director() -> None:
    _company(director="Б. Батболд")
    assert OrderFieldsForm().initial["issued_by"] == "Б. Батболд"


def test_director_name_fits_issued_by() -> None:
    # director_name holds at most 25 characters, the length of production command.human_command
    _company(director="Ж" * 25)
    assert OrderFieldsForm().initial["issued_by"] == "Ж" * 25
    assert CompanySettings._meta.get_field("director_name").max_length == 25


def test_register_blank_issued_by_takes_director(actor: User, job_values: dict[str, Any]) -> None:
    _company(director="Б. Батболд")
    employee = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    order = HrOrder.objects.get(employee=employee)
    orders.register(order, number="Т-1", date=date(2026, 1, 5), summary="", issued_by="", by=actor)
    order.refresh_from_db()
    assert order.issued_by == "Б. Батболд"


def test_print_shows_company_name(client: Client) -> None:
    _company(name="Инфосистемс-1 ХХК")
    login_as(client, "HR", "hr_company")
    response = client.get("/employees/orders/print/")
    assert response.status_code == 200
    assert "Инфосистемс-1 ХХК" in response.content.decode()


def test_admin_singleton_no_second_row_no_delete() -> None:
    admin = site._registry[CompanySettings]
    request = RequestFactory().get("/")
    request.user = User.objects.create_superuser("company_admin", password="x-long-pass-123")  # noqa: S106
    assert admin.has_add_permission(request) is True
    CompanySettings.get()
    assert admin.has_add_permission(request) is False
    assert admin.has_delete_permission(request, CompanySettings.get()) is False
