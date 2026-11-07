"""Layout address parameters: layout, lby, lby2, lval, lchart, lmonth. A bad value falls back to the default."""

import pytest
from django.http import QueryDict

from reports.filters import Filters, parse_filters, to_query


def _parse(raw: str) -> Filters:
    return parse_filters(QueryDict(raw))


def test_full_set_is_read() -> None:
    f = _parse("layout=board&lby=department&lchart=donut&lmonth=2026-03&lval=pay:sum&lby2=end")
    assert f.layout == "board"
    assert f.lby == "department"
    assert f.lby2 == "end"
    assert f.lval == "pay:sum"
    assert f.lchart == "donut"
    assert f.lmonth == "2026-03"


def test_unknown_layout_and_table_fall_back() -> None:
    assert _parse("layout=nope").layout == ""
    assert _parse("layout=table").layout == ""


@pytest.mark.parametrize("layout", ["board", "calendar", "timeline", "cards", "chart", "pivot"])
def test_known_layouts_are_kept(layout: str) -> None:
    assert _parse(f"layout={layout}").layout == layout


def test_unknown_chart_falls_back() -> None:
    assert _parse("lchart=x").lchart == ""
    assert _parse("lchart=bar").lchart == "bar"


@pytest.mark.parametrize("month", ["2026-13", "abc", "0000-01", "9999-99", "2026-00", "2026-1"])
def test_bad_month_falls_back(month: str) -> None:
    assert _parse(f"lmonth={month}").lmonth == ""


def test_good_month_is_kept() -> None:
    assert _parse("lmonth=2026-12").lmonth == "2026-12"


@pytest.mark.parametrize("key", ["Bad Key!", "a" * 5000, "a1"], ids=["space-bang", "long", "digit"])
def test_bad_column_key_falls_back(key: str) -> None:
    assert _parse(f"lby={key}").lby == ""
    assert _parse(f"lby2={key}").lby2 == ""


def test_value_count_is_kept() -> None:
    assert _parse("lval=count").lval == "count"


@pytest.mark.parametrize(
    "value", ["a:b:c", "pay:median", "pay", "a" * 5000], ids=["three-parts", "median", "no-agg", "long"]
)
def test_bad_value_falls_back(value: str) -> None:
    assert _parse(f"lval={value}").lval == ""


def test_repeated_parameter_takes_the_last_value() -> None:
    assert _parse("layout=board&layout=nope").layout == ""
    assert _parse("layout=nope&layout=board").layout == "board"


def test_default_filters_write_no_layout_keys() -> None:
    query = to_query(Filters())
    for key in ("layout", "lby", "lby2", "lval", "lchart", "lmonth"):
        assert key not in query


def test_table_layout_is_not_written() -> None:
    assert "layout" not in to_query(Filters(layout="table"))


def test_month_year_bounds() -> None:
    assert _parse("lmonth=1899-12").lmonth == ""
    assert _parse("lmonth=1900-01").lmonth == "1900-01"
    assert _parse("lmonth=2100-12").lmonth == "2100-12"
    assert _parse("lmonth=2101-01").lmonth == ""


@pytest.mark.parametrize("name", ["lmonth", "layout", "lchart"])
def test_long_value_falls_back(name: str) -> None:
    assert getattr(_parse(f"{name}={'a' * 5000}"), name) == ""


def test_value_keeps_first_valid_pair() -> None:
    assert _parse("lval=pay:sum,bad!").lval == "pay:sum"


def test_count_value_round_trips() -> None:
    assert _parse(to_query(Filters(lval="count"))).lval == "count"


def test_full_set_round_trips() -> None:
    f = Filters(
        layout="chart",
        lby="department",
        lby2="end",
        lval="pay:sum",
        lchart="line",
        lmonth="2026-03",
    )
    assert _parse(to_query(f)) == f
