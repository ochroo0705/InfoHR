"""Click-through from a layout to the table: the rules that keep one category's rows."""

import re
from calendar import monthrange
from collections.abc import Iterable
from datetime import date

from reports import rules as rules_mod

_OP_BY_KIND = {"text": "eq", "number": "eq", "date": "on"}
# the text of a date bucket for each grain (layouts.date_bucket): 2026-03, 2026-Q1, 2026
_BUCKET_PATTERN = {
    "month": re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])"),
    "quarter": re.compile(r"([0-9]{4})-Q([1-4])"),
    "year": re.compile(r"([0-9]{4})"),
}


def bucket_condition(column_key: str, grain: str, key: str) -> rules_mod.Rule | None:
    """The «between» rule that keeps the rows of one date bucket: from its first day to its last, both inclusive
    («2026-03» is 2026-03-01..2026-03-31). A blank key is the «—» bucket and gives the «empty» rule. None when the
    grain is unknown or the key is not a bucket of that grain (a folded «Бусад» has no key: the caller passes none)."""
    pattern = _BUCKET_PATTERN.get(grain)
    if pattern is None:
        return None
    if key.strip() == "":
        return rules_mod.Rule(column=column_key, op="empty", value="")
    match = pattern.fullmatch(key)
    if match is None:
        return None
    year = int(match.group(1))
    if grain == "year":
        first_month, last_month = 1, 12
    elif grain == "quarter":
        first_month = (int(match.group(2)) - 1) * 3 + 1
        last_month = first_month + 2
    else:
        first_month = last_month = int(match.group(2))
    try:
        first = date(year, first_month, 1)
        last = date(year, last_month, monthrange(year, last_month)[1])
    except ValueError:  # year 0000 is not a calendar year
        return None
    return rules_mod.Rule(column=column_key, op="between", value=f"{first.isoformat()}..{last.isoformat()}")


def condition(column_key: str, kind: str, key: str) -> rules_mod.Rule | None:
    """The rule that keeps the rows whose category text is `key` (as layouts._key gives it). A blank key is the
    «—» bucket: the rule is «empty». None when the kind is unknown, the text is too long for a rule value, or the
    rule engine cannot read the text for the kind (such a rule would keep every row)."""
    op = _OP_BY_KIND.get(kind)
    if op is None:
        return None
    if key.strip() == "":
        return rules_mod.Rule(column=column_key, op="empty", value="")
    if len(key) > rules_mod.MAX_VALUE or not rules_mod.check_value(op, key, kind):
        return None
    return rules_mod.Rule(column=column_key, op=op, value=key)


def collisions(keys: Iterable[str | None]) -> set[str]:
    """The keys whose rule would also keep another bucket's rows: two distinct keys that read the same once
    stripped and case-folded (so "a"/"A", and ""/"   "). The caller draws no link for these. None (the folded
    «Бусад») is ignored."""
    distinct = {k for k in keys if k is not None}
    by_fold: dict[str, list[str]] = {}
    for key in distinct:
        by_fold.setdefault(key.strip().casefold(), []).append(key)
    return {key for group in by_fold.values() if len(group) > 1 for key in group}


def drill_rules(existing: str, conditions: list[rules_mod.Rule]) -> str:
    """The `rules` address text for the existing rules AND every condition. "" when there is no condition, or when
    the result would not read back (too deep, too many rules, too long): the caller then draws no link."""
    if not conditions:
        return ""
    tree = rules_mod.parse_rules(existing)
    if tree is None:
        combined = rules_mod.Group(op="and", items=tuple(conditions))
    elif tree.op == "and":
        combined = rules_mod.Group(op="and", items=(*tree.items, *conditions))
    else:  # an OR tree must stay whole: it is one item of an AND group
        combined = rules_mod.Group(op="and", items=(tree, *conditions))
    text = rules_mod.dump_rules(combined)
    readback = rules_mod.parse_rules(text)
    if readback is None or rules_mod.dump_rules(readback) != text:
        return ""
    return text
