from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from employees.models import Employee
from macs.models import AddressRow, City, District

from reports.filters import ATTRIBUTES, Filters, parse_filters
from reports.statistics import REPORT, VALUES
from reports.survey_common import UNKNOWN

from .conftest import legacy

pytestmark = pytest.mark.django_db


def test_every_attribute_has_a_value_function() -> None:
    assert set(VALUES) == set(ATTRIBUTES)


def _by_label(user: User, f: Filters) -> dict[str, Any]:
    return {c.label: c for c in REPORT.rows(user, f)}


def test_default_attribute_is_gender_and_shares_add_up(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    legacy(actor, job_values, gender="M")
    legacy(actor, job_values, gender="M")
    legacy(actor, job_values, gender="F")
    by = _by_label(hr_user, Filters())
    assert by["Эрэгтэй"].qty == 2
    assert by["Эрэгтэй"].share == Decimal("66.7")
    assert by["Эмэгтэй"].share == Decimal("33.3")
    assert sum(c.qty for c in by.values()) == 3


def test_department_attribute(hr_user: User, hired: Employee, job_values: dict[str, Any]) -> None:
    by = _by_label(hr_user, Filters(attribute="department"))
    assert list(by) == [job_values["department"].name]
    assert by[job_values["department"].name].qty == 1


def test_age_attribute_uses_brackets(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    legacy(actor, job_values, birth_date=date(date.today().year - 30, 1, 1))
    legacy(actor, job_values, birth_date=None)
    by = _by_label(hr_user, Filters(attribute="age"))
    assert {label: c.qty for label, c in by.items()} == {"25–34": 1, UNKNOWN: 1}


def test_unknown_attribute_in_the_address_falls_back_to_gender(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    legacy(actor, job_values, gender="F")
    f = parse_filters(QueryDict("attribute=nope"))
    assert f.attribute == ""
    assert list(_by_label(hr_user, f)) == ["Эмэгтэй"]


def test_empty_value_is_counted_as_unknown(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    legacy(actor, job_values, marital_status=None)
    by = _by_label(hr_user, Filters(attribute="marital"))
    assert {label: c.qty for label, c in by.items()} == {UNKNOWN: 1}


def test_city_attribute_uses_the_first_address(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    ub = City.objects.create(name="Улаанбаатар")
    darkhan = City.objects.create(name="Дархан")
    district = District.objects.create(name="Баянгол", city=ub)
    person = legacy(actor, job_values)
    AddressRow.objects.create(employee=person, city=ub, district=district, street="Хан-Уул 3")
    AddressRow.objects.create(employee=person, city=darkhan, district=district, street="Төв 1")
    legacy(actor, job_values)
    by = _by_label(hr_user, Filters(attribute="city"))
    assert {label: c.qty for label, c in by.items()} == {"Улаанбаатар": 1, UNKNOWN: 1}


def test_attribute_select_is_in_the_filter_bar(client: Client, login_hr: User, hired: Employee) -> None:
    response = client.get("/reports/statistics/")
    assert response.status_code == 200
    page = response.content.decode()
    assert "Дэлгэрэнгүй хайлт, статистик" in page
    assert 'name="attribute"' in page
    assert '<option value="gender" selected>Хүйс</option>' in page


def test_accountant_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc")
    assert client.get("/reports/statistics/").status_code == 403
