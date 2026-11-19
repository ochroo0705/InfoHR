"""The order register's filters and filter options as a request-free service (shared by the page and the API)."""

from datetime import date

import pytest

from employees.models import Department, DepartmentExt, OrderState, OrderType
from employees.services import order_register
from employees.services.order_register_page import (
    FilterOptions,
    RegisterQuery,
    filter_options,
    parse_query,
    query_string,
)

pytestmark = pytest.mark.django_db


def test_parse_query_defaults() -> None:
    assert parse_query({}) == RegisterQuery(
        year=None,
        order_type=None,
        department=None,
        state="",
        q="",
        sort=order_register.DEFAULT_SORT,
    )


def test_parse_query_keeps_good_values() -> None:
    query = parse_query(
        {
            "year": "2025",
            "order_type": str(OrderType.HIRED.value),
            "department": "7",
            "state": OrderState.SIGNED.value,
            "q": "Бат",
            "sort": "-employee",
        }
    )
    assert query == RegisterQuery(
        year=2025,
        order_type=OrderType.HIRED.value,
        department=7,
        state=OrderState.SIGNED.value,
        q="Бат",
        sort="-employee",
    )


def test_parse_query_accepts_legacy_state() -> None:
    assert parse_query({"state": order_register.LEGACY}).state == order_register.LEGACY


def test_parse_query_ignores_bad_values() -> None:
    query = parse_query({"year": "abc", "order_type": "!", "department": "x", "state": "zzz", "sort": "bogus"})
    assert query.year is None
    assert query.order_type is None
    assert query.department is None
    assert query.state == ""
    assert query.sort == order_register.DEFAULT_SORT


@pytest.mark.parametrize("year", ["0", "10000"])
def test_parse_query_year_out_of_range_is_none(year: str) -> None:
    assert parse_query({"year": year}).year is None


def test_parse_query_unknown_order_type_is_none() -> None:
    assert parse_query({"order_type": "999999"}).order_type is None


def test_parse_query_cuts_q_to_100_and_strips() -> None:
    query = parse_query({"q": "   " + "x" * 150 + "   "})
    assert query.q == "x" * 100


def test_filter_options_states_have_no_pending_and_end_with_legacy() -> None:
    options = filter_options(date(2026, 11, 19))
    keys = [key for key, _label in options.states]
    assert OrderState.PENDING.value not in keys
    assert options.states[-1] == (order_register.LEGACY, "MACS")


def test_filter_options_types_are_order_types() -> None:
    options = filter_options(date(2026, 11, 19))
    assert options.types == list(OrderType.choices)


def test_filter_options_years_are_twelve_newest_first() -> None:
    options = filter_options(date(2026, 11, 19))
    assert options.years == list(range(2026, 2014, -1))
    assert len(options.years) == 12


def test_filter_options_departments_skip_inactive() -> None:
    active = Department.objects.create(name="Идэвхтэй хэлтэс")
    inactive = Department.objects.create(name="Идэвхгүй хэлтэс")
    DepartmentExt.objects.create(department=inactive, active=False)
    options = filter_options(date(2026, 11, 19))
    assert (active.pk, "Идэвхтэй хэлтэс") in options.departments
    assert all(pk != inactive.pk for pk, _name in options.departments)


def test_filter_options_department_with_null_name_has_empty_label() -> None:
    nameless = Department.objects.create(name=None)
    options = filter_options(date(2026, 11, 19))
    assert (nameless.pk, "") in options.departments


def test_filter_options_is_a_dataclass_of_lists() -> None:
    options = filter_options(date(2026, 11, 19))
    assert isinstance(options, FilterOptions)
    assert isinstance(options.departments, list)


def test_query_string_skips_empty_fields() -> None:
    query = RegisterQuery(year=2026, order_type=None, department=None, state="", q="", sort="")
    assert query_string(query) == "year=2026"


def test_query_string_order_is_q_sort_year_type_department_state() -> None:
    query = RegisterQuery(year=2026, order_type=2, department=5, state="signed", q="Бат", sort="-date")
    assert query_string(query) == "q=%D0%91%D0%B0%D1%82&sort=-date&year=2026&order_type=2&department=5&state=signed"
