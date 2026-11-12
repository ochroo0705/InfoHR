import pytest
import sqlglot

from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery, CheckError, check_sql
from sqlcore.firebird import Firebird

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(
        Column("ID", "employee id"),
        Column("NAME", "full name"),
        Column("DEPT", "department"),
    ),
)
CHILDREN = View(
    name="GOV_CHILDREN",
    description="Children of employees",
    columns=(
        Column("EMPLOYEE_ID", "employee id"),
        Column("BIRTH_DATE", "birth date"),
    ),
)
CATALOGUE = Catalogue(views=(EMPLOYEES, CHILDREN))


def test_join_with_count_star_and_group_by_is_accepted() -> None:
    checked = check_sql(
        "SELECT e.NAME, COUNT(*) AS CHILDREN FROM GOV_EMPLOYEES e "
        "JOIN GOV_CHILDREN c ON c.EMPLOYEE_ID = e.ID GROUP BY e.NAME",
        CATALOGUE,
    )

    assert isinstance(checked, CheckedQuery)
    assert checked.views == frozenset({"GOV_EMPLOYEES", "GOV_CHILDREN"})


def test_cte_over_one_view_is_accepted() -> None:
    checked = check_sql(
        "WITH staff AS (SELECT ID, DEPT FROM GOV_EMPLOYEES) SELECT DEPT, COUNT(*) FROM staff GROUP BY DEPT",
        CATALOGUE,
    )

    assert checked.views == frozenset({"GOV_EMPLOYEES"})


def test_cte_name_is_not_mistaken_for_a_real_table_and_its_body_is_checked() -> None:
    with pytest.raises(CheckError):
        check_sql("WITH staff AS (SELECT id FROM IHR_EMPLOYEE) SELECT id FROM staff", CATALOGUE)


def test_column_used_with_a_table_alias_is_accepted() -> None:
    checked = check_sql("SELECT e.NAME FROM GOV_EMPLOYEES e WHERE e.DEPT = 'X'", CATALOGUE)

    assert checked.views == frozenset({"GOV_EMPLOYEES"})


def test_alias_of_unknown_table_is_rejected() -> None:
    with pytest.raises(CheckError):
        check_sql("SELECT x.NAME FROM GOV_EMPLOYEES e", CATALOGUE)


def test_alias_column_must_exist_on_its_view() -> None:
    with pytest.raises(CheckError):
        check_sql("SELECT c.NAME FROM GOV_CHILDREN c", CATALOGUE)


def test_identifiers_are_matched_case_insensitively() -> None:
    checked = check_sql("select name, Dept from gov_employees", CATALOGUE)

    assert checked.views == frozenset({"GOV_EMPLOYEES"})


def test_union_of_governed_views_is_accepted() -> None:
    checked = check_sql(
        "SELECT ID FROM GOV_EMPLOYEES UNION SELECT EMPLOYEE_ID FROM GOV_CHILDREN",
        CATALOGUE,
    )

    assert checked.views == frozenset({"GOV_EMPLOYEES", "GOV_CHILDREN"})


def test_sql_is_rerendered_without_comments() -> None:
    checked = check_sql("SELECT ID /* secret note */ FROM GOV_EMPLOYEES -- trailing note", CATALOGUE)

    assert "note" not in checked.sql.lower()
    assert "GOV_EMPLOYEES" in checked.sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM GOV_EMPLOYEES",
        "SELECT t.* FROM GOV_EMPLOYEES t",
        "SELECT id FROM GOV_EMPLOYEES; DROP TABLE x",
        "SELECT id FROM GOV_EMPLOYEES; SELECT id FROM GOV_CHILDREN",
        "DELETE FROM GOV_EMPLOYEES",
        "SELECT id FROM IHR_EMPLOYEE",
        "SELECT id FROM GOV_EMPLOYEES UNION SELECT id FROM IHR_EMPLOYEE",
        "SELECT NAME FROM GOV_EMPLOYEES UNION SELECT NAME FROM IHR_EMPLOYEE",
        "SELECT salary FROM GOV_EMPLOYEES",
        "SELECT id FROM GOV_EMPLOYEES WHERE salary > 0",
        "SELECT id FROM GOV_EMPLOYEES /* ; */ DROP TABLE x",
        "SELECT id FROM GOV_EMPLOYEES /* ; */ ; DELETE FROM GOV_EMPLOYEES",
        "SELECT id FROM GOV_EMPLOYEES -- hidden\n; DROP TABLE x",
        "SELECT 'GOV_EMPLOYEES' FROM RDB$DATABASE",
        "SELECT id FROM GOV_SCOPE",
        "SELECT id FROM GOV_EMPLOYEES WHERE id IN (SELECT id FROM GOV_SCOPE)",
        "EXECUTE BLOCK AS BEGIN END",
        "SELECT GEN_ID(GEN_TEST, 1) FROM GOV_EMPLOYEES",
        "SELECT id FROM GOV_EMPLOYEES WHERE EXISTS (SELECT 1 FROM IHR_EMPLOYEE)",
        'SELECT "ID" FROM "GOV_EMPLOYEES"',
        'SELECT "ID" FROM GOV_EMPLOYEES',
        "SELECT a.ID FROM db.GOV_EMPLOYEES a",
        "SELECT id FROM GOV_EMPLOYEES INTO target_table",
        "WITH d AS (DELETE FROM GOV_EMPLOYEES RETURNING ID) SELECT ID FROM d",
        "INSERT INTO GOV_EMPLOYEES (ID) VALUES (1)",
        "UPDATE GOV_EMPLOYEES SET NAME = 'x'",
        "CREATE TABLE x (a INTEGER)",
        "COMMIT",
        "",
        "   ",
    ],
)
def test_rejected_queries_raise_check_error(sql: str) -> None:
    with pytest.raises(CheckError):
        check_sql(sql, CATALOGUE)


def test_date_functions_with_unit_words_are_accepted_and_keep_the_unit() -> None:
    checked = check_sql(
        "SELECT EXTRACT(YEAR FROM BIRTH_DATE), DATEADD(DAY, 5, BIRTH_DATE), "
        "DATEDIFF(YEAR, BIRTH_DATE, CURRENT_DATE) FROM GOV_CHILDREN",
        CATALOGUE,
    )

    assert checked.views == frozenset({"GOV_CHILDREN"})
    assert "DATEADD(DAY" in checked.sql.replace("DATEADD( DAY", "DATEADD(DAY")
    assert "YEAR" in checked.sql


def test_unit_word_outside_a_date_function_is_not_a_column() -> None:
    with pytest.raises(CheckError):
        check_sql("SELECT DAY FROM GOV_EMPLOYEES", CATALOGUE)


def test_case_and_substring_are_accepted() -> None:
    checked = check_sql(
        "SELECT CASE WHEN DEPT = 'X' THEN 1 ELSE 0 END AS F, SUBSTRING(NAME FROM 1 FOR 3) FROM GOV_EMPLOYEES",
        CATALOGUE,
    )

    assert checked.views == frozenset({"GOV_EMPLOYEES"})


def test_rejection_names_the_real_problem() -> None:
    with pytest.raises(CheckError, match="GEN_ID"):
        check_sql("SELECT GEN_ID(GEN_TEST, 1) FROM GOV_EMPLOYEES", CATALOGUE)
    with pytest.raises(CheckError, match="COUNT"):
        check_sql("SELECT t.* FROM GOV_EMPLOYEES t", CATALOGUE)


def test_boolean_operators_and_predicates_are_accepted() -> None:
    checked = check_sql(
        "SELECT ID FROM GOV_EMPLOYEES WHERE ID IN (1, 2) AND NAME LIKE 'A%' OR DEPT IS NOT NULL",
        CATALOGUE,
    )

    assert checked.views == frozenset({"GOV_EMPLOYEES"})


def _rendered(sql: str) -> str:
    return check_sql(sql, CATALOGUE).sql


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("SELECT FIRST 5 ID FROM GOV_EMPLOYEES", "SELECT FIRST 5 ID FROM GOV_EMPLOYEES"),
        (
            "SELECT FIRST 5 SKIP 2 ID FROM GOV_EMPLOYEES ORDER BY ID",
            "SELECT FIRST 5 SKIP 2 ID FROM GOV_EMPLOYEES ORDER BY ID",
        ),
        ("SELECT FIRST 5 DISTINCT DEPT FROM GOV_EMPLOYEES", "SELECT FIRST 5 DISTINCT DEPT FROM GOV_EMPLOYEES"),
        ("SELECT ID FROM GOV_EMPLOYEES ORDER BY ID ROWS 5", "SELECT FIRST 5 ID FROM GOV_EMPLOYEES ORDER BY ID"),
        (
            "SELECT ID FROM GOV_EMPLOYEES ORDER BY ID ROWS 2 TO 5",
            "SELECT FIRST 4 SKIP 1 ID FROM GOV_EMPLOYEES ORDER BY ID",
        ),
        (
            "SELECT ID FROM GOV_EMPLOYEES ORDER BY ID FETCH FIRST 5 ROWS ONLY",
            "SELECT FIRST 5 ID FROM GOV_EMPLOYEES ORDER BY ID",
        ),
        (
            "SELECT ID FROM GOV_EMPLOYEES ORDER BY ID OFFSET 2 ROWS FETCH NEXT 3 ROWS ONLY",
            "SELECT FIRST 3 SKIP 2 ID FROM GOV_EMPLOYEES ORDER BY ID",
        ),
    ],
)
def test_firebird_row_limits_are_accepted_and_rendered_as_first_and_skip(source: str, expected: str) -> None:
    rendered = _rendered(source)

    assert rendered == expected
    assert "FETCH" not in rendered
    assert "OFFSET" not in rendered
    assert "LIMIT" not in rendered


def test_fetch_and_offset_inputs_never_render_as_fetch_or_offset_keywords() -> None:
    rendered = _rendered("SELECT ID FROM GOV_EMPLOYEES ORDER BY ID OFFSET 2 ROWS")

    assert rendered == "SELECT SKIP 2 ID FROM GOV_EMPLOYEES ORDER BY ID"


def test_substring_renders_in_firebird_from_for_form() -> None:
    assert _rendered("SELECT SUBSTRING(NAME, 1, 3) FROM GOV_EMPLOYEES") == (
        "SELECT SUBSTRING(NAME FROM 1 FOR 3) FROM GOV_EMPLOYEES"
    )


def test_length_renders_as_char_length_in_both_spellings() -> None:
    assert _rendered("SELECT LENGTH(NAME), CHAR_LENGTH(NAME) FROM GOV_EMPLOYEES") == (
        "SELECT CHAR_LENGTH(NAME), CHAR_LENGTH(NAME) FROM GOV_EMPLOYEES"
    )


def test_dateadd_and_datediff_keep_firebird_argument_order_with_unquoted_unit() -> None:
    rendered = _rendered(
        "SELECT DATEADD(DAY, 5, BIRTH_DATE), DATEDIFF(YEAR, BIRTH_DATE, CURRENT_DATE) FROM GOV_CHILDREN"
    )

    assert rendered == (
        "SELECT DATEADD(DAY, 5, BIRTH_DATE), DATEDIFF(YEAR, BIRTH_DATE, CAST('TODAY' AS TIMESTAMP)) FROM GOV_CHILDREN"
    )


def test_coalesce_and_cast_render_unchanged() -> None:
    assert _rendered("SELECT COALESCE(NAME, 'x'), CAST(ID AS VARCHAR(10)) FROM GOV_EMPLOYEES") == (
        "SELECT COALESCE(NAME, 'x'), CAST(ID AS VARCHAR(10)) FROM GOV_EMPLOYEES"
    )


def test_current_date_is_accepted_and_renders_as_today_at_midnight() -> None:
    rendered = _rendered("SELECT EXTRACT(YEAR FROM CURRENT_DATE) FROM GOV_EMPLOYEES")

    assert rendered == "SELECT EXTRACT(YEAR FROM CAST('TODAY' AS TIMESTAMP)) FROM GOV_EMPLOYEES"
    assert "CURRENT_DATE" not in rendered


def test_current_date_in_datediff_renders_as_today_at_midnight() -> None:
    rendered = _rendered("SELECT DATEDIFF(YEAR, BIRTH_DATE, CURRENT_DATE) FROM GOV_CHILDREN")

    assert rendered == "SELECT DATEDIFF(YEAR, BIRTH_DATE, CAST('TODAY' AS TIMESTAMP)) FROM GOV_CHILDREN"
    assert "CURRENT_DATE" not in rendered


def test_current_date_inside_where_renders_as_today_at_midnight() -> None:
    checked = check_sql("SELECT NAME FROM GOV_EMPLOYEES WHERE DEPT < CURRENT_DATE", CATALOGUE)

    assert checked.sql == "SELECT NAME FROM GOV_EMPLOYEES WHERE DEPT < CAST('TODAY' AS TIMESTAMP)"
    assert "CURRENT_DATE" not in checked.sql


def test_current_date_inside_a_cte_renders_as_today_at_midnight() -> None:
    checked = check_sql(
        "WITH recent AS (SELECT BIRTH_DATE, CURRENT_DATE AS TODAY FROM GOV_CHILDREN) SELECT TODAY FROM recent",
        CATALOGUE,
    )

    assert checked.sql == (
        "WITH recent AS (SELECT BIRTH_DATE, CAST('TODAY' AS TIMESTAMP) AS TODAY FROM GOV_CHILDREN) "
        "SELECT TODAY FROM recent"
    )
    assert "CURRENT_DATE" not in checked.sql


def test_current_date_inside_a_subquery_renders_as_today_at_midnight() -> None:
    checked = check_sql(
        "SELECT NAME FROM GOV_EMPLOYEES WHERE BIRTH_DATE < (SELECT CURRENT_DATE FROM GOV_CHILDREN)",
        CATALOGUE,
    )

    assert checked.sql == (
        "SELECT NAME FROM GOV_EMPLOYEES WHERE BIRTH_DATE < (SELECT CAST('TODAY' AS TIMESTAMP) FROM GOV_CHILDREN)"
    )
    assert "CURRENT_DATE" not in checked.sql


def test_current_timestamp_is_left_alone() -> None:
    # The checker still refuses CURRENT_TIMESTAMP typed by the model (check.py ALLOWED_KEYWORDS), so this pins the
    # renderer alone: a real timestamp stays CURRENT_TIMESTAMP, bare, and is never turned into midnight.
    tree = sqlglot.parse_one("SELECT NAME FROM GOV_EMPLOYEES WHERE DEPT < CURRENT_TIMESTAMP", read=Firebird)
    rendered = tree.sql(dialect=Firebird, comments=False)

    assert rendered == "SELECT NAME FROM GOV_EMPLOYEES WHERE DEPT < CURRENT_TIMESTAMP"
    assert "TODAY" not in rendered


def test_first_inside_a_cte_renders_after_select() -> None:
    assert _rendered("WITH staff AS (SELECT FIRST 3 ID, DEPT FROM GOV_EMPLOYEES) SELECT DEPT FROM staff") == (
        "WITH staff AS (SELECT FIRST 3 ID, DEPT FROM GOV_EMPLOYEES) SELECT DEPT FROM staff"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT FIRST 5 ID FROM GOV_EMPLOYEES; DROP TABLE x",
        "SELECT FIRST (SELECT 1) ID FROM GOV_EMPLOYEES",
        "SELECT FIRST x ID FROM GOV_EMPLOYEES",
        "SELECT FIRST 5 SKIP x ID FROM GOV_EMPLOYEES",
        "SELECT ID FROM GOV_EMPLOYEES ORDER BY ID ROWS x",
    ],
)
def test_firebird_row_limit_with_non_integer_or_second_statement_is_rejected(sql: str) -> None:
    with pytest.raises(CheckError):
        check_sql(sql, CATALOGUE)


def test_limit_on_a_union_is_rejected_because_firebird_cannot_render_it() -> None:
    with pytest.raises(CheckError):
        check_sql("SELECT ID FROM GOV_EMPLOYEES UNION SELECT EMPLOYEE_ID FROM GOV_CHILDREN ROWS 3", CATALOGUE)


# Finding 1: a CTE name must never hide a base table, and a CTE is visible only where it is defined earlier.
# CATALOGUE above has no GOV_SALARY, so every form below must be refused.
CTE_NAME_TRICKS = [
    # (a) the body reads GOV_SALARY before a CTE of that name is defined
    "WITH a AS (SELECT GOV_SALARY.BASE_SALARY AS AMT FROM GOV_SALARY), "
    "GOV_SALARY AS (SELECT e.ID AS X FROM GOV_EMPLOYEES e) SELECT AMT FROM a",
    # (b) a CTE named GOV_SALARY reads GOV_SALARY itself
    "WITH GOV_SALARY AS (SELECT GOV_SALARY.AMOUNT AS AMOUNT FROM GOV_SALARY) SELECT AMOUNT FROM GOV_SALARY",
    # (c) a CTE named after a real table reads that table
    "WITH IHR_EMPLOYEE AS (SELECT IHR_EMPLOYEE.ID AS ID FROM IHR_EMPLOYEE) SELECT ID FROM IHR_EMPLOYEE",
    # (d) the same trick in a nested WITH inside a subquery
    "SELECT e.ID FROM GOV_EMPLOYEES e WHERE e.ID IN "
    "(WITH IHR_EMPLOYEE AS (SELECT IHR_EMPLOYEE.ID AS ID FROM IHR_EMPLOYEE) SELECT ID FROM IHR_EMPLOYEE)",
]


@pytest.mark.parametrize("sql", CTE_NAME_TRICKS, ids=["form_a", "form_b", "form_c", "form_d"])
def test_cte_named_like_a_real_table_is_refused(sql: str) -> None:
    with pytest.raises(CheckError):
        check_sql(sql, CATALOGUE)


def test_cte_named_like_a_catalogue_view_is_refused_even_when_the_view_is_allowed() -> None:
    with pytest.raises(CheckError, match="reserved"):
        check_sql("WITH GOV_EMPLOYEES AS (SELECT ID FROM GOV_CHILDREN) SELECT ID FROM GOV_EMPLOYEES", CATALOGUE)


@pytest.mark.parametrize(
    "sql",
    [
        "WITH GOV_X AS (SELECT ID FROM GOV_EMPLOYEES) SELECT ID FROM GOV_X",
        "WITH IHR_X AS (SELECT ID FROM GOV_EMPLOYEES) SELECT ID FROM IHR_X",
        "WITH RDB$X AS (SELECT ID FROM GOV_EMPLOYEES) SELECT ID FROM RDB$X",
        "WITH MON$X AS (SELECT ID FROM GOV_EMPLOYEES) SELECT ID FROM MON$X",
        "WITH SEC$X AS (SELECT ID FROM GOV_EMPLOYEES) SELECT ID FROM SEC$X",
    ],
)
def test_cte_with_a_reserved_prefix_is_refused(sql: str) -> None:
    with pytest.raises(CheckError, match="reserved"):
        check_sql(sql, CATALOGUE)


def test_chained_cte_in_definition_order_is_accepted() -> None:
    checked = check_sql(
        "WITH a AS (SELECT ID, DEPT FROM GOV_EMPLOYEES), b AS (SELECT DEPT FROM a) SELECT DEPT, COUNT(*) FROM b "
        "GROUP BY DEPT",
        CATALOGUE,
    )

    assert checked.views == frozenset({"GOV_EMPLOYEES"})


def test_cte_referenced_only_from_the_main_query_is_accepted() -> None:
    checked = check_sql("WITH staff AS (SELECT ID FROM GOV_EMPLOYEES) SELECT ID FROM staff", CATALOGUE)

    assert checked.views == frozenset({"GOV_EMPLOYEES"})


def test_cte_used_before_its_definition_is_refused() -> None:
    with pytest.raises(CheckError):
        check_sql(
            "WITH a AS (SELECT ID FROM staff_b), staff_b AS (SELECT ID FROM GOV_EMPLOYEES) SELECT ID FROM a",
            CATALOGUE,
        )


def test_cte_that_refers_to_itself_is_refused() -> None:
    with pytest.raises(CheckError):
        check_sql("WITH a AS (SELECT ID FROM a) SELECT ID FROM a", CATALOGUE)


def test_duplicate_cte_names_in_one_query_are_refused() -> None:
    with pytest.raises(CheckError, match="defined twice"):
        check_sql(
            "WITH a AS (SELECT ID FROM GOV_EMPLOYEES), a AS (SELECT ID FROM GOV_CHILDREN) SELECT ID FROM a",
            CATALOGUE,
        )


def test_with_recursive_is_refused() -> None:
    with pytest.raises(CheckError, match="RECURSIVE"):
        check_sql(
            "WITH RECURSIVE r AS (SELECT ID FROM GOV_EMPLOYEES UNION ALL SELECT ID FROM r) SELECT ID FROM r",
            CATALOGUE,
        )
