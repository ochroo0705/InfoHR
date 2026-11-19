"""Which conditions of the old query the refined query no longer has.

A refinement that adds a column can quietly turn a filter into that column (a «leave not taken» filter becomes a
«leave taken» column), and the table then shows more people than the viewer asked for. This finds the WHERE conditions
of the old query that are gone from the new one so the assistant's line can say so. It never raises: a query that
cannot be read gives no answer.
"""

from __future__ import annotations

import sqlglot
from sqlcore.firebird import Firebird
from sqlglot import exp

MAX_SHOWN = 2  # conditions named in the line
MAX_CHARS = 70  # one named condition, cut to this


def _normal(node: exp.Expr) -> str:
    """The condition as comparable text: no table aliases, today written one way."""
    copy = node.copy()
    for column in list(copy.find_all(exp.Column)):
        column.set("table", None)
    for cast in list(copy.find_all(exp.Cast)):
        inner = cast.this
        if isinstance(inner, exp.Literal) and inner.is_string and inner.name.upper() == "TODAY":
            cast.replace(exp.CurrentDate())
    return " ".join(copy.sql(dialect=Firebird, comments=False).upper().split())


def _conditions(where: exp.Expr) -> list[exp.Expr]:
    """The top-level AND parts of a WHERE condition."""
    if isinstance(where, exp.Paren):
        return _conditions(where.this)
    if isinstance(where, exp.And):
        return _conditions(where.left) + _conditions(where.right)
    return [where]


def dropped_conditions(old_sql: str, new_sql: str) -> list[str]:
    """The top-level WHERE conditions of old_sql that appear nowhere in new_sql (as written SQL, cut short)."""
    try:
        old = sqlglot.parse_one(old_sql, dialect=Firebird)
        new = sqlglot.parse_one(new_sql, dialect=Firebird)
        old_where = old.args.get("where") if isinstance(old, exp.Select) else None
        if old_where is None:
            return []
        present = {_normal(node) for node in new.walk() if isinstance(node, exp.Condition)}
        gone = []
        for part in _conditions(old_where.this):
            if _normal(part) not in present:
                text = part.sql(dialect=Firebird, comments=False)
                gone.append(text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1] + "…")
        return gone
    except Exception:
        return []
