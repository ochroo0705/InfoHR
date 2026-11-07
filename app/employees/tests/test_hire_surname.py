"""The surname (family name) is required on every path that hires a person: the hire form, the recruitment hire
(the same form, opened from a candidate) and the staff Excel import. MACS needs it: the customer description is
built from it (TR_EMPCUST), so a hire without a surname fails on Firebird."""

from typing import Any

import pytest
from django.forms import Field
from django.test import Client
from macs.models import Employee as MacsEmployee

from employees.models import Employee
from employees.staff_import.fields import BY_KEY
from employees.staff_import.run import run_import

from .test_hire_personal import hire_post
from .test_staff_import_run import make_draft, person, rejected_sheet
from .test_views import login_as

pytestmark = pytest.mark.django_db

SURNAME_REQUIRED = str(Field.default_error_messages["required"])


@pytest.fixture
def hr_client(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


def test_hire_form_without_surname_shows_required_error_and_creates_nothing(hr_client: Client) -> None:
    response = hr_client.post("/employees/new/", hire_post({}, family_name=""))
    assert response.status_code == 200
    assert response.context["person"].errors["family_name"] == [SURNAME_REQUIRED]
    assert not Employee.objects.exists()
    assert not MacsEmployee.objects.exists()


def test_hire_form_with_blank_spaces_as_surname_is_refused(hr_client: Client) -> None:
    response = hr_client.post("/employees/new/", hire_post({}, family_name="   "))
    assert response.status_code == 200
    assert response.context["person"].errors["family_name"] == [SURNAME_REQUIRED]
    assert not Employee.objects.exists()


def test_staff_import_row_without_surname_is_rejected_not_created(actor: Any) -> None:
    draft = make_draft([person(family_name=""), person(register_no="УБ99112255", given_name="Сэрэн")])

    run_import(draft, by=actor, allow_salary=False)

    draft.refresh_from_db()
    assert draft.created_count == 1
    assert draft.rejected_count == 1
    assert Employee.objects.count() == 1
    assert Employee.objects.get().given_name == "Сэрэн"
    rows = rejected_sheet(draft)
    assert rows[1][-1] == f"{BY_KEY['family_name'].label} дутуу байна"
