"""Conditional colours: up to MAX_MARKS rules that colour a cell when its value passes.

Pure functions only. The address text is a JSON list of {"c": column, "o": operator, "v": value, "k": colour}.
Bad input never raises: a bad item is dropped.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from reports import rules

COLOURS: dict[str, str] = {
    "red": "bg-red-50 text-red-700",
    "amber": "bg-amber-50 text-amber-800",
    "green": "bg-green-50 text-green-700",
    "blue": "bg-blue-50 text-blue-700",
    "grey": "bg-slate-100 text-slate-600",
}
MAX_MARKS = 5  # marks in one address
MAX_TEXT = 2000  # characters in the whole address text


@dataclass(frozen=True)
class Mark:
    """One colour rule: when the column's value passes (rule_op, value), the cell gets the colour."""

    column: str
    rule_op: str
    value: str
    colour: str


# ---- the address text ----


def parse_marks(text: str) -> tuple[Mark, ...]:
    """Read the JSON list of marks. Bad items are dropped, at most MAX_MARKS are kept, and text over MAX_TEXT
    characters gives (). Never raises."""
    if not isinstance(text, str) or not text or len(text) > MAX_TEXT:
        return ()
    try:
        raw = json.loads(text)
    except (ValueError, RecursionError):
        return ()
    if not isinstance(raw, list):
        return ()
    marks: list[Mark] = []
    for item in raw:
        mark = _parse_mark(item)
        if mark is not None:
            marks.append(mark)
            if len(marks) >= MAX_MARKS:
                break
    return tuple(marks)


def _parse_mark(item: object) -> Mark | None:
    """One item {"c", "o", "v", "k"}. Needs a known operator and colour; a number value becomes text, a missing
    value is empty, and a value longer than the rule limit is cut to it."""
    if not isinstance(item, dict):
        return None
    column, op, colour = item.get("c"), item.get("o"), item.get("k")
    if not isinstance(column, str) or not column:
        return None
    if not isinstance(op, str) or op not in rules.KNOWN_OPS:
        return None
    if not isinstance(colour, str) or colour not in COLOURS:
        return None
    value = _mark_value(item.get("v", ""))
    if value is None or not _encodable(column) or not _encodable(value):
        return None  # a lone surrogate cannot be written as UTF-8 in a link: this mark is dropped
    return Mark(column=column, rule_op=op, value=value[: rules.MAX_VALUE], colour=colour)


def _encodable(text: str) -> bool:
    """True when the text can be written as UTF-8 (a lone surrogate from a JSON escape cannot)."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _mark_value(raw: object) -> str | None:
    """The value as text: text as it is, a number as its text; any other type (bool, list, dict, null) is None."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return str(raw)
    return None


def dump_marks(marks: Sequence[Mark]) -> str:
    """The compact JSON text of the marks, read back by parse_marks. Empty text for no marks."""
    if not marks:
        return ""
    items = [{"c": m.column, "o": m.rule_op, "v": m.value, "k": m.colour} for m in marks]
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


# ---- the colour of one cell ----


def mark_for(marks: Sequence[Mark], column_key: str, value: object, kind: str, today: date) -> str:
    """The CSS classes of the first mark on this column whose rule the value passes, else "".

    A mark whose operator is not valid for the column's kind never passes, so it gives no colour.
    """
    for mark in marks:
        if mark.column != column_key:
            continue
        rule = rules.Rule(column=column_key, op=mark.rule_op, value=mark.value)
        if rules.test_rule(rule, value, kind, today) is True:
            return COLOURS.get(mark.colour, "")
    return ""
