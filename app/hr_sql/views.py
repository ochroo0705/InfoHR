"""The governed objects in the Firebird database: the scope table GOV_SCOPE and the views GOV_EMPLOYEES,
GOV_CHILDREN, GOV_LEAVE, GOV_ORDERS, GOV_SALARY and GOV_LOANS.

Table and column names come from the models (db_table, db_column) when install runs, so a renamed column is seen
here, not as a silent break. Firebird dialect 1: unquoted upper-case names, 31 characters at most, no schemas.

No access rule is written in SQL. The host fills GOV_SCOPE with the ids the asker may see (employees/access.py). A
view shows only employees whose id is in GOV_SCOPE, so an empty scope gives zero rows.
"""

import re
from collections.abc import Mapping
from typing import Any

from django.db import transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Field, Model
from employees.models import HrOrder, OrderType, SalaryRecord
from macs.models import (
    Branch,
    Department,
    Employee,
    FamilyRelation,
    FamilyRow,
    LeaveAssign,
    LeaveTypeRow,
    LoanRefRow,
    LoanRow,
    Position,
)

SCOPE_TABLE = "GOV_SCOPE"
_PLAIN = re.compile(r"[a-z][a-z0-9_]*")
# English words for the views, one per OrderType member (a missing member fails at import, not in a query).
_ORDER_TYPE_WORDS: dict[OrderType, str] = {
    OrderType.HIRED: "hired",
    OrderType.DEPARTMENT: "department",
    OrderType.POSITION: "position",
    OrderType.FIRED: "fired",
    OrderType.PENSION: "pension",
    OrderType.TYPE_CHANGED: "type_changed",
}
_LEAVE_STATUS_WORDS: dict[int, str] = {
    LeaveAssign.APPROVED: "approved",
    LeaveAssign.CANCELLED: "cancelled",
    LeaveAssign.REJECTED: "rejected",
}
_SCOPE_CREATE = (
    "CREATE GLOBAL TEMPORARY TABLE GOV_SCOPE (EMP_ID INTEGER NOT NULL PRIMARY KEY, WORKING SMALLINT NOT NULL)"
    " ON COMMIT DELETE ROWS"
)
_SCOPE_WORKING_CHECK = (
    "SELECT COUNT(*) FROM RDB$RELATION_FIELDS WHERE TRIM(RDB$RELATION_NAME) = 'GOV_SCOPE'"
    " AND TRIM(RDB$FIELD_NAME) = 'WORKING'"
)
_GOV_VIEW_LIST = (
    "SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE RDB$VIEW_SOURCE IS NOT NULL"
    " AND TRIM(RDB$RELATION_NAME) STARTING WITH 'GOV_'"
)


def _table(model: type[Model]) -> str:
    name = str(model._meta.db_table)
    if not _PLAIN.fullmatch(name):
        raise ValueError(f"table name is not a plain identifier: {name!r}")
    return name


def _col(model: type[Model], field_name: str) -> str:
    field = model._meta.get_field(field_name)
    if not isinstance(field, Field):
        raise ValueError(f"{model.__name__}.{field_name} is not a column")
    name = str(field.column)
    if not _PLAIN.fullmatch(name):
        raise ValueError(f"column name is not a plain identifier: {name!r}")
    return name


def _case(column: str, words: Mapping[int, str]) -> str:
    """A CASE expression that maps integer codes to words; a code not in `words` gives NULL."""
    arms = " ".join(f"WHEN {int(code)} THEN '{word}'" for code, word in words.items())
    return f"TRIM(CASE {column} {arms} END)"  # TRIM: Firebird pads CASE text to a fixed width


def view_statements() -> list[str]:
    """The CREATE OR ALTER VIEW statements, built from the models. Run after GOV_SCOPE exists."""
    emp, dep, branch, pos = _table(Employee), _table(Department), _table(Branch), _table(Position)
    fam, rel = _table(FamilyRow), _table(FamilyRelation)
    employees = f"""CREATE OR ALTER VIEW GOV_EMPLOYEES (EMP_ID, FIRST_NAME, LAST_NAME, DEPARTMENT_NAME, BRANCH_NAME,
POSITION_NAME, HIRE_DATE, BIRTH_DATE, GENDER, WORKING) AS
SELECT e.{_col(Employee, "id")}, e.{_col(Employee, "given_name")}, e.{_col(Employee, "family_name")},
d.{_col(Department, "name")}, b.{_col(Branch, "name")}, p.{_col(Position, "name")},
e.{_col(Employee, "first_hire_date")}, e.{_col(Employee, "birth_date")}, e.{_col(Employee, "gender")}, w.WORKING
FROM {emp} e
JOIN GOV_SCOPE w ON w.EMP_ID = e.{_col(Employee, "id")}
LEFT JOIN {dep} d ON d.{_col(Department, "id")} = e.{_col(Employee, "department")}
LEFT JOIN {branch} b ON b.{_col(Branch, "id")} = e.{_col(Employee, "branch")}
LEFT JOIN {pos} p ON p.{_col(Position, "id")} = e.{_col(Employee, "position")}"""  # noqa: S608 (names come from the models, checked by _PLAIN)
    children = f"""CREATE OR ALTER VIEW GOV_CHILDREN (CHILD_ID, EMP_ID, BIRTH_DATE, GENDER) AS
SELECT f.{_col(FamilyRow, "id")}, f.{_col(FamilyRow, "employee")}, f.{_col(FamilyRow, "birth_date")},
CASE r.{_col(FamilyRelation, "fm_type")} WHEN 'son' THEN 'M' WHEN 'daughter' THEN 'F' END
FROM {fam} f
JOIN {rel} r ON r.{_col(FamilyRelation, "id")} = f.{_col(FamilyRow, "relation")}
WHERE r.{_col(FamilyRelation, "fm_type")} IN ('son', 'daughter')
AND EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = f.{_col(FamilyRow, "employee")})"""  # noqa: S608 (as above)
    leave_t, leave_row = _table(LeaveTypeRow), _table(LeaveAssign)
    leave = f"""CREATE OR ALTER VIEW GOV_LEAVE (LEAVE_ID, EMP_ID, LEAVE_TYPE_NAME, START_DATE, END_DATE, DAYS,
STATUS_NAME) AS
SELECT l.{_col(LeaveAssign, "id")}, l.{_col(LeaveAssign, "employee")}, t.{_col(LeaveTypeRow, "name")},
l.{_col(LeaveAssign, "date1")}, l.{_col(LeaveAssign, "date2")}, l.{_col(LeaveAssign, "adays")},
{_case(f"l.{_col(LeaveAssign, 'status')}", _LEAVE_STATUS_WORDS)}
FROM {leave_row} l
LEFT JOIN {leave_t} t ON t.{_col(LeaveTypeRow, "id")} = l.{_col(LeaveAssign, "leave_type")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = l.{_col(LeaveAssign, "employee")})"""  # noqa: S608 (as above)
    order_t = _table(HrOrder)
    orders = f"""CREATE OR ALTER VIEW GOV_ORDERS (ORDER_ID, EMP_ID, ORDER_TYPE_NAME, STATE_NAME, ORDER_NUMBER,
ORDER_DATE, SUMMARY) AS
SELECT o.{_col(HrOrder, "id")}, o.{_col(HrOrder, "employee")},
{_case(f"o.{_col(HrOrder, 'order_type')}", {int(t): w for t, w in _ORDER_TYPE_WORDS.items()})},
TRIM(o.{_col(HrOrder, "state")}), o.{_col(HrOrder, "number")}, o.{_col(HrOrder, "date")}, o.{_col(HrOrder, "summary")}
FROM {order_t} o
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE s WHERE s.EMP_ID = o.{_col(HrOrder, "employee")})"""  # noqa: S608 (as above)
    salary_t = _table(SalaryRecord)
    salary = f"""CREATE OR ALTER VIEW GOV_SALARY (SALARY_ID, EMP_ID, START_DATE, END_DATE, BASE_SALARY,
CHANGE_TYPE) AS
SELECT s.{_col(SalaryRecord, "id")}, s.{_col(SalaryRecord, "employee")}, s.{_col(SalaryRecord, "start_date")},
s.{_col(SalaryRecord, "end_date")}, s.{_col(SalaryRecord, "base_salary")}, s.{_col(SalaryRecord, "change_type")}
FROM {salary_t} s
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE sc WHERE sc.EMP_ID = s.{_col(SalaryRecord, "employee")})"""  # noqa: S608 (as above)
    loan_t, loan_ref_t = _table(LoanRow), _table(LoanRefRow)
    loans = f"""CREATE OR ALTER VIEW GOV_LOANS (LOAN_ID, EMP_ID, LOAN_DATE, END_DATE, AMOUNT, MONTHLY_PAYMENT,
REASON) AS
SELECT l.{_col(LoanRow, "id")}, l.{_col(LoanRow, "employee")}, l.{_col(LoanRow, "get_date")},
l.{_col(LoanRow, "end_date")}, l.{_col(LoanRow, "amount")}, l.{_col(LoanRow, "pay_permonth")},
r.{_col(LoanRefRow, "description")}
FROM {loan_t} l
LEFT JOIN {loan_ref_t} r ON r.{_col(LoanRefRow, "id")} = l.{_col(LoanRow, "loan_ref")}
WHERE EXISTS (SELECT 1 FROM GOV_SCOPE sc WHERE sc.EMP_ID = l.{_col(LoanRow, "employee")})"""  # noqa: S608 (as above)
    return [employees, children, leave, orders, salary, loans]


_VIEW_HEADER = re.compile(r"CREATE OR ALTER VIEW (\w+) \(([^)]*)\)", re.DOTALL)


def view_columns() -> dict[str, tuple[str, ...]]:
    """The column names of each governed view, read from its CREATE header in view_statements(). No database."""
    found: dict[str, tuple[str, ...]] = {}
    for statement in view_statements():
        match = _VIEW_HEADER.search(statement)
        if match is None:
            raise ValueError(f"no column list in view statement: {statement[:60]!r}")
        names = tuple(part.strip() for part in match.group(2).split(",") if part.strip())
        found[match.group(1)] = names
    return found


def _drop_governed(cursor: Any) -> None:
    """Drop every GOV_* view, then GOV_SCOPE. A view that reads GOV_SCOPE blocks the table's drop, so views go first."""
    cursor.execute(_GOV_VIEW_LIST)
    names = [str(row[0]) for row in cursor.fetchall()]
    for name in names:
        if not re.fullmatch(r"GOV_[A-Z0-9_]+", name):
            raise ValueError(f"not a governed view name: {name!r}")
        cursor.execute(f"DROP VIEW {name}")  # noqa: S608 (name checked above)
    cursor.execute("DROP TABLE GOV_SCOPE")


def install(connection: BaseDatabaseWrapper) -> None:
    """Create or update the governed objects in one transaction. Safe to run again.

    A table cannot be altered in place, so when GOV_SCOPE exists without the WORKING column (a database installed
    before it was added), the GOV_* views and GOV_SCOPE are dropped and created again, in this same transaction.
    The rows of GOV_SCOPE are temporary (they are filled per query), so nothing is lost. The views use CREATE OR ALTER.
    Dropping the table drops its grants: the administrator must run scripts/grant_governed_fb.sql again afterwards.
    """
    with transaction.atomic(using=connection.alias), connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM RDB$RELATIONS WHERE TRIM(RDB$RELATION_NAME) = 'GOV_SCOPE'")
        exists = bool(int(cursor.fetchone()[0]))
        if exists:
            cursor.execute(_SCOPE_WORKING_CHECK)
            if not int(cursor.fetchone()[0]):
                _drop_governed(cursor)
                exists = False
        if not exists:
            cursor.execute(_SCOPE_CREATE)
        for statement in view_statements():
            cursor.execute(statement)
