"""An imported person with no register number (a foreign worker, passport only) can be edited on the Work tab and in
the identity section. A register number is still required for a new hire, and a typed one is still checked."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse

from employees.forms import EmployeeForm
from employees.models import Employee
from employees.services import history

from .test_views import login_as

pytestmark = pytest.mark.django_db


@pytest.fixture
def passport_only(actor: User, job_values: dict[str, Any]) -> Employee:
    return history.hire(
        {
            "family_name": "Smith",
            "given_name": "John",
            "passport_no": "AB1234567",
            "birth_date": date(1980, 1, 1),
            "gender": "M",
            "first_hire_date": date(2026, 1, 5),
        },
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=None,
        by=actor,
        with_order=False,
    )


def test_work_tab_save_succeeds_for_a_passport_only_person(client: Client, passport_only: Employee) -> None:
    login_as(client, "HR", "hr_passport_work")
    response = client.post(f"/employees/{passport_only.pk}/save/", {"tab": "work", "private_phone": "99112233"})
    assert response.status_code == 303
    passport_only.refresh_from_db()
    assert passport_only.private_phone == "99112233"


def test_identity_section_saves_with_register_blank(client: Client, passport_only: Employee) -> None:
    login_as(client, "HR", "hr_passport_identity")
    url = reverse("employees:personal_section", args=[passport_only.pk, "identity"])
    client.post(url, {"register_no": "", "passport_no": "AB7654321"})
    passport_only.refresh_from_db()
    assert passport_only.passport_no == "AB7654321"
    assert not passport_only.register_no


def test_a_typed_malformed_register_is_still_refused(client: Client, passport_only: Employee) -> None:
    login_as(client, "HR", "hr_passport_bad")
    response = client.post(f"/employees/{passport_only.pk}/save/", {"tab": "work", "register_no": "XX1"})
    assert response.status_code == 400
    passport_only.refresh_from_db()
    assert not passport_only.register_no


def test_a_new_hire_still_requires_register_phone_and_work_conditions() -> None:
    form = EmployeeForm({"family_name": "Бат", "given_name": "Дорж"}, employee=None)
    assert not form.is_valid()
    assert {"register_no", "work_phone", "work_conditions", "birth_date", "gender"} <= set(form.errors)


def test_an_existing_employee_with_a_register_still_requires_it(hired: Employee) -> None:
    """Relaxed only when the stored value is empty: a stored register number stays required."""
    form = EmployeeForm({"register_no": ""}, employee=hired)
    form.is_valid()
    assert "register_no" in form.errors
