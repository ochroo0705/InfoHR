"""SQL for the assistant workspace tools: wrap a tab's saved query in one new SELECT.

A tool (filter, sort, columns, page, count, group) never runs its own SQL. It takes the tab's saved, checked SQL as
``ws_base`` and writes one ``SELECT ... FROM ws_base ...``. The caller runs the result through the existing checker
and runner, so every tool call is checked again.

Plain Python only. No Django, no HR imports, no database connection.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

import sqlglot
from sqlcore.firebird import Firebird
from sqlglot import exp

from assistant.ws_limits import PAGE_SIZE

OPS: frozenset[str] = frozenset({"contains", "eq", "gt", "lt", "empty", "notempty"})
DIRECTIONS: frozenset[str] = frozenset({"asc", "desc"})

# Only plain names can be used by a tool: letters, digits and underscore, starting with a letter.
_PLAIN_NAME = re.compile(r"[A-Z][A-Z0-9_]*", re.IGNORECASE | re.ASCII)

# The name the saved query is given inside the wrapper (a derived table alias).
BASE_NAME = "ws_base"

# The alias of the row count made by count_sql and group_sql.
COUNT_NAME = "N"

# The longest filter value a viewer may type. A longer one is refused, not cut.
MAX_FILTER_CHARS = 200

# The largest power of ten a gt or lt number may have (1E+40 is allowed, 1E+41 is refused).
MAX_NUMBER_EXPONENT = 40

# The text type each column is cast to for the LIKE and empty-value checks, so any column type can be compared as text.
_TEXT = "VARCHAR(4000)"


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    value: str = ""


@dataclass(frozen=True)
class Spec:
    columns: tuple[str, ...] = ()
    filters: tuple[Filter, ...] = ()
    sort: tuple[tuple[str, str], ...] = ()
    group_by: str = ""


class SpecError(ValueError):
    """A tool request that cannot be turned into SQL. The message is for the user."""


def usable_columns(columns: Iterable[str]) -> tuple[str, ...]:
    """The columns a tool may name: plain identifiers only, always upper-cased. Others (with a space, a quote, a dot)
    are left out, and so is every copy of a name that appears more than once (case-insensitively), because the
    wrapper selects by name and two columns of one name cannot be told apart. Quoting is not an option (the checker
    refuses quoted names), so the upper-case form is what is used."""
    names = list(columns)
    counts = Counter(name.upper() for name in names)
    return tuple(name.upper() for name in names if _PLAIN_NAME.fullmatch(name) and counts[name.upper()] == 1)


def _usable_or_raise(columns: Iterable[str]) -> tuple[str, ...]:
    usable = usable_columns(columns)
    if not usable:
        raise SpecError("This result has no column a tool can use.")
    return usable


def _resolve(name: object, usable: tuple[str, ...]) -> str:
    """The upper-cased column from the usable list, matched case-insensitively. Anything else is refused,
    so no user text reaches the SQL."""
    if isinstance(name, str):
        wanted = name.strip().upper()
        for column in usable:
            if column.upper() == wanted:
                return column
    raise SpecError(f"Column {name} is not in this result.")


def _literal(value: str) -> str:
    if "\x00" in value:
        raise SpecError("A filter value cannot contain a NUL character.")
    return "'" + value.replace("'", "''") + "'"


def _number(value: str) -> str:
    """A number written as plain digits for gt and lt. Anything that is not a finite number is refused."""
    try:
        number = Decimal(value.strip())
    except (ArithmeticError, ValueError) as error:
        raise SpecError(f"{value} is not a number.") from error
    if not number.is_finite():
        raise SpecError(f"{value} is not a number.")
    # format(..., "f") writes every digit, so a huge exponent would make a huge string. Bound the size instead.
    if abs(number.adjusted()) > MAX_NUMBER_EXPONENT:
        raise SpecError(f"{value} is too large or too small to compare.")
    return format(number, "f")


def _condition(column: str, item: Filter) -> str:
    if item.op == "eq":
        return f"{column} = {_literal(item.value)}"
    if item.op == "gt":
        return f"{column} > {_number(item.value)}"
    if item.op == "lt":
        return f"{column} < {_number(item.value)}"
    if item.op == "contains":
        # Escape the LIKE wildcards so the typed text is matched as text. ESCAPE '\' is the escape character.
        escaped = item.value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = _literal("%" + escaped + "%")
        return f"UPPER(CAST({column} AS {_TEXT})) LIKE UPPER({pattern}) ESCAPE '\\'"
    if item.op == "empty":
        return f"({column} IS NULL OR CAST({column} AS {_TEXT}) = '')"
    # "notempty" is the last of OPS; _conditions has already refused any other op.
    return f"({column} IS NOT NULL AND CAST({column} AS {_TEXT}) <> '')"


def _conditions(spec: Spec, usable: tuple[str, ...]) -> list[str]:
    conditions = []
    for item in spec.filters:
        if not isinstance(item.op, str) or item.op not in OPS:
            raise SpecError(f"Filter {item.op} is not a known condition.")
        if len(item.value) > MAX_FILTER_CHARS:
            raise SpecError(f"A filter value can be at most {MAX_FILTER_CHARS} characters.")
        conditions.append(_condition(_resolve(item.column, usable), item))
    return conditions


def _orders(spec: Spec, usable: tuple[str, ...]) -> list[str]:
    orders = []
    for name, direction in spec.sort:
        normal = direction.lower() if isinstance(direction, str) else ""
        if normal not in DIRECTIONS:
            raise SpecError(f"Sort direction {direction} is not asc or desc.")
        orders.append(f"{_resolve(name, usable)} {normal.upper()}")
    return orders


def base_orders(base_sql: str, usable: tuple[str, ...]) -> list[str]:
    """The ORDER BY of the saved query's outermost SELECT, written as ``NAME ASC|DESC`` terms the wrapper can use.

    A term is kept when it is a plain usable column, or when its expression is the same as a projection that has a
    usable alias (then the alias is used). The first term that cannot be named stops the list, so the order is never
    changed by a part that was dropped. Any parse error gives an empty list."""
    try:
        tree = sqlglot.parse_one(base_sql.strip().rstrip(";").strip(), read=Firebird)
    except (sqlglot.errors.SqlglotError, ValueError, TypeError, RecursionError):
        return []
    if not isinstance(tree, exp.Select):
        return []
    order = tree.args.get("order")
    if order is None:
        return []

    aliases: dict[str, str] = {}
    for projection in tree.expressions:
        if isinstance(projection, exp.Alias) and projection.alias.upper() in usable:
            aliases.setdefault(projection.this.sql(dialect=Firebird), projection.alias.upper())

    orders: list[str] = []
    for term in order.expressions:
        direction = "DESC" if term.args.get("desc") else "ASC"
        expression = term.this
        if isinstance(expression, exp.Column) and not expression.table and expression.name.upper() in usable:
            orders.append(f"{expression.name.upper()} {direction}")
            continue
        alias = aliases.get(expression.sql(dialect=Firebird))
        if alias is None:
            break
        orders.append(f"{alias} {direction}")
    return orders


def _from_base(base_sql: str) -> str:
    # A derived table, not a WITH clause: the renderer in sqlcore/firebird.py cannot add a row window to a SELECT
    # that starts with WITH (it expects the text to start with SELECT).
    base = base_sql.strip().rstrip(";").strip()
    return f"FROM (\n{base}\n) {BASE_NAME}"


def _where(conditions: list[str]) -> str:
    return " WHERE " + " AND ".join(conditions) if conditions else ""


def _check_page(page: object) -> None:
    """A page is None (no window) or a whole number of 0 or more. A bool, a float or a string is refused."""
    if page is None:
        return
    if not isinstance(page, int) or isinstance(page, bool):
        raise SpecError("A page number must be a whole number.")
    if page < 0:
        raise SpecError("A page number cannot be negative.")


def _window(sql: str, page: int | None) -> str:
    """Add the Firebird row window for one page (0-based). No window when page is None."""
    if page is None:
        return sql
    first = page * PAGE_SIZE + 1
    last = (page + 1) * PAGE_SIZE
    return sql + f" ROWS {first} TO {last}"


def wrap_sql(base_sql: str, columns: tuple[str, ...], spec: Spec, *, page: int | None = None) -> str:
    """One SELECT over the saved query. ``columns`` are the base result's column names; ``page`` is 0-based.

    ``spec.group_by`` is ignored here: grouping is rendered only by ``group_sql``.
    With a page and no sort, rows are ordered by the first usable column so that pages do not overlap."""
    _check_page(page)
    usable = _usable_or_raise(columns)

    if spec.columns:
        selected = tuple(dict.fromkeys(_resolve(name, usable) for name in spec.columns))
    else:
        selected = usable

    conditions = _conditions(spec, usable)
    orders = _orders(spec, usable)
    if not orders:
        # Keep the saved query's own order (e.g. ORDER BY COUNT(*) DESC) instead of losing it in the wrapper.
        orders = base_orders(base_sql, usable)
        if page is not None and usable[0] not in (order.rsplit(" ", 1)[0] for order in orders):
            # A tie-breaker, so that pages do not overlap when the order is not unique.
            orders.append(f"{usable[0]} ASC")

    sql = f"SELECT {', '.join(selected)} {_from_base(base_sql)}" + _where(conditions)
    if orders:
        sql += " ORDER BY " + ", ".join(orders)
    return _window(sql, page)


def count_sql(base_sql: str, columns: tuple[str, ...], spec: Spec) -> str:
    """One row: ``N``. Without ``spec.group_by`` it is the number of rows of the saved query that pass the filters.
    With ``spec.group_by`` it is the number of groups that those rows fall into (the total of a grouped view).
    Columns and sort are ignored."""
    usable = _usable_or_raise(columns)
    conditions = _conditions(spec, usable)
    if spec.group_by:
        group = _resolve(spec.group_by, usable)
        if group == COUNT_NAME:
            raise SpecError(f"A column named {COUNT_NAME} cannot be grouped; the count uses that name.")
        grouped = f"SELECT {group} {_from_base(base_sql)}" + _where(conditions) + f" GROUP BY {group}"
        return f"SELECT COUNT(*) AS {COUNT_NAME} FROM ({grouped}) AS ws_groups"
    return f"SELECT COUNT(*) AS {COUNT_NAME} {_from_base(base_sql)}" + _where(conditions)


def group_sql(base_sql: str, columns: tuple[str, ...], spec: Spec, *, page: int | None = None) -> str:
    """Rows of ``<group_by>, N``: how many filtered rows fall in each value of the group column, biggest first.
    Ordered by N descending, then the group column. Columns and sort are ignored."""
    _check_page(page)
    usable = _usable_or_raise(columns)
    if not spec.group_by:
        raise SpecError("Name the column to group by.")
    group = _resolve(spec.group_by, usable)
    if group == COUNT_NAME:
        raise SpecError(f"A column named {COUNT_NAME} cannot be grouped; the count uses that name.")
    conditions = _conditions(spec, usable)
    sql = (
        f"SELECT {group}, COUNT(*) AS {COUNT_NAME} {_from_base(base_sql)}"
        + _where(conditions)
        + f" GROUP BY {group} ORDER BY {COUNT_NAME} DESC, {group} ASC"
    )
    return _window(sql, page)


def spec_to_json(spec: Spec) -> str:
    data = {
        "columns": list(spec.columns),
        "filters": [{"column": f.column, "op": f.op, "value": f.value} for f in spec.filters],
        "sort": [[name, direction] for name, direction in spec.sort],
        "group_by": spec.group_by,
    }
    return json.dumps(data, ensure_ascii=False)


def spec_from_json(text: str, columns: tuple[str, ...]) -> Spec:
    """Read a saved spec. Anything naming a column not in ``columns``, an unknown op or direction, or a value that is
    not text or is too long, is dropped. Never raises on bad input."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError, RecursionError):
        return Spec()
    if not isinstance(data, dict):
        return Spec()

    usable = usable_columns(columns)

    def canon(name: object) -> str | None:
        try:
            return _resolve(name, usable)
        except SpecError:
            return None

    def items(key: str) -> list:
        value = data.get(key)
        return value if isinstance(value, list) else []

    selected = tuple(dict.fromkeys(name for name in (canon(x) for x in items("columns")) if name))

    filters = []
    for item in items("filters"):
        if not isinstance(item, dict):
            continue
        column = canon(item.get("column"))
        op = item.get("op")
        value = item.get("value", "")
        if column is None or not isinstance(op, str) or op not in OPS:
            continue
        if not isinstance(value, str) or len(value) > MAX_FILTER_CHARS or "\x00" in value:
            continue
        if op in ("gt", "lt"):
            try:
                _number(value)  # a missing, non-numeric or huge number makes the filter unusable: drop it
            except SpecError:
                continue
        filters.append(Filter(column, op, value))

    sort = []
    for item in items("sort"):
        if not isinstance(item, list) or len(item) != 2:
            continue
        column = canon(item[0])
        direction = item[1]
        if column is None or not isinstance(direction, str) or direction.lower() not in DIRECTIONS:
            continue
        sort.append((column, direction.lower()))

    group_by = canon(data.get("group_by")) or ""
    if group_by == COUNT_NAME:  # the count uses that name, so it cannot be grouped (group_sql refuses it)
        group_by = ""
    return Spec(columns=selected, filters=tuple(filters), sort=tuple(sort), group_by=group_by)
