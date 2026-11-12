"""Adversarial SQL for the checker (Task 14a). No database: every case is checked against the catalogue of all six
governed views, with the column names of hr_sql/views.py (tests/test_scope.py checks those names against Firebird).

Every hostile string must raise CheckError. Every legitimate string must pass. A hostile string that is not refused
is a security finding: do not weaken the list, report it.
"""

import pytest

from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery, CheckError, check_sql

SIX_VIEWS = Catalogue(
    views=(
        View(
            name="GOV_EMPLOYEES",
            description="Employees you may see",
            columns=(
                Column("EMP_ID", "employee id"),
                Column("FIRST_NAME", "first name"),
                Column("LAST_NAME", "last name"),
                Column("DEPARTMENT_NAME", "department"),
                Column("BRANCH_NAME", "branch"),
                Column("POSITION_NAME", "position"),
                Column("HIRE_DATE", "hire date"),
                Column("BIRTH_DATE", "birth date"),
                Column("GENDER", "gender"),
                Column("WORKING", "working now"),
            ),
        ),
        View(
            name="GOV_CHILDREN",
            description="Children of employees",
            columns=(
                Column("CHILD_ID", "child id"),
                Column("EMP_ID", "employee id"),
                Column("BIRTH_DATE", "birth date"),
                Column("GENDER", "gender"),
            ),
        ),
        View(
            name="GOV_LEAVE",
            description="Leave",
            columns=(
                Column("LEAVE_ID", "leave id"),
                Column("EMP_ID", "employee id"),
                Column("LEAVE_TYPE_NAME", "leave type"),
                Column("START_DATE", "start"),
                Column("END_DATE", "end"),
                Column("DAYS", "days"),
                Column("STATUS_NAME", "status"),
            ),
        ),
        View(
            name="GOV_ORDERS",
            description="Orders",
            columns=(
                Column("ORDER_ID", "order id"),
                Column("EMP_ID", "employee id"),
                Column("ORDER_TYPE_NAME", "order type"),
                Column("STATE_NAME", "state"),
                Column("ORDER_NUMBER", "order number"),
                Column("ORDER_DATE", "order date"),
                Column("SUMMARY", "summary"),
            ),
        ),
        View(
            name="GOV_SALARY",
            description="Salary records",
            columns=(
                Column("SALARY_ID", "salary id"),
                Column("EMP_ID", "employee id"),
                Column("START_DATE", "start"),
                Column("END_DATE", "end"),
                Column("BASE_SALARY", "base salary"),
                Column("CHANGE_TYPE", "change type"),
            ),
        ),
        View(
            name="GOV_LOANS",
            description="Loans",
            columns=(
                Column("LOAN_ID", "loan id"),
                Column("EMP_ID", "employee id"),
                Column("LOAN_DATE", "loan date"),
                Column("END_DATE", "end"),
                Column("AMOUNT", "amount"),
                Column("MONTHLY_PAYMENT", "monthly payment"),
                Column("REASON", "reason"),
            ),
        ),
    )
)

HOSTILE: list[str] = [
    # stacked statements, with and without comments hiding the separator
    "SELECT EMP_ID FROM GOV_EMPLOYEES; DROP TABLE GOV_SCOPE",
    "SELECT EMP_ID FROM GOV_EMPLOYEES; SELECT EMP_ID FROM GOV_SALARY",
    "SELECT EMP_ID FROM GOV_EMPLOYEES /* ; */ ; DELETE FROM GOV_SCOPE",
    "SELECT EMP_ID FROM GOV_EMPLOYEES -- x\n; UPDATE GOV_SCOPE SET WORKING = 1",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE FIRST_NAME = '' OR 1 = 1; DROP TABLE x",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE 'a' = '/*' ; DROP VIEW GOV_EMPLOYEES",
    "SELECT EMP_ID FROM GOV_EMPLOYEES; COMMIT",
    "SET TRANSACTION READ WRITE",
    # a comment hiding a UNION into a real table or a system table
    "SELECT EMP_ID FROM GOV_EMPLOYEES -- hidden\nUNION SELECT EMP_ID FROM IHR_EMPLOYEE",
    "SELECT EMP_ID FROM GOV_EMPLOYEES /* a */ UNION /* b */ SELECT EMP_ID FROM IHR_EMPLOYEE",
    "SELECT FIRST_NAME FROM GOV_EMPLOYEES /* GOV_SCOPE */ UNION SELECT RDB$RELATION_NAME FROM RDB$RELATIONS",
    # a string literal that names a view or a system table, used as a table
    "SELECT 'GOV_EMPLOYEES' FROM RDB$DATABASE",
    "SELECT EMP_ID FROM 'GOV_EMPLOYEES'",
    # real tables, system tables, scope table, qualified names
    "SELECT EMP_ID FROM IHR_EMPLOYEE",
    "SELECT FIRST_NAME FROM RDB$RELATIONS",
    "SELECT RDB$RELATION_NAME FROM RDB$RELATIONS",
    "SELECT EMP_ID FROM GOV_EMPLOYEES UNION SELECT RDB$RELATION_ID FROM RDB$RELATIONS",
    "SELECT 1 FROM RDB$DATABASE",
    "SELECT EMP_ID FROM GOV_SCOPE",
    "SELECT s.EMP_ID FROM GOV_SCOPE s",
    "SELECT GOV_SCOPE.EMP_ID FROM GOV_EMPLOYEES",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE EMP_ID IN (SELECT EMP_ID FROM GOV_SCOPE)",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE EXISTS (SELECT 1 FROM GOV_SCOPE)",
    "WITH s AS (SELECT EMP_ID FROM GOV_SCOPE) SELECT EMP_ID FROM s",
    "SELECT EMP_ID FROM GOV_EMPLOYEES e JOIN GOV_SCOPE s ON s.EMP_ID = e.EMP_ID",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE EMP_ID IN (SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS)",
    "SELECT EMP_ID FROM GOV_EMPLOYEES JOIN RDB$DATABASE ON 1 = 1",
    "SELECT EMP_ID FROM RDB$DATABASE GOV_EMPLOYEES",
    "SELECT EMP_ID FROM GOV_EMPLOYEES a, IHR_EMPLOYEE b",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE EMP_ID = (SELECT MAX(EMP_ID) FROM IHR_EMPLOYEE)",
    "SELECT EMP_ID, (SELECT COUNT(*) FROM RDB$DATABASE) FROM GOV_EMPLOYEES",
    'SELECT EMP_ID FROM "IHR_EMPLOYEE"',
    'SELECT "EMP_ID" FROM GOV_EMPLOYEES',
    # CTE that selects from a real table or the scope table
    "WITH t AS (SELECT EMP_ID FROM IHR_EMPLOYEE) SELECT EMP_ID FROM t",
    "WITH t AS (SELECT EMP_ID FROM GOV_EMPLOYEES) SELECT EMP_ID FROM IHR_EMPLOYEE",
    # set operations into real tables, nested
    "SELECT EMP_ID FROM GOV_EMPLOYEES UNION ALL SELECT EMP_ID FROM IHR_EMPLOYEE",
    "SELECT EMP_ID FROM GOV_EMPLOYEES INTERSECT SELECT EMP_ID FROM IHR_EMPLOYEE",
    "SELECT EMP_ID FROM GOV_EMPLOYEES EXCEPT (SELECT EMP_ID FROM GOV_SCOPE)",
    "(SELECT EMP_ID FROM GOV_EMPLOYEES UNION SELECT EMP_ID FROM GOV_CHILDREN) UNION (SELECT EMP_ID FROM IHR_EMPLOYEE)",
    # execute block, execute statement, generators, sequences, context and session functions
    "EXECUTE BLOCK AS BEGIN END",
    "EXECUTE BLOCK RETURNS (X INTEGER) AS BEGIN X = 1; SUSPEND; END",
    "EXECUTE STATEMENT 'SELECT * FROM GOV_SCOPE'",
    "SELECT GEN_ID(GEN_TEST, 1) FROM GOV_EMPLOYEES",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE EMP_ID = GEN_ID(GEN_EMP, 0)",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE EMP_ID = (SELECT GEN_ID(X, 0) FROM RDB$DATABASE)",
    "SELECT NEXT VALUE FOR SEQ_EMP FROM GOV_EMPLOYEES",
    "SELECT RDB$GET_CONTEXT('SYSTEM', 'DB_NAME') FROM RDB$DATABASE",
    "SELECT RDB$GET_CONTEXT('USER_SESSION', 'X') FROM GOV_EMPLOYEES",
    "SELECT CURRENT_USER FROM GOV_EMPLOYEES",
    "SELECT USER FROM GOV_EMPLOYEES",
    "SELECT CURRENT_ROLE FROM GOV_EMPLOYEES",
    "SELECT CURRENT_CONNECTION FROM GOV_EMPLOYEES",
    "SELECT CURRENT_TRANSACTION FROM GOV_EMPLOYEES",
    # writes, DDL and grants
    "SELECT EMP_ID INTO target_table FROM GOV_EMPLOYEES",
    "SELECT EMP_ID FROM GOV_EMPLOYEES INTO :x",
    "INSERT INTO GOV_SCOPE (EMP_ID, WORKING) VALUES (1, 1)",
    "UPDATE GOV_SCOPE SET WORKING = 1",
    "DELETE FROM GOV_SCOPE",
    "MERGE INTO GOV_SCOPE USING GOV_EMPLOYEES ON 1 = 1 WHEN MATCHED THEN DELETE",
    "DROP VIEW GOV_EMPLOYEES",
    "ALTER VIEW GOV_EMPLOYEES AS SELECT 1 FROM RDB$DATABASE",
    "CREATE VIEW GOV_X AS SELECT * FROM IHR_EMPLOYEE",
    "GRANT SELECT ON IHR_EMPLOYEE TO PUBLIC",
    # a look-alike Cyrillic letter in a view name, and in a column name (not Latin, so not the same name)
    "SELECT EMP_ID FROM GOV_ЕMPLOYEES",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE FIRST_NАME IS NULL",
    # row limits used to smuggle a subquery, or a second statement
    "SELECT FIRST (SELECT COUNT(*) FROM GOV_SCOPE) EMP_ID FROM GOV_EMPLOYEES",
    "SELECT FIRST 1 EMP_ID FROM GOV_EMPLOYEES ROWS (SELECT 1 FROM RDB$DATABASE)",
    # bytes that a C-string based driver would cut at
    "SELECT EMP_ID FROM GOV_EMPLOYEES\x00; DROP TABLE GOV_SCOPE",
    "SELECT EMP_ID FROM GOV_EMPLOYEES\x00",
    # locking and row-level syntax on a view
    "SELECT EMP_ID FROM GOV_EMPLOYEES FOR UPDATE",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WITH LOCK",
    # an identifier far longer than Firebird's 31 characters, and a column that exists on no view
    "SELECT " + "A" * 300 + " FROM GOV_EMPLOYEES",
    "SELECT EMP_ID FROM GOV_EMPLOYEES WHERE EMP_ID = 1 OR (SELECT 1 FROM GOV_SCOPE) = 1",
]

LEGITIMATE: list[str] = [
    "SELECT COUNT(*) FROM GOV_EMPLOYEES",
    "SELECT DEPARTMENT_NAME, COUNT(*) FROM GOV_EMPLOYEES GROUP BY DEPARTMENT_NAME",
    "SELECT e.FIRST_NAME, COUNT(c.CHILD_ID) AS CHILDREN FROM GOV_EMPLOYEES e "
    "JOIN GOV_CHILDREN c ON c.EMP_ID = e.EMP_ID GROUP BY e.FIRST_NAME",
    "SELECT FIRST 10 FIRST_NAME FROM GOV_EMPLOYEES ORDER BY FIRST_NAME",
    "SELECT EMP_ID FROM GOV_LEAVE WHERE STATUS_NAME = 'approved' AND DAYS > 2",
    "SELECT ORDER_TYPE_NAME, COUNT(*) FROM GOV_ORDERS WHERE ORDER_DATE >= DATEADD(YEAR, -1, CURRENT_DATE) "
    "GROUP BY ORDER_TYPE_NAME",
    "SELECT SUM(BASE_SALARY) FROM GOV_SALARY",
    "SELECT LOAN_ID, REASON FROM GOV_LOANS WHERE AMOUNT > 100000",
    "SELECT EMP_ID FROM GOV_EMPLOYEES UNION SELECT EMP_ID FROM GOV_CHILDREN",
    "WITH staff AS (SELECT EMP_ID, GENDER FROM GOV_EMPLOYEES) SELECT GENDER, COUNT(*) FROM staff GROUP BY GENDER",
    "SELECT EXTRACT(YEAR FROM HIRE_DATE), COUNT(*) FROM GOV_EMPLOYEES GROUP BY EXTRACT(YEAR FROM HIRE_DATE)",
    "SELECT BRANCH_NAME, AVG(DAYS) FROM GOV_LEAVE l JOIN GOV_EMPLOYEES e ON e.EMP_ID = l.EMP_ID GROUP BY BRANCH_NAME",
    "SELECT CASE WHEN WORKING = 1 THEN 'yes' ELSE 'no' END FROM GOV_EMPLOYEES",
    "SELECT FIRST_NAME FROM GOV_EMPLOYEES WHERE BIRTH_DATE < CURRENT_DATE",
    "SELECT SUBSTRING(LAST_NAME FROM 1 FOR 1), COUNT(*) FROM GOV_EMPLOYEES "
    "GROUP BY SUBSTRING(LAST_NAME FROM 1 FOR 1)",
    "SELECT EMP_ID FROM GOV_EMPLOYEES ORDER BY EMP_ID ROWS 5",
    "SELECT COUNT(*) AS N FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM GOV_EMPLOYEES e WHERE e.EMP_ID = o.EMP_ID)",
    "SELECT STATE_NAME, COUNT(*) FROM GOV_ORDERS GROUP BY STATE_NAME HAVING COUNT(*) > 1",
    "SELECT LOWER(LAST_NAME), UPPER(FIRST_NAME), TRIM(GENDER) FROM GOV_EMPLOYEES",
    "SELECT ROUND(AVG(AMOUNT), 2), MIN(LOAN_DATE), MAX(END_DATE) FROM GOV_LOANS",
    "SELECT CHILD_ID FROM GOV_CHILDREN WHERE CHILD_ID IN (1, 2, 3)",
    "SELECT DISTINCT STATUS_NAME FROM GOV_LEAVE",
    "SELECT e.EMP_ID FROM GOV_EMPLOYEES e WHERE NOT EXISTS (SELECT 1 FROM GOV_LEAVE l WHERE l.EMP_ID = e.EMP_ID)",
    "SELECT COUNT(*) FROM GOV_EMPLOYEES e WHERE EXISTS (SELECT 1 FROM GOV_CHILDREN c WHERE c.EMP_ID = e.EMP_ID)",
    "SELECT COUNT(*) FROM GOV_EMPLOYEES WHERE EXISTS "
    "(SELECT 1 FROM GOV_LEAVE WHERE GOV_LEAVE.EMP_ID = GOV_EMPLOYEES.EMP_ID)",
    "SELECT e.EMP_ID FROM GOV_EMPLOYEES e WHERE EXISTS (SELECT 1 FROM GOV_LEAVE l WHERE l.EMP_ID = e.EMP_ID "
    "AND NOT EXISTS (SELECT 1 FROM GOV_SALARY s WHERE s.EMP_ID = l.EMP_ID))",
]

# EXISTS and NOT EXISTS subqueries. Each must raise CheckError (the walk reaches every table and column inside them).
EXISTS_HOSTILE: list[str] = [
    # real table, scope table, and a real table nested in a second EXISTS
    "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM IHR_EMPLOYEE e WHERE e.EMP_ID = o.EMP_ID)",
    "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = o.EMP_ID)",
    "SELECT e.EMP_ID FROM GOV_EMPLOYEES e WHERE NOT EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = e.EMP_ID)",
    "SELECT e.EMP_ID FROM GOV_EMPLOYEES e WHERE EXISTS (SELECT 1 FROM GOV_LEAVE l WHERE l.EMP_ID = e.EMP_ID "
    "AND EXISTS (SELECT 1 FROM IHR_EMPLOYEE i WHERE i.EMP_ID = l.EMP_ID))",
    # correlated reference to a column that is on no view
    "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM GOV_EMPLOYEES e WHERE e.EMP_ID = o.NOPE)",
    "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM GOV_LEAVE l WHERE NOPE = 1)",
    # a stacked statement, and a DML or locking keyword inside the subquery
    "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM GOV_LEAVE l WHERE l.EMP_ID = o.EMP_ID); "
    "DROP TABLE GOV_SCOPE",
    "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM GOV_LEAVE l WHERE l.EMP_ID = o.EMP_ID; "
    "DELETE FROM GOV_SCOPE)",
    "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (DELETE FROM GOV_LEAVE)",
    "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (INSERT INTO GOV_LEAVE (EMP_ID) VALUES (1))",
    "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM GOV_LEAVE l WHERE l.EMP_ID = o.EMP_ID FOR UPDATE)",
    "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM GOV_LEAVE l INTO target_table)",
    # EXISTS inside a CTE over a real table
    "WITH t AS (SELECT o.EMP_ID FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM IHR_EMPLOYEE e "
    "WHERE e.EMP_ID = o.EMP_ID)) SELECT EMP_ID FROM t",
]


def test_exists_over_a_view_missing_from_the_catalogue_is_refused() -> None:
    # GOV_SALARY is a real governed view name, but this user's catalogue does not contain it.
    without_salary = SIX_VIEWS.restrict(
        [view.name for view in SIX_VIEWS.views if view.name != "GOV_SALARY"]
    )

    with pytest.raises(CheckError):
        check_sql(
            "SELECT o.ORDER_ID FROM GOV_ORDERS o WHERE EXISTS (SELECT 1 FROM GOV_SALARY s WHERE s.EMP_ID = o.EMP_ID)",
            without_salary,
        )


@pytest.mark.parametrize("sql", EXISTS_HOSTILE)
def test_exists_hostile_sql_is_refused(sql: str) -> None:
    with pytest.raises(CheckError):
        check_sql(sql, SIX_VIEWS)


def test_not_exists_renders_as_firebird_3_text() -> None:
    checked = check_sql(
        "SELECT e.EMP_ID FROM GOV_EMPLOYEES e WHERE NOT EXISTS (SELECT 1 FROM GOV_LEAVE l WHERE l.EMP_ID = e.EMP_ID)",
        SIX_VIEWS,
    )

    assert checked.sql == (
        "SELECT e.EMP_ID FROM GOV_EMPLOYEES AS e "
        "WHERE NOT EXISTS(SELECT 1 FROM GOV_LEAVE AS l WHERE l.EMP_ID = e.EMP_ID)"
    )
    assert checked.views == frozenset({"GOV_EMPLOYEES", "GOV_LEAVE"})


@pytest.mark.parametrize("sql", HOSTILE)
def test_hostile_sql_is_refused(sql: str) -> None:
    with pytest.raises(CheckError):
        check_sql(sql, SIX_VIEWS)


def test_locking_read_for_update_is_refused_not_silently_dropped() -> None:
    # Found by the adversarial list: the checker used to accept FOR UPDATE and render a plain SELECT.
    with pytest.raises(CheckError, match="Locking reads"):
        check_sql("SELECT EMP_ID FROM GOV_EMPLOYEES FOR UPDATE", SIX_VIEWS)
    with pytest.raises(CheckError, match="Locking reads"):
        check_sql("SELECT EMP_ID FROM GOV_EMPLOYEES UNION SELECT EMP_ID FROM GOV_CHILDREN FOR UPDATE", SIX_VIEWS)


@pytest.mark.parametrize("sql", LEGITIMATE)
def test_legitimate_sql_passes(sql: str) -> None:
    checked = check_sql(sql, SIX_VIEWS)

    assert isinstance(checked, CheckedQuery)
    assert checked.views <= SIX_VIEWS.view_names()


def test_hostile_list_has_at_least_40_cases() -> None:
    assert len(HOSTILE) >= 40


def test_legitimate_list_has_at_least_15_cases() -> None:
    assert len(LEGITIMATE) >= 15
