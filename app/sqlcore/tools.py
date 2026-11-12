"""Tool definitions and the dispatcher for the governed SQL assistant.

The model sees two tools: describe_data (which views it may use, in words) and run_query (one checked SELECT).
handle() never raises on bad input: every failure comes back as {"ok": False, "reason": ...}.

Plain Python on top of the core modules. No Django, no HR imports, no database connection.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal

from sqlcore.catalogue import Catalogue, View
from sqlcore.explain import as_english, explain, tidy_result
from sqlcore.limits import Limits
from sqlcore.runner import DEFAULT_LIMITS, Host, Refused, run_question

DESCRIBE_TOOL = "describe_data"
RUN_TOOL = "run_query"
MAX_SQL_LENGTH = 4000

TOOLS: tuple[dict[str, object], ...] = (
    {
        "name": DESCRIBE_TOOL,
        "description": (
            "List the data you may query: each view with its description, its rules and its columns. "
            "Call this before writing a query."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": RUN_TOOL,
        "description": (
            "Run one read-only SELECT over the views that describe_data lists. Only those GOV_ views may be used. "
            "List the columns you need instead of SELECT *. Join views on their ID columns. "
            "For a head count of working employees use WORKING = 1 where the view has that column. "
            "Count people with COUNT(DISTINCT ...) when a view has one row per child or per record."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "maxLength": MAX_SQL_LENGTH,
                    "description": "One SELECT statement. No semicolons, no comments, no other statements.",
                },
            },
            "required": ["sql"],
        },
    },
)


def describe_text(catalogue: Catalogue) -> str:
    """The catalogue as plain text for the model: each view with its rules, then each column with its synonyms."""
    if not catalogue.views:
        return "No views are available to you."
    return "\n\n".join(_describe_view(view) for view in catalogue.views)


def handle(
    host: Host,
    user: object,
    name: str,
    arguments: dict[str, object],
    limits: Limits = DEFAULT_LIMITS,
) -> dict[str, object]:
    """Run one tool call for this user. Returns a JSON-safe dict; never raises for a bad call."""
    if name == DESCRIBE_TOOL:
        return {"ok": True, "text": describe_text(host.catalogue_for(user))}
    if name == RUN_TOOL:
        return _run(host, user, arguments, limits)
    return _refuse(f"Unknown tool: {name}.")


def _run(host: Host, user: object, arguments: dict[str, object], limits: Limits) -> dict[str, object]:
    sql = arguments.get("sql") if isinstance(arguments, dict) else None
    if not isinstance(sql, str):
        return _refuse("The sql argument must be one text string.")
    if len(sql) > MAX_SQL_LENGTH:
        return _refuse(f"The sql argument is longer than {MAX_SQL_LENGTH} characters.")

    outcome = run_question(host, user, sql, limits)
    if isinstance(outcome, Refused):
        return _refuse(outcome.reason)

    # Explain the raw result first: MONEY_ROUNDED must reflect the rounding the user will see.
    explanation = explain(outcome.query, outcome.result, host.catalogue_for(user))
    tidied, _changed = tidy_result(outcome.result)
    return {
        "ok": True,
        "columns": list(tidied.columns),
        "rows": [[_json_cell(cell) for cell in row] for row in tidied.rows],
        "explanation": as_english(explanation),
        "sql": explanation.sql,
        "warnings": [warning.value for warning in explanation.warnings],
        "row_count": explanation.row_count,
    }


def _refuse(reason: str) -> dict[str, object]:
    return {"ok": False, "reason": reason}


def _json_cell(cell: object) -> object:
    """Turn one cell into a JSON-safe value: numbers and text stay, money and dates become strings."""
    if cell is None or isinstance(cell, (bool, int, str)):
        return cell
    if isinstance(cell, float):
        return cell if math.isfinite(cell) else str(cell)
    if isinstance(cell, Decimal):
        return str(cell)
    if isinstance(cell, (date, datetime)):
        return cell.isoformat()
    if isinstance(cell, (bytes, bytearray, memoryview)):
        return bytes(cell).hex()
    return str(cell)


def _describe_view(view: View) -> str:
    lines = [f"{view.name}: {view.description}"]
    if view.description_mn:
        lines.append(f"  Mongolian: {view.description_mn}")
    for rule in view.rules:
        lines.append(f"  Rule: {rule}")
    lines.append("  Columns:")
    for column in view.columns:
        lines.append(f"  - {column.name}: {column.description}")
        if column.synonyms:
            lines.append(f"    Also called: {', '.join(column.synonyms)}")
        if column.description_mn:
            lines.append(f"    Mongolian: {column.description_mn}")
    return "\n".join(lines)
