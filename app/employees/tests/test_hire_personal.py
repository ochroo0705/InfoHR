"""The hire form's optional first address and emergency contact (production rows, written in the hire transaction)."""

from datetime import date
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from macs.models import AddressRow, City, ContactRow, ContactType, District

from employees.models import ActivityEntry, Department, Employee, Position
from employees.services import history
from employees.services import personal_writes as pw

from .conftest import hire_values
from .test_views import login_as

pytestmark = pytest.mark.django_db


@pytest.fixture
def place() -> dict[str, Any]:
    city = City.objects.create(name="Улаанбаатар")
    district = District.objects.create(name="Баянгол", city=city)
    return {"city": city, "district": district, "contact_type": ContactType.objects.create(name="Утас")}


@pytest.fixture
def hr_client(client: Client) -> Client:
    login_as(client, "HR", "hr1")
    return client


def hire_post(place: dict[str, Any], **extra: str) -> dict[str, str]:
    position = Position.objects.create(name="Нягтлан")
    department = Department.objects.create(name="Санхүү")
    return {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": "уб 99112233",
        "birth_date": "1999-11-22",
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": "2026-01-05",
        "work_conditions": "1",
        "prior_service_years": "0",
        "prior_service_months": "0",
        "start": "2026-01-05",
        "position": str(position.pk),
        "department": str(department.pk),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
        **extra,
    }


def test_hire_writes_first_address_and_contact(actor: Any, job_values: dict[str, Any], place: dict[str, Any]) -> None:
    address = {"city_id": place["city"].pk, "district_id": place["district"].pk, "street": "Peace ave 1"}
    contact = {
        "contact_type_id": place["contact_type"].pk,
        "name": "Болд",
        "relative": "Ах",
        "value": "99001122",
    }
    employee = history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=None,
        by=actor,
        address=address,
        contact=contact,
    )
    row = AddressRow.objects.get(employee=employee)
    assert (row.city_id, row.district_id, row.street) == (place["city"].pk, place["district"].pk, "Peace ave 1")
    crow = ContactRow.objects.get(employee=employee)
    assert (crow.name, crow.relative, crow.value) == ("Болд", "Ах", "99001122")
    assert ActivityEntry.objects.filter(employee=employee, personal=True).count() == 2


def test_hire_without_address_ok(actor: Any, job_values: dict[str, Any]) -> None:
    employee = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    assert not AddressRow.objects.filter(employee=employee).exists()
    assert not ContactRow.objects.filter(employee=employee).exists()


def test_hire_personal_conflict_rolls_back_the_hire(
    actor: Any, job_values: dict[str, Any], place: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(kind: str, *args: Any, **kwargs: Any) -> None:
        raise pw.PersonalConflict("refused")

    monkeypatch.setattr(pw, "add", refuse)
    with pytest.raises(pw.PersonalConflict):
        history.hire(
            hire_values(),
            {},
            start=date(2026, 1, 5),
            job=job_values,
            salary=None,
            by=actor,
            address={"city_id": place["city"].pk, "district_id": place["district"].pk, "street": None},
        )
    assert not Employee.objects.exists()


def test_hire_partial_address_refused_rolls_back(hr_client: Client, place: dict[str, Any]) -> None:
    response = hr_client.post("/employees/new/", hire_post(place, **{"addr-street": "Peace ave 1"}))
    assert response.status_code == 200
    assert response.context["address"].errors["city"]
    assert response.context["address"].errors["district"]
    assert not Employee.objects.exists()


def test_hire_partial_contact_refused(hr_client: Client, place: dict[str, Any]) -> None:
    response = hr_client.post("/employees/new/", hire_post(place, **{"contact-name": "Болд"}))
    errors = response.context["contact"].errors
    assert errors["contact_type"] and errors["relative"]
    assert not Employee.objects.exists()


def test_hire_post_saves_address_and_contact(hr_client: Client, place: dict[str, Any]) -> None:
    response = hr_client.post(
        "/employees/new/",
        hire_post(
            place,
            **{
                "addr-city": str(place["city"].pk),
                "addr-district": str(place["district"].pk),
                "addr-street": "Peace ave 1",
                "contact-contact_type": str(place["contact_type"].pk),
                "contact-name": "Болд",
                "contact-relative": "Ах",
            },
        ),
    )
    assert response.status_code == 302
    employee = Employee.objects.get()
    assert AddressRow.objects.get(employee=employee).street == "Peace ave 1"
    assert ContactRow.objects.get(employee=employee).relative == "Ах"


@pytest.mark.parametrize("prior", ["", None])
def test_hire_post_blank_prior_service_years_is_zero(
    hr_client: Client, place: dict[str, Any], prior: str | None
) -> None:
    # production working_year is NOT NULL: an emptied or missing field must not refuse the whole hire
    data = hire_post(place)
    if prior is None:
        del data["prior_service_years"]
    else:
        data["prior_service_years"] = prior
    response = hr_client.post("/employees/new/", data)
    assert response.status_code == 302
    assert Employee.objects.get().prior_service_years == 0


def test_hire_post_personal_conflict_shows_form_error(
    hr_client: Client, place: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(kind: str, *args: Any, **kwargs: Any) -> None:
        raise pw.PersonalConflict("Энэ хаяг аль хэдийн бүртгэгдсэн байна")

    monkeypatch.setattr(pw, "add", refuse)
    response = hr_client.post(
        "/employees/new/",
        hire_post(place, **{"addr-city": str(place["city"].pk), "addr-district": str(place["district"].pk)}),
    )
    assert response.status_code == 400
    assert "Энэ хаяг аль хэдийн бүртгэгдсэн байна" in response.content.decode()
    assert not Employee.objects.exists()


def test_hire_district_options_follow_city(hr_client: Client, place: dict[str, Any]) -> None:
    other_city = City.objects.create(name="Дархан")
    District.objects.create(name="Дархан дүүрэг", city=other_city)
    url = reverse("employees:district_options")
    body = hr_client.get(url, {"addr-city": str(place["city"].pk)}).content.decode()
    assert "Баянгол" in body
    assert "Дархан дүүрэг" not in body
    empty = hr_client.get(url).content.decode()
    assert "Баянгол" not in empty
    assert "Дархан дүүрэг" not in empty
    unknown = hr_client.get(url, {"addr-city": "999999"}).content.decode()
    assert "Баянгол" not in unknown


def test_hire_page_district_empty_without_city(hr_client: Client, place: dict[str, Any]) -> None:
    body = hr_client.get(reverse("employees:add")).content.decode()
    start = body.index('id="addr-district-wrap"')
    wrap = body[start : body.index("</label>", start)]  # the address district select only (birth place is separate)
    assert "<select" in wrap
    assert "Баянгол" not in wrap
