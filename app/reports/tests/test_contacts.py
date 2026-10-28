from collections.abc import Callable
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee
from employees.tests.conftest import named
from macs.models import ContactRow, ContactType

from reports.contacts import REPORT
from reports.filters import Filters

pytestmark = pytest.mark.django_db


def _contact(employee: Employee, kind: ContactType, value: str) -> ContactRow:
    return ContactRow.objects.create(employee=employee, contact_type=kind, value=value, name="Эх", relative="Ээж")


def test_each_contact_row_is_listed_with_its_person(hr_user: User, hired: Employee) -> None:
    _contact(hired, named(ContactType, "Утас"), "99112233")
    _contact(hired, named(ContactType, "Имэйл"), "a@b.mn")
    rows = REPORT.rows(hr_user, Filters())
    assert sorted(r.item.value or "" for r in rows) == ["99112233", "a@b.mn"]
    assert all(r.person.row.employee.pk == hired.pk for r in rows)


def test_contact_type_filter(hr_user: User, hired: Employee) -> None:
    _contact(hired, named(ContactType, "Утас"), "99112233")
    mail = named(ContactType, "Имэйл")
    _contact(hired, mail, "a@b.mn")
    rows = REPORT.rows(hr_user, Filters(contact_type=mail.pk))
    assert [r.item.value for r in rows] == ["a@b.mn"]


def test_department_filter(hr_user: User, hired: Employee, job_values: dict[str, Any]) -> None:
    _contact(hired, named(ContactType, "Утас"), "99112233")
    department = job_values["department"]
    assert len(REPORT.rows(hr_user, Filters(department=department.pk))) == 1
    assert REPORT.rows(hr_user, Filters(department=department.pk + 1000)) == []


def test_left_person_hidden_by_default(hr_user: User, left_employee: Employee) -> None:
    _contact(left_employee, named(ContactType, "Утас"), "99000011")
    assert REPORT.rows(hr_user, Filters()) == []
    assert len(REPORT.rows(hr_user, Filters(state="left"))) == 1


def test_accountant_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc")
    assert client.get("/reports/contacts/").status_code == 403


def test_page_shows_title_and_contact_type_select(client: Client, login_hr: User, hired: Employee) -> None:
    response = client.get("/reports/contacts/")
    assert response.status_code == 200
    page = response.content.decode()
    assert "Ажилчидтай холбоо барих" in page
    assert 'name="contact_type"' in page
