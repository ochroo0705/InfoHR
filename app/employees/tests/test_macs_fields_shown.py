"""MACS fields shown and edited on the employee page (QC 4a-4c): education and degree on the personal tab;
employee code, foreign citizen flag, branch and years in sector; read-only contract, long leave, probation
months and last order from the MACS row."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.test import Client
from macs.models import AcademicDegree, Branch, EducationLevel

from employees.models import ActivityEntry, Employee
from employees.services import macs_writes

from .conftest import hire_values
from .test_insurance_columns import login_as
from .test_screen_fields import _edit_post


def _set(employee: Employee, **columns: Any) -> Employee:
    Employee.objects.filter(pk=employee.pk).update(**columns)
    return Employee.objects.get(pk=employee.pk)


def _page(client: Client, employee: Employee) -> str:
    return client.get(f"/employees/{employee.pk}/").content.decode()


def _logged(employee: Employee, label: str) -> bool:
    return any(label in str(entry.changes) for entry in ActivityEntry.objects.filter(employee=employee))


def _viewer(client: Client) -> User:
    """A user who can see the employee but cannot manage it: the read-only page."""
    user = User.objects.create_user("viewer_4c", password="x-long-pass-123")  # noqa: S106
    for codename in ("view_employees", "view_personal"):
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="macs"))
    client.force_login(user)
    return user


@pytest.fixture
def other(actor: User) -> Employee:
    """A second employee, with a code, to clash with."""
    emp = macs_writes.create_employee(hire_values("УБ11223344"), {}, code="OTHER01", by=actor)
    return emp


# 4a: education level and academic degree on the personal tab


def test_personal_tab_shows_education_and_degree_to_viewer(client: Client, hired: Employee) -> None:
    level = macs_writes.save_list_entry(EducationLevel, {"name": "Бакалавр боловсрол"})
    degree = macs_writes.save_list_entry(AcademicDegree, {"name": "Магистрын зэрэг"})
    hired = _set(hired, education_level=level, academic_degree=degree)
    _viewer(client)
    html = _page(client, hired)
    assert "Боловсрол" in html and "Эрдмийн зэрэг" in html
    assert "Бакалавр боловсрол" in html and "Магистрын зэрэг" in html


# 4b: employee code


def test_code_is_editable_in_header_for_managers(client: Client, hired: Employee) -> None:
    hired = _set(hired, code="E0042")
    login_as(client, "HR")
    assert 'name="code"' in _page(client, hired)


def test_code_edit_saves_trimmed_and_is_logged(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/save/", _edit_post(hired, code="  NEW77 "))
    assert response.status_code == 303, response.context["form"].errors
    row = Employee.objects.get(pk=hired.pk)
    assert row.code == "NEW77"
    assert _logged(row, "Ажилтны код")


def test_code_clash_is_refused_case_insensitively(client: Client, hired: Employee, other: Employee) -> None:
    login_as(client, "HR")
    before = Employee.objects.get(pk=hired.pk).code
    response = client.post(f"/employees/{hired.pk}/save/", _edit_post(hired, code="other01"), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert "аль хэдийн бүртгэлтэй" in response.content.decode()
    assert Employee.objects.get(pk=hired.pk).code == before


def test_code_longer_than_ten_characters_is_refused(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.post(
        f"/employees/{hired.pk}/save/", _edit_post(hired, code="ABCDEFGHIJK"), HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 200
    assert "10 тэмдэгт" in response.content.decode()
    assert Employee.objects.get(pk=hired.pk).code != "ABCDEFGHIJK"


def test_clearing_an_existing_code_is_refused(client: Client, hired: Employee) -> None:
    hired = _set(hired, code="KEEP1")
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/save/", _edit_post(hired, code="   "), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert Employee.objects.get(pk=hired.pk).code == "KEEP1"


# 4c: foreign citizen flag, branch, years in sector (editable)


def test_foreign_flag_saves_and_is_logged(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/save/", _edit_post(hired, foreign_emp="1"))
    assert response.status_code == 303, response.context["form"].errors
    row = Employee.objects.get(pk=hired.pk)
    assert row.foreign_emp == 1
    assert _logged(row, "Гадаад иргэн")


def test_foreign_flag_can_be_set_back_to_no(client: Client, hired: Employee) -> None:
    hired = _set(hired, foreign_emp=1)
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/save/", _edit_post(hired, foreign_emp="0"))
    assert response.status_code == 303
    assert Employee.objects.get(pk=hired.pk).foreign_emp == 0


def test_branch_and_sector_years_save_and_are_logged(client: Client, hired: Employee) -> None:
    branch = macs_writes.save_list_entry(Branch, {"name": "Салбар тест", "status": 1})
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/save/", _edit_post(hired, branch=branch.pk, sector_years="5"))
    assert response.status_code == 303, response.context["form"].errors
    row = Employee.objects.get(pk=hired.pk)
    assert row.branch_id == branch.pk and row.sector_years == 5
    assert _logged(row, "Салбар") and _logged(row, "Салбарт ажилласан жил")


def test_sector_years_refuses_negative(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/save/", _edit_post(hired, sector_years="-1"), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert Employee.objects.get(pk=hired.pk).sector_years == 0


def test_branch_is_not_addable(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    html = _page(client, hired)
    branch_select = html[html.index('name="branch"') - 300 : html.index('name="branch"') + 300]
    assert "data-add-url" not in branch_select


# Read-only MACS fields: shown, never written from the form


def test_read_only_work_fields_are_shown(client: Client, hired: Employee) -> None:
    hired = _set(
        hired,
        contract_no="C-2026-9",
        contract_start=date(2026, 2, 1),
        contract_end=date(2027, 1, 31),
        taken_leave=1,
        leave_type=2,
        probation_months=3,
        last_order_no="77/12",
        last_order_text="Ажлын байранд томилсон",
    )
    _viewer(client)
    html = _page(client, hired)
    for text in (
        "C-2026-9",
        "2026-02-01",
        "2027-01-31",
        "Хүүхэд асрах",
        "77/12",
        "Ажлын байранд томилсон",
    ):
        assert text in html, text


def test_posting_read_only_fields_changes_nothing(client: Client, hired: Employee) -> None:
    hired = _set(
        hired,
        contract_no="C-1",
        contract_start=date(2026, 2, 1),
        contract_end=date(2027, 1, 31),
        taken_leave=0,
        leave_type=None,
        probation_months=3,
        last_order_no="1",
        last_order_text="Анхны",
    )
    login_as(client, "HR")
    data = _edit_post(
        hired,
        contract_no="HACK",
        contract_start="2030-01-01",
        contract_end="2030-02-01",
        taken_leave="1",
        leave_type="3",
        probation_months="9",
        last_order_no="999",
        last_order_text="Хуурамч",
    )
    client.post(f"/employees/{hired.pk}/save/", data)
    row = Employee.objects.get(pk=hired.pk)
    assert row.contract_no == "C-1"
    assert row.contract_start == date(2026, 2, 1) and row.contract_end == date(2027, 1, 31)
    assert (row.taken_leave, row.leave_type) == (0, None)
    assert (row.last_order_no, row.last_order_text) == ("1", "Анхны")


# Legacy rows: an unrelated save leaves the MACS values alone


def test_unrelated_save_keeps_legacy_values(client: Client, hired: Employee) -> None:
    branch = macs_writes.save_list_entry(Branch, {"name": "Салбар легаси", "status": 1})
    hired = _set(hired, code="LEG01", foreign_emp=None, branch=branch, sector_years=3)
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/save/", _edit_post(hired, phone2="88001122"))
    assert response.status_code == 303, response.context["form"].errors
    row = Employee.objects.get(pk=hired.pk)
    assert row.phone2 == "88001122"
    assert row.code == "LEG01"
    assert row.foreign_emp is None
    assert row.branch_id == branch.pk
    assert row.sector_years == 3


def test_unrelated_save_on_legacy_row_without_code_does_not_demand_one(client: Client, hired: Employee) -> None:
    hired = _set(hired, code=None, foreign_emp=None)
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/save/", _edit_post(hired, phone2="88003344"))
    assert response.status_code == 303, response.context["form"].errors
    row = Employee.objects.get(pk=hired.pk)
    assert row.phone2 == "88003344"
    assert row.code in (None, "")
    assert row.foreign_emp is None


@pytest.mark.parametrize(
    "columns",
    [
        {"code": None},
        {"code": ""},
        {"code": "A1   "},
        {"foreign_emp": 2},
        {"sector_years": 75},
        {"sector_years": -1},
    ],
)
def test_unusual_legacy_values_survive_an_unrelated_save(
    client: Client, hired: Employee, columns: dict[str, Any]
) -> None:
    emp = _set(hired, **columns)
    login_as(client, "HR")
    response = client.post(f"/employees/{emp.pk}/save/", _edit_post(emp, work_phone="99112233"))
    assert response.status_code == 303, response.context["form"].errors
    after = Employee.objects.get(pk=emp.pk)
    assert after.work_phone == "99112233"
    assert {name: getattr(after, name) for name in columns} == columns
