"""Rules for the learning loop: what a correction may be saved as, and which words look like employee names."""

import difflib
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qsl, urlencode

from django.conf import settings
from django.http import QueryDict
from django.utils import timezone
from employees.palette import _fold
from macs.models import Employee
from reports.filters import parse_filters, to_query

from assistant.entries import ENTRIES, ENTRY_BY_KEY
from assistant.evalcheck import expected_pairs
from assistant.evalset import CASES
from assistant.models import HelpExample, Kind
from assistant.resolver import LOOKUPS

NO_ENTRY = "Энэ хариулт байхгүй болсон байна."
DUPLICATE = "Энэ асуулт аль хэдийн бүртгэгдсэн байна."
TOO_CLOSE_TO_EXAMPLE = "Энэ асуулт жишээтэй хэт ойролцоо байна: тест болгож болохгүй."
TOO_CLOSE_TO_TEST = "Энэ асуулт тесттэй хэт ойролцоо байна."
ENTRY_AND_FILTER = "Хариулт ба хүлээгдэх шүүлтүүр хоёрыг хамт оруулж болохгүй."
FILTER_BRACES = "Шүүлтүүрт { } тэмдэг бичиж болохгүй."
BAD_FILTER = "Шүүлтүүр буруу байна: «{}» нь хүснэгтийн шүүлтүүр биш эсвэл утга буруу байна."
NAME_NOT_LOOKUP = "Нэрээр бичих боломжгүй шүүлтүүр: «{}»."

_WORD_SPLIT = re.compile(r'[\s,.!?;:«»"()]+')


def fold(text: str) -> str:
    """Folded text for every comparison: see `employees.palette._fold`, with the ends trimmed."""
    return _fold(text).strip()


def similar(a: str, b: str) -> bool:
    """True when the two texts are at least `ASSISTANT_SIMILARITY` alike after folding. Read at call time."""
    return bool(difflib.SequenceMatcher(None, fold(a), fold(b)).ratio() >= settings.ASSISTANT_SIMILARITY)


def expected_problems(expected: str) -> list[str]:
    """Problems with a filter query typed in the admin. It must read the way the staff table reads a query: a plain
    pair (`department=5`) must survive the parse, and `param~Name` is allowed only for a lookup (the eval resolves the
    name when it runs). Placeholders are not allowed here. An empty list means it is valid."""
    if not expected:
        return []
    if "{" in expected or "}" in expected:
        return [FILTER_BRACES]
    try:
        pairs = expected_pairs(expected, timezone.localdate())
    except ValueError:
        return [BAD_FILTER.format(expected)]
    plain: list[tuple[str, str]] = []
    for param, value, by_name in pairs:
        if not by_name:
            plain.append((param, value))
        elif param not in LOOKUPS:
            return [NAME_NOT_LOOKUP.format(param)]
        elif not value.strip():
            return [BAD_FILTER.format(f"{param}~")]
    kept = set(parse_qsl(to_query(parse_filters(QueryDict(urlencode(plain)))), keep_blank_values=True))
    for param, value in plain:
        # state=working is the one default that to_query leaves out, so it is written on purpose.
        if (param, value) not in kept and (param, value) != ("state", "working"):
            return [BAD_FILTER.format(f"{param}={value}")]
    return []


def check(
    question: str, entry: str, kind: str, active: bool, exclude_pk: int | None = None, expected: str = ""
) -> list[str]:
    """Problems that stop a correction from being saved or switched on. An empty list means it is valid.

    `exclude_pk` is the row being checked, so it is not compared with itself. Inactive rows are not checked
    at all: they may hold anything (switching `active` off is the undo). A row with `expected` is a filter sentence:
    it must have no entry, and its filter query must be valid.
    """
    if not active:
        return []
    if entry and expected:
        return [ENTRY_AND_FILTER]
    if entry and entry not in ENTRY_BY_KEY:
        return [NO_ENTRY]
    problems = expected_problems(expected)
    if problems:
        return problems

    others = HelpExample.objects.filter(active=True)
    if exclude_pk is not None:
        others = others.exclude(pk=exclude_pk)

    folded = fold(question)
    if any(fold(text) == folded for text in others.values_list("question", flat=True)):
        return [DUPLICATE]

    if kind == Kind.TEST:
        shipped = [example for item in ENTRIES for example in item.examples]
        local = list(others.filter(kind=Kind.EXAMPLE).values_list("question", flat=True))
        if any(similar(question, text) for text in shipped + local):
            return [TOO_CLOSE_TO_EXAMPLE]

    if kind == Kind.EXAMPLE:
        cases = [case.question for case in CASES]
        local = list(others.filter(kind=Kind.TEST).values_list("question", flat=True))
        if any(similar(question, text) for text in cases + local):
            return [TOO_CLOSE_TO_TEST]

    return []


def employee_names() -> set[str]:
    """Folded given and family names of every employee, short ones (under 3 letters) left out."""
    names: set[str] = set()
    for given, family in Employee.objects.values_list("given_name", "family_name"):
        for name in (given, family):
            folded = fold(name or "")
            if len(folded) >= 3:
                names.add(folded)
    return names


def name_hits(text: str, names: set[str] | None = None) -> list[str]:
    """Words of `text` that are an employee name, in their original spelling, first occurrence only."""
    if names is None:
        names = employee_names()
    hits: list[str] = []
    seen: set[str] = set()
    for word in _WORD_SPLIT.split(text):
        folded = fold(word)
        if word and folded in names and folded not in seen:
            seen.add(folded)
            hits.append(word)
    return hits


def _chosen() -> tuple[dict[str, list[tuple[int, str]]], list[tuple[int, str]], list[tuple[int, str, str]]]:
    """The learned examples the assistant sees: per entry, the no-entry ones, then the filter sentences. Newest first,
    capped at read time.

    One query. Each item is (id, question); a filter sentence is (id, question, expected). Orphans (entry not in
    `ENTRY_BY_KEY`) and inactive rows are left out. A filter sentence is never a no-entry question or an entry example.
    """
    per_entry_cap = settings.ASSISTANT_EXAMPLES_PER_ENTRY
    no_entry_cap = settings.ASSISTANT_NO_ENTRY_EXAMPLES
    per_entry: dict[str, list[tuple[int, str]]] = {}
    no_entry: list[tuple[int, str]] = []
    table: list[tuple[int, str, str]] = []
    rows = (
        HelpExample.objects.filter(active=True, kind=Kind.EXAMPLE)
        .order_by("-created_at", "-pk")
        .values_list("pk", "entry", "question", "expected")
    )
    for pk, entry, question, expected in rows:
        if expected:
            if len(table) < no_entry_cap:
                table.append((pk, question, expected))
        elif not entry:
            if len(no_entry) < no_entry_cap:
                no_entry.append((pk, question))
        elif entry in ENTRY_BY_KEY:
            bucket = per_entry.setdefault(entry, [])
            if len(bucket) < per_entry_cap:
                bucket.append((pk, question))
    return per_entry, no_entry, table


def learned_by_entry() -> dict[str, tuple[str, ...]]:
    """Per help entry key, the newest `ASSISTANT_EXAMPLES_PER_ENTRY` learned questions (newest first)."""
    per_entry, _, _ = _chosen()
    return {key: tuple(question for _, question in items) for key, items in per_entry.items()}


def no_entry_questions() -> tuple[str, ...]:
    """The newest `ASSISTANT_NO_ENTRY_EXAMPLES` learned questions that no entry answers (newest first)."""
    _, no_entry, _ = _chosen()
    return tuple(question for _, question in no_entry)


def table_examples() -> tuple[tuple[str, str], ...]:
    """The newest `ASSISTANT_NO_ENTRY_EXAMPLES` learned filter sentences as (question, filter query), newest first."""
    _, _, table = _chosen()
    return tuple((question, expected) for _, question, expected in table)


def used_example_ids() -> set[int]:
    """Ids of the rows that `learned_by_entry`, `no_entry_questions` and `table_examples` return. One query."""
    per_entry, no_entry, table = _chosen()
    return (
        {pk for items in per_entry.values() for pk, _ in items}
        | {pk for pk, _ in no_entry}
        | {pk for pk, _, _ in table}
    )


def usage_label(row: HelpExample, used: set[int]) -> str:
    """Short Mongolian label for the corrections list: whether the row is sent to the assistant, and why not."""
    if row.entry and row.entry not in ENTRY_BY_KEY:
        return "Энэ хариулт байхгүй болсон"
    if not row.active:
        return "Идэвхгүй"
    if row.kind == Kind.TEST:
        return "Тест"
    if row.pk in used:
        return "Хүснэгтэд ашиглагдаж байна" if row.expected else "Ашиглагдаж байна"
    return "Хязгаараас хэтэрсэн"


def local_tests() -> list[HelpExample]:
    """Active tests whose entry exists or is blank, oldest first. Filter sentences are left out (see
    `local_table_tests`)."""
    rows = HelpExample.objects.filter(active=True, kind=Kind.TEST, expected="").order_by("created_at", "pk")
    return [row for row in rows if not row.entry or row.entry in ENTRY_BY_KEY]


def local_table_tests() -> list[HelpExample]:
    """Active tests that are filter sentences (with `expected` and no entry), oldest first."""
    rows = (
        HelpExample.objects.filter(active=True, kind=Kind.TEST, entry="")
        .exclude(expected="")
        .order_by("created_at", "pk")
    )
    return list(rows)


def export_payload(rows: Iterable[HelpExample]) -> dict[str, Any]:
    """The corrections as a file for review: active rows whose entry exists or is blank. No user, no ids."""
    examples: list[dict[str, str]] = []
    tests: list[dict[str, str]] = []
    for row in rows:
        if not row.active or (row.entry and row.entry not in ENTRY_BY_KEY):
            continue
        item = {"question": row.question, "entry": row.entry, "expected": row.expected}
        if row.kind == Kind.TEST:
            tests.append(item)
        else:
            examples.append(item)
    return {"exported_at": timezone.localtime().isoformat(), "examples": examples, "tests": tests}
