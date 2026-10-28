from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from employees.models import Employee
from employees.tests.conftest import named
from macs.models import AddressRow, City, ContactRow, ContactType, District

from reports.elders import REPORT
from reports.filters import Filters

from .conftest import legacy

pytestmark = pytest.mark.django_db


def _aged(actor: User, job_values: dict[str, Any], years: int) -> Employee:
    """An employee who is `years` full years old today: the 1 January of that year has always passed."""
    return legacy(actor, job_values, birth_date=date(timezone.localdate().year - years, 1, 1))


def _pks(people: list[Any]) -> list[int]:
    return [p.person.row.employee.pk for p in people]


def _records(employee: Employee, phone: ContactType) -> None:
    """One contact row and one address row for the employee (both FKs are NOT NULL in the DB)."""
    city = City.objects.create(name="Улаанбаатар")
    district = District.objects.create(name="Баянгол", city=city)
    AddressRow.objects.create(employee=employee, city=city, district=district, street="Хан-Уул 3")
    ContactRow.objects.create(employee=employee, contact_type=phone, value="99112233", name="Эх", relative="Ээж")


def test_default_minimum_age_is_sixty(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    too_young = _aged(actor, job_values, 59)
    elder = _aged(actor, job_values, 60)
    rows = REPORT.rows(hr_user, Filters())
    assert _pks(rows) == [elder.pk]
    assert too_young.pk not in _pks(rows)


def test_age_boundary_on_an_explicit_day(hr_user: User, hired: Employee) -> None:
    """Born 27 October 1966: 59 on 26 October 2026 (birthday tomorrow), 60 from 27 October 2026."""
    Employee.objects.filter(pk=hired.pk).update(birth_date=date(1966, 10, 27))
    assert REPORT.rows(hr_user, Filters(as_of=date(2026, 10, 26))) == []
    on_birthday = REPORT.rows(hr_user, Filters(as_of=date(2026, 10, 27)))
    assert _pks(on_birthday) == [hired.pk]
    assert on_birthday[0].person.age == 60


def test_age_range_filter(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    young = _aged(actor, job_values, 49)
    low = _aged(actor, job_values, 50)
    high = _aged(actor, job_values, 58)
    over = _aged(actor, job_values, 59)
    rows = REPORT.rows(hr_user, Filters(age_from=50, age_to=58))
    assert sorted(_pks(rows)) == sorted([low.pk, high.pk])
    assert young.pk not in _pks(rows) and over.pk not in _pks(rows)


def test_contacts_and_address_are_listed_once_per_person(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    with_contacts = _aged(actor, job_values, 65)
    bare = _aged(actor, job_values, 70)
    city = City.objects.create(name="Улаанбаатар")
    district = District.objects.create(name="Баянгол", city=city)
    AddressRow.objects.create(employee=with_contacts, city=city, district=district, street="Хан-Уул 3")
    AddressRow.objects.create(employee=with_contacts, city=city, district=district, street="Сүхбаатар 9")
    phone = named(ContactType, "Утас")
    mail = named(ContactType, "Имэйл")
    ContactRow.objects.create(employee=with_contacts, contact_type=phone, value="99112233", name="Эх", relative="Ээж")
    ContactRow.objects.create(employee=with_contacts, contact_type=mail, value="a@b.mn", name="Ах", relative="Ах")

    rows = REPORT.rows(hr_user, Filters())
    assert len(rows) == 2
    by_pk = {r.person.row.employee.pk: r for r in rows}
    elder = by_pk[with_contacts.pk]
    assert "99112233" in elder.contacts and "a@b.mn" in elder.contacts
    assert elder.contacts.count(";") == 1
    assert elder.address == "Улаанбаатар, Баянгол, Хан-Уул 3"
    empty = by_pk[bare.pk]
    assert empty.contacts == "" and empty.address == ""


def test_empty_contact_parts_are_left_out(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    elder = _aged(actor, job_values, 66)
    phone = named(ContactType, "Утас")
    ContactRow.objects.create(employee=elder, contact_type=phone, value=None, name="Эх", relative="")
    [row] = REPORT.rows(hr_user, Filters())
    assert row.contacts == "Утас (Эх)"


def test_person_without_birth_date_is_not_listed(
    hr_user: User, actor: User, hired: Employee, job_values: dict[str, Any]
) -> None:
    Employee.objects.filter(pk=hired.pk).update(birth_date=None)
    sibling = _aged(actor, job_values, 65)
    assert _pks(REPORT.rows(hr_user, Filters())) == [sibling.pk]


def test_query_count_does_not_grow_with_people(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    phone = named(ContactType, "Утас")
    _records(_aged(actor, job_values, 61), phone)
    REPORT.rows(hr_user, Filters())  # warm the user's permission cache so the first count is not inflated
    with CaptureQueriesContext(connection) as one:
        assert len(REPORT.rows(hr_user, Filters())) == 1
    for years in (62, 63):
        _records(_aged(actor, job_values, years), phone)
    with CaptureQueriesContext(connection) as three:
        assert len(REPORT.rows(hr_user, Filters())) == 3
    assert len(three.captured_queries) == len(one.captured_queries)


def test_accountant_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc")
    assert client.get("/reports/elders/").status_code == 403


def test_note_explains_the_floor_when_only_an_upper_age_is_set() -> None:
    """With age_to alone the floor stays at 60: the grey line says so; with both ages set it does not."""
    assert REPORT.note is not None
    sentence = "Дээд насыг тохируулсан бол доод нас 60 хэвээр."
    assert sentence in REPORT.note(Filters(age_to=70))
    assert sentence not in REPORT.note(Filters(age_from=65, age_to=70))
    assert sentence not in REPORT.note(Filters())
