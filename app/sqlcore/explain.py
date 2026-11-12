"""Explain a checked question in plain words, and tidy its result for display.

Plain Python on top of sqlglot. No Django, no HR imports, no database connection.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal
from enum import StrEnum

import sqlglot
from sqlglot import exp

from sqlcore.catalogue import Catalogue
from sqlcore.check import CheckedQuery
from sqlcore.firebird import Firebird
from sqlcore.limits import Result

_CENT = Decimal("0.01")

# Governed views that keep many rows per person (one per pay change or loan): their sums and averages count rows.
_HISTORY_VIEWS: frozenset[str] = frozenset({"GOV_SALARY", "GOV_LOANS"})


class Warning(StrEnum):
    JOIN_COUNTS_ROWS = "join_counts_rows"
    TRUNCATED = "truncated"
    EMPTY = "empty"
    MONEY_ROUNDED = "money_rounded"


_WARNING_TEXT: dict[Warning, str] = {
    Warning.JOIN_COUNTS_ROWS: (
        "The figures are worked out from rows, not people: a person with two matching rows is counted twice. "
        "Use COUNT(DISTINCT ...) to count people."
    ),
    Warning.TRUNCATED: "The result was cut at the row limit, so the real total may be larger than shown.",
    Warning.EMPTY: "No rows matched; the filters may be too narrow, or the data you need is not visible to you.",
    Warning.MONEY_ROUNDED: "Amounts are shown rounded to 2 decimal places.",
}


@dataclass(frozen=True)
class Explanation:
    views: tuple[str, ...]
    filters: tuple[str, ...]
    group_by: tuple[str, ...]
    aggregates: tuple[str, ...]
    row_count: int
    warnings: tuple[Warning, ...]
    sql: str


def explain(query: CheckedQuery, result: Result, catalogue: Catalogue) -> Explanation:
    """Describe the checked query and its result.

    Pass the raw result, before tidy_result, so that MONEY_ROUNDED reflects the rounding the user will see.
    The catalogue is accepted so that the explanation can be checked against the same views the query used.
    """
    root = sqlglot.parse_one(query.sql, dialect=Firebird)

    filters: list[str] = []
    group_by: list[str] = []
    for select in root.find_all(exp.Select):
        where = select.args.get("where")
        if where is not None:
            filters.extend(_render(part) for part in _and_parts(where.this))
        having = select.args.get("having")
        if having is not None:
            filters.extend(_render(part) for part in _and_parts(having.this))
        group = select.args.get("group")
        if group is not None:
            group_by.extend(_render(expression) for expression in group.expressions)

    aggregates = _unique(_render(aggregate) for aggregate in root.find_all(exp.AggFunc))

    warnings: list[Warning] = []
    joined_rows = _joins_tables(root) and (_counts_rows(root) or _sums_or_averages(root))
    if joined_rows or _sums_history_without_end_date(root, catalogue):
        warnings.append(Warning.JOIN_COUNTS_ROWS)
    if result.truncated:
        warnings.append(Warning.TRUNCATED)
    if not result.rows:
        warnings.append(Warning.EMPTY)
    if any(_rounded_value(cell) is not None for row in result.rows for cell in row):
        warnings.append(Warning.MONEY_ROUNDED)

    return Explanation(
        views=tuple(sorted(_catalogue_name(name, catalogue) for name in query.views)),
        filters=tuple(filters),
        group_by=tuple(group_by),
        aggregates=aggregates,
        row_count=len(result.rows),
        warnings=tuple(warnings),
        sql=query.sql,
    )


def tidy_result(result: Result) -> tuple[Result, bool]:
    """Round every Decimal cell to 2 places (ROUND_HALF_UP). Returns a new Result and whether anything changed."""
    changed = False
    rows: list[tuple[object, ...]] = []
    for row in result.rows:
        cells: list[object] = []
        for cell in row:
            rounded = _rounded_value(cell)
            if rounded is None:
                cells.append(cell)
            else:
                changed = True
                cells.append(rounded)
        rows.append(tuple(cells))
    tidied = Result(columns=result.columns, rows=tuple(rows), truncated=result.truncated)
    return tidied, changed


def as_english(e: Explanation) -> str:
    """One short paragraph: the views, the filters, the grouping, the rows, then each warning."""
    sentences = [f"The answer uses {', '.join(e.views) if e.views else 'no view'}."]
    if e.filters:
        sentences.append(f"Filtered by {' and '.join(e.filters)}.")
    if e.group_by:
        sentences.append(f"Grouped by {', '.join(e.group_by)}.")
    if e.aggregates:
        sentences.append(f"Aggregates: {', '.join(e.aggregates)}.")
    sentences.append(f"It returned {e.row_count} {'row' if e.row_count == 1 else 'rows'}.")
    sentences.extend(_WARNING_TEXT[warning] for warning in e.warnings)
    return " ".join(sentences)


def _and_parts(node: exp.Expr) -> list[exp.Expr]:
    """Split a condition into its top-level AND parts. Parentheses around a whole condition are looked through."""
    if isinstance(node, exp.Paren):
        return _and_parts(node.this)
    if isinstance(node, exp.And):
        return _and_parts(node.left) + _and_parts(node.right)
    return [node]


def _joins_tables(root: exp.Expr) -> bool:
    """True when some SELECT in the query reads more than one table or view in its FROM and JOIN parts."""
    for select in root.find_all(exp.Select):
        sources = 0
        from_ = select.args.get("from_")
        if from_ is not None:
            sources += 1
        sources += len(select.args.get("joins") or [])
        if sources > 1:
            return True
    return False


def _counts_rows(root: exp.Expr) -> bool:
    """True when some COUNT is not COUNT(DISTINCT ...). COUNT(*) and COUNT(column) count rows."""
    return any(not isinstance(count.this, exp.Distinct) for count in root.find_all(exp.Count))


def _sums_or_averages(root: exp.Expr) -> bool:
    """True when some SUM or AVG is taken over a column. Over a join, its figures also count rows, not people."""
    return any(aggregate.find(exp.Column) is not None for aggregate in root.find_all(exp.Sum, exp.Avg))


def _sums_history_without_end_date(root: exp.Expr, catalogue: Catalogue) -> bool:
    """True when a SUM or AVG reads GOV_SALARY or GOV_LOANS and no WHERE filters on END_DATE. Those views keep
    many rows per person (one per pay change or loan), so the total or average counts rows, not people."""
    if _filters_on_end_date(root):
        return False
    alias_views = {table.alias_or_name.upper(): table.name.upper() for table in root.find_all(exp.Table)}
    for aggregate in root.find_all(exp.Sum, exp.Avg):
        for column in aggregate.find_all(exp.Column):
            if _is_history_column(column, alias_views, catalogue):
                return True
    return False


def _filters_on_end_date(root: exp.Expr) -> bool:
    return any(
        column.name.upper() == "END_DATE" for where in root.find_all(exp.Where) for column in where.find_all(exp.Column)
    )


def _is_history_column(column: exp.Column, alias_views: dict[str, str], catalogue: Catalogue) -> bool:
    """True when the column belongs to GOV_SALARY or GOV_LOANS. A qualified name is looked up by its alias; an
    unqualified name counts when a history view in the query has a column of that name."""
    qualifier = column.table.upper()
    if qualifier:
        return alias_views.get(qualifier) in _HISTORY_VIEWS
    name = column.name.upper()
    for view_name in _HISTORY_VIEWS & set(alias_views.values()):
        view = catalogue.get(view_name)
        if view is not None and name in {c.name.upper() for c in view.columns}:
            return True
    return False


def _rounded_value(cell: object) -> Decimal | None:
    """The cell rounded to 2 places, or None when it is not a Decimal or rounding would not change it."""
    if not isinstance(cell, Decimal) or not cell.is_finite():
        return None
    context = Context(prec=max(28, cell.adjusted() + 6), rounding=ROUND_HALF_UP)
    rounded = cell.quantize(_CENT, context=context)
    return rounded if rounded != cell else None


def _catalogue_name(name: str, catalogue: Catalogue) -> str:
    """The view name as the catalogue spells it; the checker has already confirmed the view is in it."""
    view = catalogue.get(name)
    return view.name if view is not None else name


def _render(node: exp.Expr) -> str:
    return node.sql(dialect=Firebird, comments=False)


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return tuple(seen)
