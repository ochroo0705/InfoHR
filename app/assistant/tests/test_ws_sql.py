import json

import pytest
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery, check_sql

from assistant.ws_sql import (
    Filter,
    Spec,
    SpecError,
    base_orders,
    count_sql,
    group_sql,
    spec_from_json,
    spec_to_json,
    usable_columns,
    wrap_sql,
)

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(
        Column("NAME", "full name"),
        Column("DEPARTMENT", "department"),
        Column("LATE_DAYS", "days late"),
    ),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))

BASE = "SELECT NAME, DEPARTMENT, LATE_DAYS FROM GOV_EMPLOYEES"
COLS = ("NAME", "DEPARTMENT", "LATE_DAYS")


def test_wrap_default_is_checked_ok() -> None:
    checked = check_sql(wrap_sql(BASE, COLS, Spec()), CATALOGUE)

    assert isinstance(checked, CheckedQuery)
    assert checked.views == frozenset({"GOV_EMPLOYEES"})


def test_wrap_filter_sort_page_is_checked_ok() -> None:
    spec = Spec(
        filters=(Filter("DEPARTMENT", "eq", "Sales"),),
        sort=(("LATE_DAYS", "desc"),),
    )

    checked = check_sql(wrap_sql(BASE, COLS, spec, page=1), CATALOGUE)

    assert "ROWS 101 TO 200" in wrap_sql(BASE, COLS, spec, page=1)
    assert "FIRST 100 SKIP 100" in checked.sql
    assert "DEPARTMENT = 'Sales'" in checked.sql
    assert "ORDER BY LATE_DAYS DESC" in checked.sql
    assert "FETCH" not in checked.sql
    assert "OFFSET" not in checked.sql


def test_unknown_column_refused() -> None:
    with pytest.raises(SpecError):
        wrap_sql(BASE, COLS, Spec(filters=(Filter("SALARY", "eq", "1"),)))


def test_unusable_column_names_excluded() -> None:
    assert usable_columns(("NAME", "COUNT", "a b")) == ("NAME", "COUNT")
    with pytest.raises(SpecError):
        wrap_sql("SELECT 1 AS \"a b\" FROM GOV_EMPLOYEES", ("a b",), Spec())


def test_tool_column_naming_an_unusable_base_column_is_refused() -> None:
    with pytest.raises(SpecError):
        wrap_sql(BASE, ("NAME", "a b"), Spec(columns=("a b",)))


def test_lowercase_base_column_is_emitted_upper_cased() -> None:
    checked = check_sql(
        wrap_sql("SELECT NAME FROM GOV_EMPLOYEES", ("name",), Spec(filters=(Filter("name", "eq", "x"),))),
        CATALOGUE,
    )

    assert checked.sql.startswith("SELECT NAME FROM (")
    assert "NAME = 'x'" in checked.sql
    assert "name" not in checked.sql


def test_sort_direction_is_case_insensitive() -> None:
    checked = check_sql(wrap_sql(BASE, COLS, Spec(sort=(("LATE_DAYS", "DESC"),))), CATALOGUE)

    assert "ORDER BY LATE_DAYS DESC" in checked.sql


def test_bad_sort_direction_refused() -> None:
    with pytest.raises(SpecError):
        wrap_sql(BASE, COLS, Spec(sort=(("LATE_DAYS", "up"),)))


def test_spec_json_roundtrip_drops_missing_column() -> None:
    spec = Spec(
        columns=("NAME", "DEPARTMENT"),
        filters=(Filter("DEPARTMENT", "contains", "Sa"), Filter("SALARY", "eq", "1")),
        sort=(("LATE_DAYS", "desc"),),
    )

    restored = spec_from_json(spec_to_json(spec), COLS)

    assert restored == Spec(
        columns=("NAME", "DEPARTMENT"),
        filters=(Filter("DEPARTMENT", "contains", "Sa"),),
        sort=(("LATE_DAYS", "desc"),),
    )


def test_spec_from_bad_json_is_empty_spec() -> None:
    assert spec_from_json("{not json", COLS) == Spec()
    assert spec_from_json("[1, 2]", COLS) == Spec()


def test_spec_from_deeply_nested_json_is_empty_spec() -> None:
    assert spec_from_json("[" * 100000 + "]" * 100000, COLS) == Spec()


@pytest.mark.parametrize(
    "value",
    ["'); DROP TABLE X; --", "%", "_", "a\\b", "a'b", "x" * 200],
)
def test_hostile_value_stays_a_literal(value: str) -> None:
    spec = Spec(filters=(Filter("NAME", "contains", value), Filter("NAME", "eq", value)))

    checked = check_sql(wrap_sql(BASE, COLS, spec), CATALOGUE)

    literal = value.replace("'", "''")
    escaped = literal.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    assert checked.sql.count("WHERE") == 1
    assert checked.sql.count(" FROM ") == 2
    assert f"NAME = '{literal}'" in checked.sql
    assert f"LIKE UPPER('%{escaped}%') ESCAPE '\\'" in checked.sql


def test_filter_value_over_200_chars_refused() -> None:
    with pytest.raises(SpecError):
        wrap_sql(BASE, COLS, Spec(filters=(Filter("NAME", "eq", "x" * 201),)))
    with pytest.raises(SpecError):
        count_sql(BASE, COLS, Spec(filters=(Filter("NAME", "contains", "x" * 10000),)))


def test_count_sql_checked_ok() -> None:
    spec = Spec(filters=(Filter("DEPARTMENT", "eq", "Sales"),))

    checked = check_sql(count_sql(BASE, COLS, spec), CATALOGUE)

    assert checked.sql.startswith("SELECT COUNT(*) AS N FROM (")
    assert "DEPARTMENT = 'Sales'" in checked.sql
    assert "GROUP BY" not in checked.sql


def test_count_sql_with_group_by_counts_groups_and_checks() -> None:
    spec = Spec(filters=(Filter("LATE_DAYS", "gt", "1"),), group_by="DEPARTMENT")

    checked = check_sql(count_sql(BASE, COLS, spec), CATALOGUE)

    assert "COUNT(*)" in checked.sql
    assert "GROUP BY DEPARTMENT" in checked.sql
    assert "ws_groups" in checked.sql
    assert "LATE_DAYS > 1" in checked.sql


def test_count_sql_group_by_refuses_count_column() -> None:
    with pytest.raises(SpecError, match="cannot be grouped"):
        count_sql(BASE, ("N", "DEPARTMENT", "LATE_DAYS"), Spec(group_by="N"))


def test_group_sql_checked_ok() -> None:
    spec = Spec(filters=(Filter("LATE_DAYS", "gt", "3"),), group_by="DEPARTMENT")

    checked = check_sql(group_sql(BASE, COLS, spec, page=0), CATALOGUE)

    assert "GROUP BY DEPARTMENT" in checked.sql
    assert "ORDER BY N DESC, DEPARTMENT ASC" in checked.sql
    assert "LATE_DAYS > 3" in checked.sql
    assert checked.sql.startswith("SELECT FIRST 100 DEPARTMENT, COUNT(*) AS N FROM (")


def test_group_on_missing_column_refused() -> None:
    with pytest.raises(SpecError):
        group_sql(BASE, COLS, Spec(group_by="SALARY"))


def test_group_without_column_refused() -> None:
    with pytest.raises(SpecError):
        group_sql(BASE, COLS, Spec())


def test_group_on_column_named_n_refused() -> None:
    with pytest.raises(SpecError):
        group_sql(BASE, ("N",), Spec(group_by="N"))


def test_gt_needs_a_number() -> None:
    with pytest.raises(SpecError):
        wrap_sql(BASE, COLS, Spec(filters=(Filter("LATE_DAYS", "gt", "abc"),)))
    with pytest.raises(SpecError):
        count_sql(BASE, COLS, Spec(filters=(Filter("LATE_DAYS", "lt", "NaN"),)))


def test_gt_number_is_written_as_a_number() -> None:
    checked = check_sql(
        count_sql(BASE, COLS, Spec(filters=(Filter("LATE_DAYS", "gt", "1E+2"),))),
        CATALOGUE,
    )

    assert "LATE_DAYS > 100" in checked.sql


def test_spec_json_with_unhashable_op_drops_filter() -> None:
    assert spec_from_json('{"filters":[{"column":"NAME","op":["eq"]}]}', COLS) == Spec()
    assert spec_from_json('{"filters":[{"column":"NAME","op":{"a":1}}]}', COLS) == Spec()


def test_spec_json_with_non_text_value_or_column_drops_filter() -> None:
    assert spec_from_json('{"filters":[{"column":"NAME","op":"eq","value":5}]}', COLS) == Spec()
    assert spec_from_json('{"filters":[{"column":"NAME","op":"eq","value":["x"]}]}', COLS) == Spec()
    assert spec_from_json('{"filters":[{"column":["NAME"],"op":"eq","value":"x"}]}', COLS) == Spec()


def test_spec_naming_unusable_and_usable_column_is_refused() -> None:
    with pytest.raises(SpecError):
        wrap_sql(BASE, ("NAME", "a b"), Spec(columns=("NAME", "a b")))


def test_paging_without_sort_orders_by_first_column() -> None:
    checked = check_sql(wrap_sql(BASE, COLS, Spec(), page=2), CATALOGUE)

    assert "ORDER BY NAME ASC" in checked.sql
    assert "FIRST 100 SKIP 200" in checked.sql


def test_wrap_ignores_group_by() -> None:
    plain = wrap_sql(BASE, COLS, Spec())

    assert wrap_sql(BASE, COLS, Spec(group_by="DEPARTMENT")) == plain


@pytest.mark.parametrize("value", ["1E+999999999", "-1E+999999999", "1E-999999999", "-1E-999999999"])
def test_gt_huge_exponent_refused(value: str) -> None:
    with pytest.raises(SpecError):
        count_sql(BASE, COLS, Spec(filters=(Filter("LATE_DAYS", "gt", value),)))


@pytest.mark.parametrize("value", ["1E+999999999", "-1E+999999999", "1E-999999999"])
def test_spec_json_drops_gt_lt_with_huge_exponent(value: str) -> None:
    text = f'{{"filters":[{{"column":"LATE_DAYS","op":"gt","value":"{value}"}},{{"column":"LATE_DAYS","op":"lt","value":"{value}"}}]}}'

    assert spec_from_json(text, COLS) == Spec()


@pytest.mark.parametrize(
    "item",
    [
        {"column": "LATE_DAYS", "op": "gt"},
        {"column": "LATE_DAYS", "op": "lt", "value": "abc"},
        {"column": "LATE_DAYS", "op": "gt", "value": ""},
    ],
)
def test_spec_json_drops_gt_lt_without_a_number(item: dict) -> None:
    text = json.dumps({"filters": [item]})

    assert spec_from_json(text, COLS) == Spec()


def test_spec_json_keeps_valid_gt() -> None:
    text = '{"filters":[{"column":"LATE_DAYS","op":"gt","value":"2.5"}]}'

    assert spec_from_json(text, COLS) == Spec(filters=(Filter("LATE_DAYS", "gt", "2.5"),))


@pytest.mark.parametrize("page", ["1", True, 1.5, -1])
def test_page_must_be_a_whole_number(page: object) -> None:
    with pytest.raises(SpecError):
        wrap_sql(BASE, COLS, Spec(), page=page)  # type: ignore[arg-type]
    with pytest.raises(SpecError):
        group_sql(BASE, COLS, Spec(group_by="DEPARTMENT"), page=page)  # type: ignore[arg-type]


def test_a_name_twice_in_any_case_is_not_usable() -> None:
    assert usable_columns(("ID", "id", "NAME")) == ("NAME",)
    assert usable_columns(("ID", "NAME")) == ("ID", "NAME")


ACTIVE_BASE = (
    "SELECT DEPARTMENT_NAME, COUNT(*) AS ACTIVE_COUNT FROM GOV_EMPLOYEES "
    "GROUP BY DEPARTMENT_NAME ORDER BY COUNT(*) DESC"
)
ACTIVE_COLS = ("DEPARTMENT_NAME", "ACTIVE_COUNT")
ACTIVE_CATALOGUE = Catalogue(
    views=(
        View(
            name="GOV_EMPLOYEES",
            description="Employees you may see",
            columns=(Column("DEPARTMENT_NAME", "department"),),
        ),
    )
)


def test_base_order_by_aggregate_keeps_alias_and_direction() -> None:
    assert base_orders(ACTIVE_BASE, ACTIVE_COLS) == ["ACTIVE_COUNT DESC"]


def test_base_order_by_plain_column_keeps_it() -> None:
    base = "SELECT NAME, DEPARTMENT FROM GOV_EMPLOYEES ORDER BY DEPARTMENT DESC, NAME ASC"
    assert base_orders(base, ("NAME", "DEPARTMENT")) == ["DEPARTMENT DESC", "NAME ASC"]


def test_base_order_stops_at_first_term_it_cannot_name() -> None:
    base = "SELECT NAME, DEPARTMENT FROM GOV_EMPLOYEES ORDER BY DEPARTMENT DESC, LATE_DAYS + 1, NAME"
    assert base_orders(base, ("NAME", "DEPARTMENT")) == ["DEPARTMENT DESC"]


def test_base_order_with_trailing_semicolon_and_no_order_is_empty() -> None:
    assert base_orders("SELECT NAME FROM GOV_EMPLOYEES;", ("NAME",)) == []


def test_base_order_that_does_not_parse_is_empty() -> None:
    assert base_orders("SELECT FROM WHERE ORDER BY", ("NAME",)) == []


def test_wrap_keeps_base_order_then_adds_first_column_for_page() -> None:
    checked = check_sql(wrap_sql(ACTIVE_BASE, ACTIVE_COLS, Spec(), page=0), ACTIVE_CATALOGUE)

    assert "ORDER BY ACTIVE_COUNT DESC, DEPARTMENT_NAME ASC" in checked.sql


def test_wrap_keeps_base_order_without_page_and_adds_nothing() -> None:
    sql = wrap_sql(ACTIVE_BASE, ACTIVE_COLS, Spec())

    assert sql.endswith("ORDER BY ACTIVE_COUNT DESC")
    assert "DEPARTMENT_NAME ASC" not in sql


def test_wrap_does_not_repeat_first_column_already_in_base_order() -> None:
    base = "SELECT NAME, DEPARTMENT FROM GOV_EMPLOYEES ORDER BY NAME DESC"

    sql = wrap_sql(base, ("NAME", "DEPARTMENT"), Spec(), page=0)

    wrapper_order = sql.split(") ws_base ", 1)[1]  # the ORDER BY written by the wrapper, after the saved query
    assert wrapper_order == "ORDER BY NAME DESC ROWS 1 TO 100"


def test_wrap_explicit_sort_wins_over_base_order() -> None:
    sql = wrap_sql(ACTIVE_BASE, ACTIVE_COLS, Spec(sort=(("DEPARTMENT_NAME", "asc"),)), page=0)

    assert "ORDER BY DEPARTMENT_NAME ASC" in sql
    assert "ACTIVE_COUNT" not in sql.split("ORDER BY")[1]


def test_wrap_without_base_order_or_page_has_no_order_by() -> None:
    assert "ORDER BY" not in wrap_sql(BASE, COLS, Spec())
