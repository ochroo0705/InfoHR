"""The rule tree for report filters: parse, check, evaluate and describe rules.

Pure functions only. A rule is one condition (column, operator, value); a group joins rules
or other groups with AND or OR. Bad input never raises: it is ignored or refused.
"""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reports.types import Column

MAX_DEPTH = 3  # groups may nest this deep
MAX_RULES = 20  # rules in one tree
MAX_VALUE = 100  # characters in one rule value
MAX_TEXT = 2000  # characters in the whole address text
MAX_DAYS = 36500  # the largest day count in «next_days» / «last_days» (about 100 years)

_NUMBER_TEXT = re.compile(
    r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]{1,3})?"
)  # digits only, an optional exponent: no spaces, no underscores
_DAY_COUNT = re.compile(r"[0-9]{1,6}")  # a plain non-negative whole number of days

OPS: dict[str, tuple[str, ...]] = {
    "text": ("contains", "not_contains", "eq", "neq", "starts", "empty", "filled"),
    "number": ("eq", "neq", "gt", "gte", "lt", "lte", "between", "empty", "filled"),
    "date": ("on", "before", "after", "between", "next_days", "last_days", "empty", "filled"),
}

OP_LABELS: dict[str, str] = {
    "contains": "агуулсан",
    "not_contains": "агуулаагүй",
    "eq": "тэнцүү",
    "neq": "тэнцүү биш",
    "starts": "эхэлсэн",
    "empty": "хоосон",
    "filled": "хоосон биш",
    "gt": ">",
    "gte": "≥",
    "lt": "<",
    "lte": "≤",
    "between": "хооронд",
    "on": "өдөр",
    "before": "өмнө",
    "after": "дараа",
    "next_days": "ирэх … хоногт",
    "last_days": "өнгөрсөн … хоногт",
}

GROUP_OPS = ("and", "or")
KNOWN_OPS = {code for codes in OPS.values() for code in codes}
BLANK_MATCHES = frozenset({"neq", "not_contains"})  # the only operators that match a blank cell


@dataclass(frozen=True)
class Rule:
    """One condition: the column, the operator code and the typed value."""

    column: str
    op: str
    value: str = ""


@dataclass(frozen=True)
class Group:
    """Rules and groups joined by AND (op "and") or OR (op "or")."""

    op: str
    items: tuple["Rule | Group", ...]


class _Invalid(Exception):
    """Raised inside the parser when the whole text must be refused."""


# ---- parsing and dumping the address text ----


def parse_rules(text: str) -> Group | None:
    """Read the address text. None when it is empty, not valid, or over a limit."""
    if not isinstance(text, str) or not text or len(text) > MAX_TEXT:
        return None
    try:
        raw = json.loads(text)
        return _parse_group(raw, 1, [0])
    except (ValueError, RecursionError, _Invalid):
        return None


def _parse_group(raw: object, depth: int, counter: list[int]) -> Group | None:
    """A group dict: its items are parsed, unknown group operators and empty groups are dropped."""
    if depth > MAX_DEPTH or not isinstance(raw, dict):
        raise _Invalid()
    items_raw = raw.get("items")
    if not isinstance(items_raw, list):
        raise _Invalid()
    items = [node for node in (_parse_item(i, depth, counter) for i in items_raw) if node is not None]
    if raw.get("op") not in GROUP_OPS or not items:
        return None
    return Group(op=raw["op"], items=tuple(items))


def _parse_item(raw: object, depth: int, counter: list[int]) -> Rule | Group | None:
    """One item of a group: a nested group when it has `items`, otherwise a rule."""
    if not isinstance(raw, dict):
        raise _Invalid()
    if "items" in raw:
        return _parse_group(raw, depth + 1, counter)
    return _parse_rule(raw, counter)


def _parse_rule(raw: dict[str, Any], counter: list[int]) -> Rule | None:
    """One rule dict {"c", "o", "v"}. Over a limit refuses the tree; a bad value or unknown operator drops this rule."""
    column, op = raw.get("c"), raw.get("o")
    if not isinstance(column, str) or not isinstance(op, str):
        raise _Invalid()
    counter[0] += 1
    if counter[0] > MAX_RULES:
        raise _Invalid()
    value = _rule_value(raw.get("v", ""), op)
    if not _encodable(column) or (value is not None and not _encodable(value)):
        raise _Invalid()  # a lone surrogate cannot be written as UTF-8 in a link: refuse the whole tree
    if value is None or op not in KNOWN_OPS:
        return None
    if len(value) > MAX_VALUE:
        raise _Invalid()
    return Rule(column=column, op=op, value=value)


def _encodable(text: str) -> bool:
    """True when the text can be written as UTF-8 (a lone surrogate from a JSON escape cannot)."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _rule_value(raw_value: object, op: str) -> str | None:
    """The typed value as text. Numbers become text; other types only fit operators that need no value (else None)."""
    if isinstance(raw_value, str):
        return raw_value
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        return str(raw_value)
    if op in ("empty", "filled"):
        return ""
    return None


def rule_columns(group: Group | None) -> list[str]:
    """Every column a rule in the tree names, in order, with repeats."""
    if group is None:
        return []
    keys: list[str] = []
    for node in group.items:
        if isinstance(node, Rule):
            keys.append(node.column)
        else:
            keys.extend(rule_columns(node))
    return keys


def dump_rules(group: Group | None) -> str:
    """The compact JSON text of a tree, read back by parse_rules. Empty text for None."""
    if group is None:
        return ""
    return json.dumps(_to_dict(group), ensure_ascii=False, separators=(",", ":"))


def _to_dict(node: Rule | Group) -> dict[str, Any]:
    """Short keys: a rule is {"c", "o", "v"}, a group is {"op", "items"}."""
    if isinstance(node, Rule):
        return {"c": node.column, "o": node.op, "v": node.value}
    return {"op": node.op, "items": [_to_dict(item) for item in node.items]}


# ---- permissions ----


def restrict(group: Group | None, allowed: set[str]) -> Group | None:
    """Keep only rules on the allowed columns; groups left empty are removed."""
    if group is None:
        return None
    items = _restrict_items(group.items, allowed)
    return Group(op=group.op, items=items) if items else None


def _restrict_items(items: tuple[Rule | Group, ...], allowed: set[str]) -> tuple[Rule | Group, ...]:
    kept: list[Rule | Group] = []
    for node in items:
        if isinstance(node, Rule):
            if node.column in allowed:
                kept.append(node)
        else:
            sub = restrict(node, allowed)
            if sub is not None:
                kept.append(sub)
    return tuple(kept)


# ---- checking one rule against one cell ----


def test_rule(rule: Rule, value: object, kind: str, today: date) -> bool | None:
    """Does the cell value pass the rule? None when the rule cannot be checked (it is then ignored).

    A blank cell is judged by the operator alone, whatever the column's kind: a column with no values at all is
    inferred as text, and a date rule must still not match everyone there.
    """
    if rule.op not in KNOWN_OPS:
        return None
    if _is_blank(value) or (isinstance(value, str) and not value.strip()):
        # the typed value must still read as a kind the operator belongs to, else the rule is inactive as before
        if any(_value_readable(rule, k) for k in OPS if rule.op in OPS[k]):
            return _blank_result(rule.op)
        return None
    if kind not in OPS or rule.op not in OPS[kind]:
        return None
    if not _value_readable(rule, kind):
        return None
    cell = _READERS[kind](value)
    if cell is None:
        return None
    if rule.op == "empty":
        return False
    if rule.op == "filled":
        return True
    return _CHECKERS[kind](rule, cell, today)


def _value_readable(rule: Rule, kind: str) -> bool:
    """The typed value must read as the kind (e.g. a number for «gt»), else the rule is inactive."""
    if kind == "text" or rule.op in ("empty", "filled"):
        return True
    if rule.op == "between":
        return _bounds(rule.value, _READERS[kind]) is not None
    if rule.op in ("next_days", "last_days"):
        return _to_days(rule.value) is not None
    return _READERS[kind](rule.value) is not None


def _is_blank(value: object) -> bool:
    return value is None or value == ""


def _blank_result(op: str) -> bool:
    """A blank cell: only «empty» is true for it, and «neq» and «not_contains» are true too."""
    if op == "empty":
        return True
    if op == "filled":
        return False
    return op in BLANK_MATCHES


def _read_text(value: object) -> str:
    return str(value).casefold()


def _to_decimal(value: object) -> Decimal | None:
    """A number from a number or a plain numeric text (no spaces, no underscores); None when it cannot be read."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, (int, float)):
        number = Decimal(str(value))
    elif isinstance(value, str) and _NUMBER_TEXT.fullmatch(value):
        number = Decimal(value)
    else:
        return None
    return number if number.is_finite() else None


def _to_date(value: object) -> date | None:
    """A date from a date, a datetime or a YYYY-MM-DD text; None when it cannot be read."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _to_days(value: str) -> int | None:
    """A plain whole number of days from 0 to MAX_DAYS; None for negatives, signs, spaces or anything larger."""
    if not _DAY_COUNT.fullmatch(value):
        return None
    days = int(value)
    return days if days <= MAX_DAYS else None


def _bounds(value: str, parse: Callable[[object], Any]) -> tuple[Any, Any] | None:
    """Read «a..b» into an ordered pair. «a..» and «..b» leave one side open (None).
    A side that does not read makes the whole pair None."""
    parts = value.split("..")
    if len(parts) != 2 or parts == ["", ""]:
        return None
    low = parse(parts[0]) if parts[0] else None
    high = parse(parts[1]) if parts[1] else None
    if (parts[0] and low is None) or (parts[1] and high is None):
        return None
    if low is not None and high is not None and low > high:
        return high, low
    return low, high


def _in_bounds(cell: Any, bounds: tuple[Any, Any]) -> bool:
    """True when the cell is inside the pair; an open side (None) does not limit it."""
    low, high = bounds
    return (low is None or low <= cell) and (high is None or cell <= high)


def _text_op(rule: Rule, cell: str, today: date) -> bool | None:
    needle = rule.value.casefold()
    checks = {
        "contains": needle in cell,
        "not_contains": needle not in cell,
        "eq": cell == needle,
        "neq": cell != needle,
        "starts": cell.startswith(needle),
    }
    return checks.get(rule.op)


def _number_op(rule: Rule, cell: Decimal, today: date) -> bool | None:
    if rule.op == "between":
        bounds = _bounds(rule.value, _to_decimal)
        return None if bounds is None else _in_bounds(cell, bounds)
    target = _to_decimal(rule.value)
    if target is None:
        return None
    checks = {
        "eq": cell == target,
        "neq": cell != target,
        "gt": cell > target,
        "gte": cell >= target,
        "lt": cell < target,
        "lte": cell <= target,
    }
    return checks.get(rule.op)


def _date_op(rule: Rule, cell: date, today: date) -> bool | None:
    if rule.op == "between":
        bounds = _bounds(rule.value, _to_date)
        return None if bounds is None else _in_bounds(cell, bounds)
    if rule.op in ("next_days", "last_days"):
        return _relative_day_op(rule, cell, today)
    target = _to_date(rule.value)
    if target is None:
        return None
    checks = {"on": cell == target, "before": cell < target, "after": cell > target}
    return checks.get(rule.op)


def _relative_day_op(rule: Rule, cell: date, today: date) -> bool | None:
    """«next_days»: today to today+N. «last_days»: today-N to today. Both inclusive."""
    days = _to_days(rule.value)
    if days is None:
        return None
    if rule.op == "next_days":
        return today <= cell <= today + timedelta(days=days)
    return today - timedelta(days=days) <= cell <= today


_READERS: dict[str, Callable[[object], Any]] = {
    "text": _read_text,
    "number": _to_decimal,
    "date": _to_date,
}

_CHECKERS: dict[str, Callable[[Rule, Any, date], bool | None]] = {
    "text": _text_op,
    "number": _number_op,
    "date": _date_op,
}


# ---- evaluating the tree over rows ----


def keep_rows(
    rows: Sequence[Any],
    group: Group | None,
    columns: "dict[str, Column]",
    kinds: dict[str, str],
    today: date,
) -> list[Any]:
    """The rows that pass the tree. A rule on a column not loaded, or a cell that cannot be read, is ignored."""
    if group is None:
        return list(rows)
    return [row for row in rows if _passes(group, row, columns, kinds, today) is not False]


def _passes(
    node: Rule | Group,
    row: Any,
    columns: "dict[str, Column]",
    kinds: dict[str, str],
    today: date,
) -> bool | None:
    """True, False, or None when nothing in this node could be checked (then it is ignored)."""
    if isinstance(node, Rule):
        return _rule_on_row(node, row, columns, kinds, today)
    results = [_passes(item, row, columns, kinds, today) for item in node.items]
    active = [result for result in results if result is not None]
    if not active:
        return None
    return all(active) if node.op == "and" else any(active)


def _rule_on_row(
    rule: Rule,
    row: Any,
    columns: "dict[str, Column]",
    kinds: dict[str, str],
    today: date,
) -> bool | None:
    column = columns.get(rule.column)
    if column is None:
        return None
    return test_rule(rule, column.value(row), kinds.get(rule.column, "text"), today)


# ---- wording for the screen and the print ----


def describe_rules(group: Group | None, labels: dict[str, str]) -> str:
    """The tree in words, e.g. «Нас ≥ 30 ба Хэлтэс агуулсан борлуулалт». Nested groups in brackets."""
    if group is None:
        return ""
    return _describe_group(group, labels)


def _describe_group(group: Group, labels: dict[str, str]) -> str:
    joiner = " ба " if group.op == "and" else " эсвэл "
    parts = []
    for node in group.items:
        if isinstance(node, Rule):
            parts.append(_describe_rule(node, labels))
        else:
            parts.append("(" + _describe_group(node, labels) + ")")
    return joiner.join(part for part in parts if part)


def _describe_rule(rule: Rule, labels: dict[str, str]) -> str:
    """«<column> <operator> <value>». A label with «…» takes the value in its place."""
    name = labels.get(rule.column, rule.column)
    label = OP_LABELS.get(rule.op, rule.op)
    if "…" in label:
        return " ".join(f"{name} {label.replace('…', rule.value)}".split())
    return " ".join(part for part in (name, label, rule.value) if part)
