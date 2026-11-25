"""The request-free page rules of the report page (reports.page_rules): pure functions, no database."""

from datetime import date

from django.http import QueryDict

from reports.filters import Filters
from reports.page_rules import (
    FOLDABLE,
    PLAIN_VIEW,
    added_names,
    address,
    group_text,
    month_param,
    next_sort,
    secondary_filters,
    sort_mark,
)
from reports.types import Column


def test_address_orders_filters_then_add_and_plain_view() -> None:
    f = Filters(branch=3, gender="F")
    assert address("/reports/x/", f, ["amount_x"]) == "/reports/x/?branch=3&gender=F&add=amount_x"
    assert address("/reports/x/", f, ["a", "b"]) == "/reports/x/?branch=3&gender=F&add=a&add=b"
    assert address("/reports/x/", f, plain=True) == "/reports/x/?branch=3&gender=F"
    assert PLAIN_VIEW == "view=plain"


def test_address_empty_query_is_bare_unless_plain() -> None:
    assert address("/reports/x/", Filters()) == "/reports/x/"
    assert address("/reports/x/", Filters(), plain=True) == "/reports/x/?view=plain"
    assert address("/reports/x/", Filters(), ["a"]) == "/reports/x/?add=a"


def test_next_sort_plain_click_toggles_asc_desc() -> None:
    assert next_sort("", "name") == "name"
    assert next_sort("name", "name") == "-name"
    assert next_sort("-name", "name") == "name"
    assert next_sort("name,-age", "name") == "name"  # a plain click replaces several keys


def test_next_sort_append_adds_flips_and_caps_at_max_sort_keys() -> None:
    assert next_sort("", "name", append=True) == "name"
    assert next_sort("name", "age", append=True) == "name,age"
    assert next_sort("name,-age", "age", append=True) == "name,age"  # an existing key flips in place
    assert next_sort("a,-b", "b", append=True) == "a,b"
    assert next_sort("a,b,c,d,e", "f", append=True) == "a,b,c,d,e"  # five keys is the most


def test_sort_mark_single_and_multi_key_arrows() -> None:
    assert sort_mark("name", "name") == "↑"
    assert sort_mark("-name", "name") == "↓"
    assert sort_mark("name", "age") == ""
    assert sort_mark("", "name") == ""
    assert sort_mark("name,-age", "name") == "↑1"
    assert sort_mark("name,-age", "age") == "↓2"


def test_group_text_only_for_several_keys() -> None:
    choices = [
        Column(key="branch", label="Салбар", value=lambda row: row),
        Column(key="department", label="Хэлтэс", value=lambda row: row),
    ]
    assert group_text("", choices) == ""
    assert group_text("branch", choices) == ""
    assert group_text("branch,department", choices) == "Салбар · Хэлтэс"
    assert group_text("branch,unknown", choices) == "Салбар · unknown"


def test_secondary_filters_empty_for_short_bar_and_foldable_only() -> None:
    assert secondary_filters(("state", "as_of", "branch", "department", "age_range")) == ()  # five: not slimmed
    assert secondary_filters(("state", "as_of", "period", "department", "emptype", "branch", "gender")) == (
        "emptype",
        "branch",
        "gender",
    )
    # quarter and year are not foldable, so only branch can be folded
    assert secondary_filters(("state", "as_of", "period", "department", "quarter", "year", "branch")) == ("branch",)
    assert "state" not in FOLDABLE  # the state filter is never folded away


def test_added_names_keeps_offered_once_in_order() -> None:
    get = QueryDict("add=a&add=zz&add=b&add=a")
    assert added_names(get, ["a", "b"]) == ["a", "b"]
    assert added_names(QueryDict(""), ["a", "b"]) == []


def test_month_param_blank_for_this_month() -> None:
    today = date(2026, 11, 25)
    assert month_param(date(2026, 11, 3), today) == ""
    assert month_param(date(2026, 12, 1), today) == "2026-12"
    assert month_param(date(2025, 11, 3), today) == "2025-11"
