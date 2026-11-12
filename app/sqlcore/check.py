"""The SQL checker: one read-only SELECT over the governed views of a catalogue, and nothing else.

Plain Python on top of sqlglot. No Django, no HR imports, no database connection.
The checked query is re-rendered from the parse tree, so comments never reach the database.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from sqlcore.catalogue import Catalogue, View
from sqlcore.firebird import Firebird

# Functions a question may call. sqlglot reads CHAR_LENGTH as LENGTH, so both names are listed.
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "COUNT",
        "SUM",
        "AVG",
        "MIN",
        "MAX",
        "COALESCE",
        "NULLIF",
        "CAST",
        "EXTRACT",
        "UPPER",
        "LOWER",
        "TRIM",
        "SUBSTRING",
        "CHAR_LENGTH",
        "LENGTH",
        "DATEADD",
        "DATEDIFF",
        "ABS",
        "ROUND",
    }
)

# Expression keywords that sqlglot parses as functions but that are not calls: CASE and CURRENT_DATE.
ALLOWED_KEYWORDS: frozenset[str] = frozenset({"CASE", "CURRENT_DATE"})

# Unit words for DATEADD and DATEDIFF.
DATE_PARTS: frozenset[str] = frozenset(
    {"YEAR", "QUARTER", "MONTH", "WEEK", "DAY", "HOUR", "MINUTE", "SECOND", "MILLISECOND"}
)

# Any of these anywhere in the tree (also nested inside a CTE) is refused.
_FORBIDDEN_NODES: tuple[type[exp.Expr], ...] = (
    exp.DML,
    exp.DDL,
    exp.Command,
    exp.Into,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Set,
    exp.Use,
    exp.Pragma,
)


# A common table (WITH name) may not take a name that is governed, a system table, or a scope table.
_RESERVED_CTE_PREFIXES: tuple[str, ...] = ("GOV_", "IHR_", "RDB$", "MON$", "SEC$")


class CheckError(ValueError):
    """The query is not allowed. The message is for the user and says what to change."""


@dataclass(frozen=True)
class CheckedQuery:
    sql: str
    views: frozenset[str]


def check_sql(sql: str, catalogue: Catalogue) -> CheckedQuery:
    root = _parse_one(sql)
    if not isinstance(root, (exp.Select, exp.SetOperation)):
        raise CheckError("Only one SELECT query is allowed.")

    for node in root.find_all(*_FORBIDDEN_NODES):
        raise CheckError(f"{type(node).__name__} is not allowed; only reading is allowed.")

    # FOR UPDATE / FOR SHARE: sqlglot parses it and the rendered SQL silently drops it, so refuse it here.
    if root.find(exp.Lock) is not None:
        raise CheckError("Locking reads (FOR UPDATE) are not allowed; only reading is allowed.")

    for identifier in root.find_all(exp.Identifier):
        if identifier.quoted:
            raise CheckError(f"Quoted name {identifier.name} is not allowed; write the name without quotes.")

    _check_common_tables(root, catalogue)
    views_by_name: dict[str, View] = {}
    # Table name or alias (upper case) -> the view it stands for; None for a CTE or a derived table.
    targets: dict[str, View | None] = {}

    for table in root.find_all(exp.Table):
        if table.args.get("db") or table.args.get("catalog"):
            raise CheckError(f"Qualified table name {table.sql()} is not allowed; use a governed view name.")
        name = table.name.upper()
        if name in _visible_common_tables(table):
            target: View | None = None
        else:
            view = catalogue.get(name)
            if view is None:
                raise CheckError(f"Table {name} is not a governed view you may use.")
            views_by_name[view.name.upper()] = view
            target = view
        targets[table.alias_or_name.upper()] = target

    for subquery in root.find_all(exp.Subquery):
        if subquery.alias:
            targets[subquery.alias.upper()] = None

    known_columns: set[str] = set()
    for view in views_by_name.values():
        known_columns.update(column.name.upper() for column in view.columns)
    alias_names = {alias.alias.upper() for alias in root.find_all(exp.Alias)}

    for star in root.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise CheckError("Name the columns you need; only COUNT(*) may use *.")

    for func in root.find_all(exp.Func):
        if isinstance(func, exp.Connector):
            continue  # AND and OR: boolean operators, their operands are checked on their own
        if isinstance(func, exp.If) and isinstance(func.parent, exp.Case):
            continue  # the WHEN branch of a CASE expression, not a call to IF
        if isinstance(func, exp.Exists):
            # EXISTS (subquery) and NOT EXISTS (subquery) are read-only predicates. The walk below reaches every
            # table and column inside the subquery, so only the wrapping form needs a check here.
            if not isinstance(func.this, (exp.Select, exp.SetOperation)):
                raise CheckError("EXISTS must be followed by a subquery, for example EXISTS (SELECT 1 FROM ...).")
            continue
        name = _function_name(func)
        if name not in ALLOWED_FUNCTIONS and name not in ALLOWED_KEYWORDS:
            raise CheckError(f"Function {name} is not allowed in a question.")

    for column in root.find_all(exp.Column):
        name = column.name.upper()
        qualifier = column.table.upper()
        if qualifier:
            if qualifier not in targets:
                raise CheckError(f"Name {qualifier} for column {name} is not a table in this query.")
            view = targets[qualifier]
            if view is None:
                continue
            if name not in {c.name.upper() for c in view.columns}:
                raise CheckError(f"Column {name} is not on the view {view.name.upper()}.")
        elif _is_date_part(column):
            continue
        elif name not in known_columns | alias_names:
            raise CheckError(f"Column {name} is not on any view this query uses.")

    return CheckedQuery(sql=_render(root), views=frozenset(views_by_name))


def _check_common_tables(root: exp.Expr, catalogue: Catalogue) -> None:
    """Refuse WITH RECURSIVE, a repeated CTE name, and a CTE name that could hide a real table."""
    for with_node in root.find_all(exp.With):
        if with_node.args.get("recursive"):
            raise CheckError("WITH RECURSIVE is not allowed; write each common table in order, without recursion.")
    seen: set[str] = set()
    for cte in root.find_all(exp.CTE):
        name = cte.alias.upper()
        if name in seen:
            raise CheckError(f"Common table name {name} is defined twice; give each one its own name.")
        seen.add(name)
        if catalogue.get(name) is not None or name.startswith(_RESERVED_CTE_PREFIXES):
            raise CheckError(f"Name {name} is reserved and cannot name a common table.")


def _visible_common_tables(table: exp.Table) -> set[str]:
    """The CTE names a table reference may resolve to. A CTE is visible only to the query that owns its WITH clause,
    and inside a CTE body only to the CTEs defined before it, so a CTE cannot read itself or a later CTE."""
    visible: set[str] = set()
    child: exp.Expr = table
    node = table.parent
    while node is not None:
        if isinstance(node, exp.CTE) and isinstance(node.parent, exp.With):
            earlier = []
            for definition in node.parent.expressions:
                if definition is node:
                    break
                earlier.append(definition)
            visible.update(definition.alias.upper() for definition in earlier)
        owned = node.args.get("with_")
        if isinstance(owned, exp.With) and child is not owned:
            visible.update(definition.alias.upper() for definition in owned.expressions)
        child, node = node, node.parent
    return visible


def _parse_one(sql: str) -> exp.Expr:
    try:
        parsed = sqlglot.parse(sql, dialect=Firebird)
    except (SqlglotError, ValueError) as error:
        raise CheckError(f"The query does not parse: {error}") from error
    statements = [statement for statement in parsed if statement is not None]
    if len(statements) != 1:
        raise CheckError("Send exactly one statement.")
    return statements[0]


def _render(root: exp.Expr) -> str:
    """The checked SQL as Firebird 3 text. Rendering can refuse a form Firebird lacks; that is a CheckError."""
    try:
        return root.sql(dialect=Firebird, comments=False)
    except SqlglotError as error:
        raise CheckError(f"The query cannot be written for Firebird: {error}") from error


def _is_date_part(column: exp.Column) -> bool:
    """sqlglot reads the unit word of DATEADD and DATEDIFF (DAY, YEAR ...) as a column. It is not one."""
    if column.table or column.name.upper() not in DATE_PARTS:
        return False
    parent = column.parent
    if isinstance(parent, exp.DateDiff):
        return column.arg_key == "this"
    if isinstance(parent, exp.Anonymous) and _function_name(parent) == "DATEADD":
        return bool(parent.expressions) and parent.expressions[0] is column
    return False


def _function_name(func: exp.Func) -> str:
    if isinstance(func, exp.Anonymous):
        return func.name.upper()
    return func.sql_name().upper()
