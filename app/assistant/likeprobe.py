"""Find a LIKE in model SQL that matches no row of its view, so the model can be asked again with the real values.

A wrong word stem ('%аралт%' for «амралт») or a stem in the wrong language matches nothing. Inside NOT EXISTS that
keeps every row, inside EXISTS it drops every row, and the answer looks fine. For each LIKE whose column belongs to one
governed view, a one-row probe runs as the asker (so the checker and the scope still apply). A miss returns a refusal
text that names the column and lists its values; the caller feeds it back once.

Plain Python plus sqlglot; the queries go through sqlcore.runner.run_question.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlcore.firebird import Firebird
from sqlcore.limits import Limits
from sqlcore.runner import Host, Refused, run_question
from sqlglot import exp

MAX_PROBES = 4  # the most LIKEs probed for one query
MAX_VALUES = 25  # the most distinct values listed in the feedback
PROBE_TIMEOUT_S = 5.0
# Values of these columns are about a person (a name, a number, free text): they are never sent to the model.
PERSONAL = ("FIRST_NAME", "LAST_NAME", "MANAGER_NAME", "GIVEN_BY", "ORGANISATION", "SUMMARY", "ORDER_NUMBER",
            "CONTRACT_NUMBER", "DIPLOMA_NUMBER", "CERTIFICATE_NUMBER")


@dataclass(frozen=True)
class Like:
    view: str
    column: str
    pattern: str  # the SQL text of the pattern literal, quotes included


def _inner(node: exp.Expression) -> exp.Expression:
    return node.this if isinstance(node, exp.Upper) else node


def _tables(select: exp.Select) -> dict[str, str]:
    """{alias or name (upper): view name (upper)} for the tables in this SELECT's own FROM and JOINs."""
    found: dict[str, str] = {}
    sources = []
    origin = select.args.get("from_") or select.args.get("from")  # the key is "from_" in newer sqlglot
    if origin is not None:
        sources.append(origin.this)
    sources += [join.this for join in select.args.get("joins") or []]
    for source in sources:
        if isinstance(source, exp.Table):
            name = source.name.upper()
            found[(source.alias or source.name).upper()] = name
    return found


def likes_in(sql: str) -> list[Like]:
    """The LIKEs of the query whose column is a plain column of one governed view and whose pattern is a literal."""
    try:
        tree = sqlglot.parse_one(sql, read=Firebird)
    except (sqlglot.errors.SqlglotError, ValueError, TypeError, RecursionError):
        return []
    found: list[Like] = []
    for like in tree.find_all(exp.Like):
        column, pattern = _inner(like.this), _inner(like.expression)
        if not isinstance(column, exp.Column) or not isinstance(pattern, exp.Literal) or not pattern.is_string:
            continue
        select = like.find_ancestor(exp.Select)
        tables = _tables(select) if select is not None else {}
        if column.table:
            view = tables.get(column.table.upper())
        else:
            view = next(iter(tables.values())) if len(tables) == 1 else None
        if view is None or not view.startswith("GOV_"):
            continue
        item = Like(view, column.name.upper(), pattern.sql(dialect=Firebird))
        if item not in found:
            found.append(item)
    return found[:MAX_PROBES]


def _limits(rows: int) -> Limits:
    return Limits(max_rows=rows, timeout_s=PROBE_TIMEOUT_S)


def _distinct(item: Like) -> str:
    return f"SELECT DISTINCT {item.column} FROM {item.view}"  # noqa: S608 - parsed names; check_sql checks it


def missing_like(host: Host, user: object, sql: str) -> str:
    """A refusal text for the first LIKE that matches no row of its view, or "" when every LIKE matches (or a probe
    cannot run: a probe never blocks an answer). Values are listed only for a short category column, never a
    personal one. The text is fed back to the model as the reason to try again."""
    for item in likes_in(sql):
        # Names come from the parsed query and the pattern is the re-rendered literal; check_sql checks the probe.
        probe = f"SELECT FIRST 1 1 AS X FROM {item.view} WHERE UPPER({item.column}) LIKE UPPER({item.pattern})"  # noqa: S608
        outcome = run_question(host, user, probe, _limits(1))
        if isinstance(outcome, Refused) or outcome.result.rows:
            continue
        listed = ""
        values = (
            Refused(reason="personal")
            if item.column in PERSONAL
            else run_question(host, user, _distinct(item), _limits(MAX_VALUES))
        )
        # Only a short list of category words is sent (leave types, departments): a long list is likely personal.
        if not isinstance(values, Refused) and not values.result.truncated:
            texts = [str(row[0]).strip() for row in values.result.rows if row and row[0] is not None]
            listed = " Its values are: " + "; ".join(f"«{text}»" for text in texts if text) + "."
        return (
            f"{item.column} LIKE {item.pattern} matches no row of {item.view}, so that condition is always false "
            f"(and NOT EXISTS over it always true).{listed} Use a stem that is part of the value the question means, "
            "or drop the condition if no value fits."
        )
    return ""
