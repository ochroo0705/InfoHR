"""The data gaps report («Дутуу мэдээлэл»): one row per employee with a blank checked staff-list column, and which ones.
A viewer never has a column named, counted or exported that the staff list would not show them."""

import io
from typing import Any

import openpyxl
import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from employees.tests.conftest import named
from macs.models import AddressRow, Bank, City, ContactRow, ContactType, District, EducationLevel

from reports import data_gaps, staff_list
from reports.filters import Filters
from reports.registry import REPORTS

from .conftest import count_queries, legacy

pytestmark = pytest.mark.django_db

PAGE = "/reports/data-gaps/"


def _complete(actor: User, job_values: dict[str, Any], **blank: Any) -> Employee:
    """A legacy employee with every checked field filled; `blank` overwrites Employee fields (a value of None or "")."""
    emp = legacy(actor, job_values)
    values: dict[str, Any] = {
        "email": "bat@example.mn",
        "private_phone": "88112233",
        "contract_no": "Г-2026/1",
        "social_insurance_no": "1234567",
        "account_no": "5001234567",
        "bank": named(Bank, "Хаан банк"),
        "education_level": named(EducationLevel, "Бакалавр"),
        **blank,
    }
    Employee.objects.filter(pk=emp.pk).update(**values)
    city = City.objects.get_or_create(name="Улаанбаатар")[0]
    district = District.objects.get_or_create(name="Сүхбаатар", city=city)[0]
    AddressRow.objects.create(employee=emp, city=city, district=district, street="Баруун 3")
    ContactRow.objects.create(
        employee=emp, contact_type=named(ContactType, "Утас"), value="99112233", name="Эх", relative="Ээж"
    )
    return Employee.objects.get(pk=emp.pk)


def _gap(rows: list[data_gaps.GapRow], emp: Employee) -> data_gaps.GapRow | None:
    return next((r for r in rows if r.staff.row.employee.pk == emp.pk), None)


def _cell(row: data_gaps.GapRow, key: str) -> Any:
    return next(c for c in data_gaps.REPORT.columns if c.key == key).value(row)


def _export_for(user: User) -> None:
    """The export switch (accounts.export_lists) for a user who is not HR; the switch itself is not under test."""
    user.user_permissions.add(Permission.objects.get(codename="export_lists", content_type__app_label="accounts"))


def test_fully_filled_person_is_not_listed(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    full = _complete(actor, job_values)
    assert _gap(data_gaps.rows(hr_user, Filters()), full) is None


def test_lists_the_blank_fields_in_checked_order(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    emp = _complete(actor, job_values, register_no="", email="")
    row = _gap(data_gaps.rows(hr_user, Filters()), emp)
    assert row is not None
    assert row.missing == ("Регистрийн дугаар", "И-мэйл")  # CHECKED order, not the order of the fields
    assert row.checked == 13  # HR sees 13 of the 16 checked columns (no salary or bank ones)
    assert _cell(row, "missing_count") == 2
    assert _cell(row, "filled_pct") == 85  # 11 of 13 filled, rounded
    assert _cell(row, "missing") == "Регистрийн дугаар; И-мэйл"


def test_most_missing_comes_first(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    one = _complete(actor, job_values, email="")
    three = _complete(actor, job_values, email="", contract_no="", work_phone="")
    listed = [r.staff.row.employee.pk for r in data_gaps.rows(hr_user, Filters())]
    assert listed == [three.pk, one.pk]


def test_text_of_only_spaces_counts_as_blank(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    emp = _complete(actor, job_values, work_phone="   ")
    row = _gap(data_gaps.rows(hr_user, Filters()), emp)
    assert row is not None and row.missing == ("Ажлын утас",)


def test_viewer_without_personal_checks_and_names_no_personal_field(
    accountant_user: User, client: Client, actor: User, job_values: dict[str, Any]
) -> None:
    emp = _complete(actor, job_values, register_no="", private_phone="", email="")
    row = _gap(data_gaps.rows(accountant_user, Filters()), emp)
    assert row is not None
    assert row.checked == 9  # the 7 personal columns are not checked for this viewer
    assert row.missing == ("И-мэйл",)  # the blank personal fields are not named

    _export_for(accountant_user)
    client.force_login(accountant_user)
    body = client.get(PAGE).content.decode()
    assert "Регистрийн дугаар" not in body and "Хувийн утас" not in body
    printed = client.get(PAGE + "print/").content.decode()
    assert "Регистрийн дугаар" not in printed and "Хувийн утас" not in printed
    sheet = openpyxl.load_workbook(io.BytesIO(client.get(PAGE + "excel/").content)).active
    cells = {str(value) for line in sheet.iter_rows(values_only=True) for value in line if value is not None}
    assert "Регистрийн дугаар" not in cells and "Хувийн утас" not in cells
    assert "И-мэйл" in cells  # a checked column is still named


def test_viewer_without_salary_never_names_bank_or_account(
    hr_user: User, client: Client, actor: User, job_values: dict[str, Any]
) -> None:
    emp = _complete(actor, job_values, email="", bank=None, account_no="", social_insurance_no="")
    row = _gap(data_gaps.rows(hr_user, Filters()), emp)
    assert row is not None and row.missing == ("И-мэйл",)
    assert "Банк" not in row.missing and "Дансны дугаар" not in row.missing
    assert row.checked == 13
    client.force_login(hr_user)
    body = client.get(PAGE).content.decode()
    assert "Банк" not in body and "Дансны дугаар" not in body and "НДД-ийн дугаар" not in body


def test_page_opens_with_count_selection_and_chart(
    client: Client, login_hr: User, actor: User, job_values: dict[str, Any]
) -> None:
    gap = _complete(actor, job_values, email="")
    _complete(actor, job_values)
    page = client.get(PAGE)
    assert page.status_code == 200
    body = page.content.decode()
    assert "Нийт: 1" in body
    assert 'type="checkbox"' in body
    assert f'data-person="{gap.pk}"' in body
    chart = client.get(PAGE, {"layout": "chart", "lby": "department"})
    assert chart.status_code == 200


def test_page_is_refused_without_view_employees(client: Client) -> None:
    reporter = User.objects.create_user("reporter", password="x-long-pass-123")  # noqa: S106
    reporter.user_permissions.add(Permission.objects.get(content_type__app_label="reports", codename="view_reports"))
    client.force_login(reporter)
    assert client.get(PAGE).status_code == 403


def test_name_links_to_the_employee(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    emp = _complete(actor, job_values, email="")
    row = _gap(data_gaps.rows(hr_user, Filters()), emp)
    assert row is not None
    href = next(c for c in data_gaps.REPORT.columns if c.key == "name").href
    assert href is not None and href(row) == reverse("employees:detail", args=[emp.pk])


def test_registered_as_a_row_report_with_selection() -> None:
    report = REPORTS["data-gaps"]
    assert report.person is not None
    assert report.shows_count is True
    assert report.layouts  # the registry gives every row report its views
    assert report.needs == ("macs.view_employees",)


def test_every_checked_key_is_a_staff_list_column() -> None:
    staff_keys = {c.key for c in staff_list.COLUMNS}
    assert set(data_gaps.CHECKED) <= staff_keys
    assert len(data_gaps.CHECKED) == len(set(data_gaps.CHECKED)) == 16


def test_query_count_does_not_grow_with_the_number_of_people(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    """Legacy employees hold only department and position ids; the names must be loaded once for all, not per row."""
    for _ in range(2):
        _complete(actor, job_values, email="")
    two = count_queries(data_gaps.REPORT, hr_user, Filters())
    for _ in range(4):
        _complete(actor, job_values, email="")
    six = count_queries(data_gaps.REPORT, hr_user, Filters())
    assert two == six
