from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone
from employees.models import Employee
from macs.models import FamilyRelation, FamilyRow, PresentRow, PresentType

from reports.filters import Filters
from reports.gifts import DUE, GIVEN
from reports.types import Column, Report

from .conftest import count_queries, legacy

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_production_rows() -> None:
    """The test database may hold production gift and family rows; each test starts empty."""
    PresentRow.objects.all().delete()
    FamilyRow.objects.all().delete()


def _column(report: Report, key: str) -> Column:
    return next(c for c in report.columns if c.key == key)


def _type(name: str) -> PresentType:
    return PresentType.objects.create(name=name)


def _gift(
    employee: Employee,
    kind: PresentType,
    given_year: int = 2025,
    child_age: int = 7,
    childqty: int = 1,
    price: int = 1000,
    given: int = 1,
) -> PresentRow:
    """A gift row as the gift table holds one (every column is NOT NULL)."""
    return PresentRow.objects.create(
        employee=employee,
        present_type=kind,
        given_year=given_year,
        child_age=child_age,
        childqty=childqty,
        price=price,
        given=given,
        pdate=date(given_year, 12, 1),
    )


def _child(employee: Employee, birth: date | None, given: str = "Бат", fm_type: str = "son") -> FamilyRow:
    names = {"son": "Хүү", "daughter": "Охин"}
    relation = FamilyRelation.objects.get_or_create(fm_type=fm_type, defaults={"name": names[fm_type]})[0]
    return FamilyRow.objects.create(employee=employee, relation=relation, given_name=given, birth_date=birth)


def _three_people(actor: User, job_values: dict[str, Any], hired: Employee) -> list[Employee]:
    """Three different people: one query per row would show as a difference in the counts below."""
    return [hired, legacy(actor, job_values), legacy(actor, job_values)]


# F2 «Хүүхдэд бэлэг олгосон жагсаалт»


def test_year_defaults_to_this_year_and_filters_type(hr_user: User, hired: Employee) -> None:
    this_year = timezone.localdate().year
    kind = _type("Баяр")
    other = _type("Хүүхдийн өдөр")
    _gift(hired, kind, given_year=this_year)
    _gift(hired, kind, given_year=this_year - 1)
    _gift(hired, other, given_year=this_year)
    assert len(GIVEN.rows(hr_user, Filters())) == 2
    assert len(GIVEN.rows(hr_user, Filters(present_type=kind.pk))) == 1
    assert len(GIVEN.rows(hr_user, Filters(year=this_year - 1))) == 1


def test_total_is_price_times_children(hr_user: User, hired: Employee) -> None:
    _gift(hired, _type("Баяр"), price=1000, childqty=3)
    row = GIVEN.rows(hr_user, Filters(year=2025))[0]
    assert _column(GIVEN, "total").value(row) == 3000
    assert _column(GIVEN, "price").value(row) == 1000


def test_given_flag_text(hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee) -> None:
    kind = _type("Баяр")
    _gift(hired, kind, given=1)
    _gift(legacy(actor, job_values), kind, given=0)
    values = sorted(str(_column(GIVEN, "given").value(r)) for r in GIVEN.rows(hr_user, Filters(year=2025)))
    assert values == ["Тийм", "Үгүй"]


def test_gift_list_refused_for_accountant_and_employee(client: Client, login_as: Callable[..., User]) -> None:
    for role in ("Accountant", "Employee"):
        login_as(client, role, f"viewer-{role}")
        assert client.get("/reports/gifts-given/").status_code == 403
        assert client.get("/reports/gifts-due/").status_code == 403
        client.logout()


def test_gift_list_pages_print_and_excel_open(client: Client, login_hr: User) -> None:
    for key in ("gifts-given", "gifts-due"):
        for suffix in ("", "print/", "excel/"):
            assert client.get(f"/reports/{key}/{suffix}").status_code == 200


def test_group_options_are_real_column_keys() -> None:
    for report in (GIVEN, DUE):
        keys = {c.key for c in report.columns}
        assert set(report.group_options) <= keys


def test_gift_query_count_does_not_grow_with_rows(
    hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    first, *others = _three_people(actor, job_values, hired)
    kind = _type("Баяр")
    _gift(first, kind)
    one = count_queries(
        GIVEN, hr_user, Filters(year=2025)
    )  # (rows alone, rows and every cell); warmed first, see count_queries
    for person in others:
        _gift(person, kind)
    assert len(GIVEN.rows(hr_user, Filters(year=2025))) == 3
    three = count_queries(GIVEN, hr_user, Filters(year=2025))
    assert three[1] - three[0] == one[1] - one[0]  # rendering adds the same queries for 1 and 3 people


# F3 «Хүүхдэд бэлэг олгох»


def test_due_lists_children_with_no_gift_row_for_the_age(hr_user: User, hired: Employee) -> None:
    _child(hired, date(2018, 6, 1), "Бат")
    _child(hired, date(2018, 9, 1), "Гантулга")
    rows = DUE.rows(hr_user, Filters(year=2025))
    assert len(rows) == 1
    assert rows[0].age == 7
    assert rows[0].children == 2


def test_age_counted_on_31_december_for_a_past_year(hr_user: User, hired: Employee) -> None:
    _child(hired, date(2018, 6, 1))  # 6 on 31 May 2025, 7 on 31 December 2025
    rows = DUE.rows(hr_user, Filters(year=2025))
    assert [r.age for r in rows] == [7]


def test_age_counted_on_today_for_this_year(hr_user: User, hired: Employee) -> None:
    this_year = timezone.localdate().year
    _child(hired, date(this_year - 7, 1, 1))  # on any day of this year the child is 7
    rows = DUE.rows(hr_user, Filters(year=this_year))
    assert [r.age for r in rows] == [7]


def test_a_gift_row_for_that_age_and_year_hides_the_line(hr_user: User, hired: Employee) -> None:
    _child(hired, date(2018, 6, 1))
    _gift(hired, _type("Баяр"), given_year=2025, child_age=7)
    assert DUE.rows(hr_user, Filters(year=2025)) == []


def test_gift_row_of_another_year_or_age_does_not_hide_it(hr_user: User, hired: Employee) -> None:
    kind = _type("Баяр")
    _child(hired, date(2018, 6, 1))
    _gift(hired, kind, given_year=2024, child_age=7)
    _gift(hired, kind, given_year=2025, child_age=6)
    rows = DUE.rows(hr_user, Filters(year=2025))
    assert [r.age for r in rows] == [7]


def test_present_type_filter_only_counts_rows_of_that_type(hr_user: User, hired: Employee) -> None:
    gift = _type("Баяр")
    other = _type("Хүүхдийн өдөр")
    _child(hired, date(2018, 6, 1))
    _gift(hired, gift, given_year=2025, child_age=7)
    assert DUE.rows(hr_user, Filters(year=2025, present_type=gift.pk)) == []
    assert len(DUE.rows(hr_user, Filters(year=2025, present_type=other.pk))) == 1


def test_contract_staff_and_children_without_birth_date_are_not_listed(
    hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    contract = legacy(actor, job_values, contract_flag="yes")
    _child(contract, date(2018, 6, 1), "Гэрээт")
    _child(hired, None, "Төрсөн огнооГүй")
    assert DUE.rows(hr_user, Filters(year=2025)) == []


def test_age_range_filter(hr_user: User, hired: Employee) -> None:
    _child(hired, date(2022, 1, 1), "Бага")  # 3 on 31 December 2025
    _child(hired, date(2015, 1, 1), "Том")  # 10 on 31 December 2025
    rows = DUE.rows(hr_user, Filters(year=2025, age_from=5))
    assert [r.age for r in rows] == [10]


def test_age_to_only_filter(hr_user: User, hired: Employee) -> None:
    _child(hired, date(2022, 1, 1), "Бага")  # 3 on 31 December 2025
    _child(hired, date(2015, 1, 1), "Том")  # 10 on 31 December 2025
    rows = DUE.rows(hr_user, Filters(year=2025, age_to=5))
    assert [r.age for r in rows] == [3]


def test_daughter_is_counted_as_a_child(hr_user: User, hired: Employee) -> None:
    _child(hired, date(2018, 6, 1), "Сараа", fm_type="daughter")
    rows = DUE.rows(hr_user, Filters(year=2025))
    assert [(r.age, r.children) for r in rows] == [(7, 1)]


def test_future_year_counts_ages_to_31_december(hr_user: User, hired: Employee) -> None:
    year = timezone.localdate().year + 1
    _child(hired, date(2018, 6, 1))  # on 31 December of that year the child is year - 2018 years old
    rows = DUE.rows(hr_user, Filters(year=year))
    assert [r.age for r in rows] == [year - 2018]


def test_due_query_count_does_not_grow_with_rows(
    hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    first, *others = _three_people(actor, job_values, hired)
    _child(first, date(2018, 6, 1))
    one = count_queries(
        DUE, hr_user, Filters(year=2025)
    )  # (rows alone, rows and every cell); warmed first, see count_queries
    for person in others:
        _child(person, date(2018, 6, 1))
    assert len(DUE.rows(hr_user, Filters(year=2025))) == 3
    three = count_queries(DUE, hr_user, Filters(year=2025))
    assert three[1] - three[0] == one[1] - one[0]  # rendering adds the same queries for 1 and 3 people
