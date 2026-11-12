from decimal import Decimal

import pytest

from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery, check_sql
from sqlcore.explain import Explanation, Warning, as_english, explain, tidy_result
from sqlcore.limits import Result

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(
        Column("EMP_ID", "employee id"),
        Column("NAME", "full name"),
        Column("DEPT", "department"),
    ),
)
CHILDREN = View(
    name="GOV_CHILDREN",
    description="Children of employees",
    columns=(
        Column("EMP_ID", "employee id"),
        Column("BIRTH_DATE", "birth date"),
    ),
)
CATALOGUE = Catalogue(views=(EMPLOYEES, CHILDREN))


def _checked(sql: str) -> CheckedQuery:
    return check_sql(sql, CATALOGUE)


def _result(rows: list[tuple[object, ...]], truncated: bool = False) -> Result:
    return Result(columns=("C1",), rows=tuple(rows), truncated=truncated)


def test_views_filters_group_and_aggregates_are_listed() -> None:
    query = _checked(
        "SELECT e.NAME, COUNT(*) AS N FROM GOV_EMPLOYEES e "
        "JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID "
        "WHERE e.DEPT = 'IT' AND c.BIRTH_DATE > '2010-01-01' GROUP BY e.NAME"
    )

    result = explain(query, _result([("Aigerim", 2)]), CATALOGUE)

    assert result.views == ("GOV_CHILDREN", "GOV_EMPLOYEES")
    assert result.filters == ("e.DEPT = 'IT'", "c.BIRTH_DATE > '2010-01-01'")
    assert result.group_by == ("e.NAME",)
    assert result.aggregates == ("COUNT(*)",)
    assert result.row_count == 1


def test_join_with_count_and_no_distinct_warns_rows_not_people() -> None:
    join_count = _checked(
        "SELECT COUNT(*) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID"
    )
    join_count_col = _checked(
        "SELECT COUNT(c.EMP_ID) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID"
    )
    join_distinct = _checked(
        "SELECT COUNT(DISTINCT e.EMP_ID) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID"
    )
    single_view = _checked("SELECT COUNT(*) FROM GOV_EMPLOYEES e")
    rows = _result([(3,)])

    assert Warning.JOIN_COUNTS_ROWS in explain(join_count, rows, CATALOGUE).warnings
    assert Warning.JOIN_COUNTS_ROWS in explain(join_count_col, rows, CATALOGUE).warnings
    assert Warning.JOIN_COUNTS_ROWS not in explain(join_distinct, rows, CATALOGUE).warnings
    assert Warning.JOIN_COUNTS_ROWS not in explain(single_view, rows, CATALOGUE).warnings


def test_group_by_alone_without_count_does_not_warn() -> None:
    query = _checked(
        "SELECT e.DEPT, c.BIRTH_DATE FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID "
        "GROUP BY e.DEPT, c.BIRTH_DATE"
    )

    result = explain(query, _result([("IT", "2010-01-01")]), CATALOGUE)

    assert result.warnings == ()
    assert result.group_by == ("e.DEPT", "c.BIRTH_DATE")


def test_truncated_result_warns() -> None:
    query = _checked("SELECT e.NAME FROM GOV_EMPLOYEES e")

    result = explain(query, _result([("A",)], truncated=True), CATALOGUE)

    assert result.warnings == (Warning.TRUNCATED,)


def test_empty_result_warns_and_says_zero_rows() -> None:
    query = _checked("SELECT e.NAME FROM GOV_EMPLOYEES e WHERE e.DEPT = 'none'")

    result = explain(query, _result([]), CATALOGUE)

    assert result.warnings == (Warning.EMPTY,)
    assert result.row_count == 0
    assert "0 rows" in as_english(result)


def test_long_decimals_in_the_raw_result_warn_money_rounded() -> None:
    query = _checked("SELECT e.NAME FROM GOV_EMPLOYEES e")

    result = explain(query, _result([(Decimal("0.30000000000000004"),)]), CATALOGUE)

    assert result.warnings == (Warning.MONEY_ROUNDED,)


def test_tidy_rounds_long_decimals() -> None:
    raw = _result([(Decimal("0.30000000000000004"),), (Decimal("1234567.89"),), (Decimal("2.005"),)])

    tidied, changed = tidy_result(raw)

    assert changed is True
    assert [str(row[0]) for row in tidied.rows] == ["0.30", "1234567.89", "2.01"]


def test_tidy_leaves_ints_strings_and_short_decimals_untouched() -> None:
    raw = _result([(7, "Aigerim", Decimal("12.50"), None)])

    tidied, changed = tidy_result(raw)

    assert changed is False
    assert tidied.rows == raw.rows


def test_tidy_does_not_mutate_the_input() -> None:
    raw = _result([(Decimal("0.30000000000000004"),)])

    tidied, _ = tidy_result(raw)

    assert raw.rows == ((Decimal("0.30000000000000004"),),)
    assert tidied is not raw
    assert tidied.columns == raw.columns
    assert tidied.truncated == raw.truncated


def test_as_english_mentions_each_warning() -> None:
    query = _checked(
        "SELECT COUNT(*) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID"
    )
    explanation = Explanation(
        views=("GOV_CHILDREN", "GOV_EMPLOYEES"),
        filters=(),
        group_by=(),
        aggregates=("COUNT(*)",),
        row_count=1,
        warnings=(
            Warning.JOIN_COUNTS_ROWS,
            Warning.TRUNCATED,
            Warning.EMPTY,
            Warning.MONEY_ROUNDED,
        ),
        sql=query.sql,
    )

    text = as_english(explanation)

    assert "rows, not people" in text
    assert "row limit" in text
    assert "No rows matched" in text
    assert "rounded" in text
    assert "GOV_EMPLOYEES" in text
    assert "COUNT(*)" in text


def test_explanation_sql_has_no_comments() -> None:
    query = _checked("SELECT e.NAME FROM GOV_EMPLOYEES e -- secret note\n /* hidden */ WHERE e.DEPT = 'IT'")

    result = explain(query, _result([("A",)]), CATALOGUE)

    assert "--" not in result.sql
    assert "/*" not in result.sql
    assert "secret" not in result.sql
    assert result.sql == query.sql


SALARY = View(
    name="GOV_SALARY",
    description="Salary records",
    columns=(
        Column("EMP_ID", "employee id"),
        Column("BASE_SALARY", "base salary"),
        Column("END_DATE", "end"),
    ),
)
LOANS = View(
    name="GOV_LOANS",
    description="Loans",
    columns=(
        Column("EMP_ID", "employee id"),
        Column("AMOUNT", "amount"),
        Column("END_DATE", "end"),
    ),
)
MONEY_CATALOGUE = Catalogue(views=(EMPLOYEES, CHILDREN, SALARY, LOANS))


def _money_warnings(sql: str) -> tuple[Warning, ...]:
    query = check_sql(sql, MONEY_CATALOGUE)
    return explain(query, _result([(1,)]), MONEY_CATALOGUE).warnings


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(e.EMP_ID) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID",
        "SELECT AVG(e.EMP_ID) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID",
        "SELECT COUNT(DISTINCT e.EMP_ID), SUM(e.EMP_ID) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c "
        "ON c.EMP_ID = e.EMP_ID",
    ],
)
def test_sum_or_avg_over_a_join_warns_rows_not_people(sql: str) -> None:
    assert Warning.JOIN_COUNTS_ROWS in _money_warnings(sql)


def test_sum_without_a_join_on_an_ordinary_view_does_not_warn() -> None:
    assert _money_warnings("SELECT SUM(EMP_ID) FROM GOV_CHILDREN") == ()


def test_count_distinct_over_a_join_without_sum_or_avg_does_not_warn() -> None:
    sql = "SELECT COUNT(DISTINCT e.EMP_ID) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID"
    assert Warning.JOIN_COUNTS_ROWS not in _money_warnings(sql)


def test_sum_over_salary_without_an_end_date_filter_warns() -> None:
    assert Warning.JOIN_COUNTS_ROWS in _money_warnings("SELECT SUM(BASE_SALARY) FROM GOV_SALARY")


def test_sum_over_salary_with_an_end_date_filter_does_not_warn() -> None:
    assert _money_warnings("SELECT SUM(BASE_SALARY) FROM GOV_SALARY WHERE END_DATE IS NULL") == ()


def test_avg_over_loans_through_an_alias_without_an_end_date_filter_warns() -> None:
    assert Warning.JOIN_COUNTS_ROWS in _money_warnings("SELECT AVG(l.AMOUNT) FROM GOV_LOANS l")


def test_count_over_salary_without_a_filter_does_not_warn() -> None:
    assert _money_warnings("SELECT COUNT(*) FROM GOV_SALARY") == ()


def test_join_warning_sentence_reads_for_sums_too() -> None:
    explanation = Explanation(
        views=("GOV_EMPLOYEES", "GOV_CHILDREN"),
        filters=(),
        group_by=(),
        aggregates=("SUM(e.EMP_ID)",),
        row_count=1,
        warnings=(Warning.JOIN_COUNTS_ROWS,),
        sql="SELECT SUM(e.EMP_ID) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID",
    )

    text = as_english(explanation)

    assert "The count goes over" not in text
    assert "The figures" in text
    assert "rows, not people" in text


@pytest.mark.parametrize("warning", list(Warning))
def test_every_warning_has_an_english_sentence(warning: Warning) -> None:
    explanation = Explanation(
        views=("GOV_EMPLOYEES",),
        filters=(),
        group_by=(),
        aggregates=(),
        row_count=0,
        warnings=(warning,),
        sql="SELECT e.NAME FROM GOV_EMPLOYEES e",
    )

    assert len(as_english(explanation)) > len("The answer uses GOV_EMPLOYEES.")
