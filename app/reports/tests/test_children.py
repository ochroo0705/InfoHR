from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee
from macs.models import FamilyRelation, FamilyRow

from reports.children import REPORT
from reports.filters import Filters

from .conftest import legacy

pytestmark = pytest.mark.django_db


def _son() -> FamilyRelation:
    return FamilyRelation.objects.create(name="Хүү", fm_type="son")


def _daughter() -> FamilyRelation:
    return FamilyRelation.objects.create(name="Охин", fm_type="daughter")


def _spouse() -> FamilyRelation:
    return FamilyRelation.objects.create(name="Эхнэр, нөхөр", fm_type="spouse")


def _child(employee: Employee, relation: FamilyRelation, given: str, birth: date | None) -> FamilyRow:
    return FamilyRow.objects.create(employee=employee, relation=relation, given_name=given, birth_date=birth)


def _names(rows: list[Any]) -> list[str]:
    return [r.item.given_name for r in rows]


def test_only_sons_and_daughters_are_listed(hr_user: User, hired: Employee) -> None:
    _child(hired, _son(), "Бат", date(2015, 1, 1))
    _child(hired, _daughter(), "Сараа", date(2018, 1, 1))
    _child(hired, _spouse(), "Оюу", date(1990, 1, 1))
    assert sorted(_names(REPORT.rows(hr_user, Filters()))) == ["Бат", "Сараа"]


def test_age_on_the_chosen_date(hr_user: User, hired: Employee) -> None:
    _child(hired, _son(), "Бат", date(2015, 5, 1))
    before = REPORT.rows(hr_user, Filters(as_of=date(2026, 4, 30)))
    assert [r.age for r in before] == [10]
    after = REPORT.rows(hr_user, Filters(as_of=date(2026, 5, 1)))
    assert [r.age for r in after] == [11]


def test_age_range_excludes_children_without_birth_date(hr_user: User, hired: Employee) -> None:
    _child(hired, _son(), "Бат", date(2015, 5, 1))
    _child(hired, _son(), "Гантулга", None)
    rows = REPORT.rows(hr_user, Filters(age_from=0, age_to=12))
    assert _names(rows) == ["Бат"]


def test_no_age_filter_includes_children_without_birth_date(hr_user: User, hired: Employee) -> None:
    _child(hired, _son(), "Гантулга", None)
    rows = REPORT.rows(hr_user, Filters())
    assert _names(rows) == ["Гантулга"]
    assert rows[0].age is None


def test_row_of_an_invisible_or_left_person_is_dropped(hr_user: User, hired: Employee, left_employee: Employee) -> None:
    _child(left_employee, _son(), "Төмөр", date(2012, 1, 1))
    _child(hired, _son(), "Бат", date(2015, 1, 1))
    assert _names(REPORT.rows(hr_user, Filters())) == ["Бат"]
    assert sorted(_names(REPORT.rows(hr_user, Filters(state="all")))) == ["Бат", "Төмөр"]


def test_children_follow_parent_name_then_birth_date(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    parent = legacy(actor, job_values, family_name="Аа", given_name="Аа")
    _child(parent, _son(), "Второй", date(2016, 1, 1))
    _child(parent, _son(), "Первый", date(2010, 1, 1))
    rows = REPORT.rows(hr_user, Filters())
    assert _names(rows) == ["Первый", "Второй"]


def test_accountant_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc")
    assert client.get("/reports/children/").status_code == 403


def test_child_born_after_the_as_of_day_has_no_age(hr_user: User, hired: Employee) -> None:
    _child(hired, _son(), "Төрөөгүй", date(2027, 1, 1))
    rows = REPORT.rows(hr_user, Filters(as_of=date(2026, 4, 30)))
    assert _names(rows) == ["Төрөөгүй"]
    assert rows[0].age is None
    assert REPORT.rows(hr_user, Filters(as_of=date(2026, 4, 30), age_from=0)) == []
