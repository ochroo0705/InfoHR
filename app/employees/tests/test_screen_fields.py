"""Old employee screen fields on production columns (macs 0005): second phone, job type and form,
second position, office, section, and the birth place table."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from macs.models import BirthPlace, City, District, Office, Section

from employees.forms import EmployeeForm
from employees.models import Employee
from employees.services import history, macs_writes

from .conftest import hire_values
from .test_insurance_columns import login_as


@pytest.fixture
def place(db: None) -> tuple[City, District]:
    city = macs_writes.save_list_entry(City, {"name": "Дархан-Уул"})
    district = macs_writes.save_list_entry(District, {"name": "Дархан", "city": city})
    return city, district


def _edit_post(employee: Employee, **extra: Any) -> dict[str, Any]:
    """The edit form's current values plus changes, as the browser would post them."""
    form = EmployeeForm(employee=employee)
    data = {n: form.initial.get(n) for n in form.fields if n not in ("photo", "photo_clear")}
    data = {k: ("" if v is None else getattr(v, "pk", v)) for k, v in data.items()}
    data["birth_date"] = employee.birth_date.isoformat() if employee.birth_date else ""
    data["first_hire_date"] = employee.first_hire_date.isoformat() if employee.first_hire_date else ""
    return {**data, **extra, "tab": "work"}


def test_edit_saves_screen_fields_to_employee_row(client: Client, hired: Employee) -> None:
    office = macs_writes.save_list_entry(Office, {"name": "Төв алба"})
    section = macs_writes.save_list_entry(Section, {"name": "Борлуулалт"})
    second = macs_writes.save_position("Зөвлөх")
    login_as(client, "HR")
    data = _edit_post(
        hired,
        phone2="88001122",
        job_type="Sesional",
        job_figure="Temporary",
        second_position=second.pk,
        office=office.pk,
        section=section.pk,
    )
    response = client.post(f"/employees/{hired.pk}/save/", data)
    assert response.status_code == 303, response.context["form"].errors
    row = Employee.objects.get(pk=hired.pk)
    assert (row.phone2, row.job_type, row.job_figure) == ("88001122", "Sesional", "Temporary")
    assert (row.second_position_id, row.office_id, row.section_id) == (second.pk, office.pk, section.pk)


def test_hire_writes_job_figure_default_and_birth_place(
    client: Client, actor: User, place: tuple[City, District]
) -> None:
    emp = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=_job(), salary=None, by=actor)
    assert Employee.objects.get(pk=emp.pk).job_figure == "Main"  # production default, written on insert
    city, district = place
    from employees.services import records

    records.set_birth_place(emp, city, district, "Сумын төв", actor)
    stored = BirthPlace.objects.get(employee=emp)
    assert (stored.city_id, stored.district_id, stored.description) == (city.pk, district.pk, "Сумын төв")
    records.set_birth_place(emp, city, district, "Өөр газар", actor)
    assert BirthPlace.objects.filter(employee=emp).count() == 1  # replaced, not added
    assert emp.activity.filter(changes__contains=[{"field": "Төрсөн газар"}]).count() == 2
    records.set_birth_place(emp, None, None, "", actor)
    assert not BirthPlace.objects.filter(employee=emp).exists()


def _job() -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


def test_birth_place_city_needs_district_of_that_city(hired: Employee, place: tuple[City, District]) -> None:
    city, district = place
    other = macs_writes.save_list_entry(City, {"name": "Орхон"})
    base = _edit_post(hired)
    assert "birth_district" in EmployeeForm({**base, "birth_city": city.pk}, employee=hired).errors
    form = EmployeeForm({**base, "birth_city": other.pk, "birth_district": district.pk}, employee=hired)
    assert "birth_district" in form.errors
    assert "birth_city" in EmployeeForm({**base, "birth_place_text": "x"}, employee=hired).errors
    form = EmployeeForm({**base, "birth_city": city.pk, "birth_district": district.pk}, employee=hired)
    assert form.is_valid(), form.errors
    assert form.birth_place() == (city, district, "")


def test_macs_employee_with_values_and_no_hr_rows_shows_them(
    client: Client, actor: User, place: tuple[City, District]
) -> None:
    """A production employee HR never touched (no EmployeeExt, no job records) shows what MACS holds."""
    office = macs_writes.save_list_entry(Office, {"name": "Салбар алба"})
    section = macs_writes.save_list_entry(Section, {"name": "Агуулах"})
    second = macs_writes.save_position("Жолооч")
    emp = macs_writes.create_employee(hire_values("УБ88776655"), {}, code="E9001", by=actor)
    emp.ext.delete()
    macs_writes.update_employee_columns(
        emp,
        {
            "phone2": "95550000",
            "job_type": "NonSesional",
            "job_figure": "Temporary",
            "second_position": second,
            "office": office,
            "section": section,
        },
    )
    macs_writes.save_birth_place(emp, *place, "Төрсөн тосгон")
    # A read-only viewer sees the stored values as text.
    from django.contrib.auth.models import Permission

    viewer = User.objects.create_user("reader", password="x-long-pass-123")  # noqa: S106
    viewer.user_permissions.add(*Permission.objects.filter(codename__in=["view_employees", "view_personal"]))
    client.force_login(viewer)
    body = client.get(f"/employees/{emp.pk}/").content.decode()
    for text in (
        "95550000",
        "Тогтмол",
        "Түр",
        "Жолооч",
        "Салбар алба",
        "Агуулах",
        "Дархан-Уул, Дархан — Төрсөн тосгон",
    ):
        assert text in body, text
    # HR gets the edit form with the same values selected.
    form = EmployeeForm(employee=Employee.objects.get(pk=emp.pk))
    assert form.initial["birth_place_text"] == "Төрсөн тосгон"
    assert (form.initial["office"], form.initial["job_figure"]) == (office.pk, "Temporary")


def test_legacy_row_without_job_figure_edits_without_error(hired: Employee) -> None:
    Employee.objects.filter(pk=hired.pk).update(job_figure=None)
    hired.refresh_from_db()
    form = EmployeeForm(_edit_post(hired), employee=hired)
    assert form.is_valid(), form.errors
    assert form.initial["job_figure"] == "Main"


def test_office_and_section_dropdowns_are_addable(hired: Employee) -> None:
    form = EmployeeForm(employee=hired)
    for name in ("office", "section", "second_position", "birth_city"):
        assert "data-add-url" in form.fields[name].widget.attrs, name
