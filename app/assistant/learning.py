"""Rules for the learning loop: what a correction may be saved as, and which words look like employee names."""

import difflib
import re
from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.utils import timezone
from employees.palette import _fold
from macs.models import Employee

from assistant.entries import ENTRIES, ENTRY_BY_KEY
from assistant.evalset import CASES
from assistant.models import HelpExample, Kind

NO_ENTRY = "Энэ хариулт байхгүй болсон байна."
DUPLICATE = "Энэ асуулт аль хэдийн бүртгэгдсэн байна."
TOO_CLOSE_TO_EXAMPLE = "Энэ асуулт жишээтэй хэт ойролцоо байна: тест болгож болохгүй."
TOO_CLOSE_TO_TEST = "Энэ асуулт тесттэй хэт ойролцоо байна."

_WORD_SPLIT = re.compile(r'[\s,.!?;:«»"()]+')


def fold(text: str) -> str:
    """Folded text for every comparison: see `employees.palette._fold`, with the ends trimmed."""
    return _fold(text).strip()


def similar(a: str, b: str) -> bool:
    """True when the two texts are at least `ASSISTANT_SIMILARITY` alike after folding. Read at call time."""
    return bool(difflib.SequenceMatcher(None, fold(a), fold(b)).ratio() >= settings.ASSISTANT_SIMILARITY)


def check(question: str, entry: str, kind: str, active: bool, exclude_pk: int | None = None) -> list[str]:
    """Problems that stop a correction from being saved or switched on. An empty list means it is valid.

    `exclude_pk` is the row being checked, so it is not compared with itself. Inactive rows are not checked
    at all: they may hold anything (switching `active` off is the undo).
    """
    if not active:
        return []
    if entry and entry not in ENTRY_BY_KEY:
        return [NO_ENTRY]

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


def _chosen() -> tuple[dict[str, list[tuple[int, str]]], list[tuple[int, str]]]:
    """The learned examples the assistant sees: per entry, then the no-entry ones. Newest first, capped at read time.

    One query. Each item is (id, question). Orphans (entry not in `ENTRY_BY_KEY`) and inactive rows are left out.
    """
    per_entry_cap = settings.ASSISTANT_EXAMPLES_PER_ENTRY
    no_entry_cap = settings.ASSISTANT_NO_ENTRY_EXAMPLES
    per_entry: dict[str, list[tuple[int, str]]] = {}
    no_entry: list[tuple[int, str]] = []
    rows = (
        HelpExample.objects.filter(active=True, kind=Kind.EXAMPLE)
        .order_by("-created_at", "-pk")
        .values_list("pk", "entry", "question")
    )
    for pk, entry, question in rows:
        if not entry:
            if len(no_entry) < no_entry_cap:
                no_entry.append((pk, question))
        elif entry in ENTRY_BY_KEY:
            bucket = per_entry.setdefault(entry, [])
            if len(bucket) < per_entry_cap:
                bucket.append((pk, question))
    return per_entry, no_entry


def learned_by_entry() -> dict[str, tuple[str, ...]]:
    """Per help entry key, the newest `ASSISTANT_EXAMPLES_PER_ENTRY` learned questions (newest first)."""
    per_entry, _ = _chosen()
    return {key: tuple(question for _, question in items) for key, items in per_entry.items()}


def no_entry_questions() -> tuple[str, ...]:
    """The newest `ASSISTANT_NO_ENTRY_EXAMPLES` learned questions that no entry answers (newest first)."""
    _, no_entry = _chosen()
    return tuple(question for _, question in no_entry)


def used_example_ids() -> set[int]:
    """Ids of the rows that `learned_by_entry` and `no_entry_questions` return. One query."""
    per_entry, no_entry = _chosen()
    return {pk for items in per_entry.values() for pk, _ in items} | {pk for pk, _ in no_entry}


def usage_label(row: HelpExample, used: set[int]) -> str:
    """Short Mongolian label for the corrections list: whether the row is sent to the assistant, and why not."""
    if row.entry and row.entry not in ENTRY_BY_KEY:
        return "Энэ хариулт байхгүй болсон"
    if not row.active:
        return "Идэвхгүй"
    if row.kind == Kind.TEST:
        return "Тест"
    if row.pk in used:
        return "Ашиглагдаж байна"
    return "Хязгаараас хэтэрсэн"


def local_tests() -> list[HelpExample]:
    """Active tests whose entry exists or is blank, oldest first."""
    rows = HelpExample.objects.filter(active=True, kind=Kind.TEST).order_by("created_at", "pk")
    return [row for row in rows if not row.entry or row.entry in ENTRY_BY_KEY]


def export_payload(rows: Iterable[HelpExample]) -> dict[str, Any]:
    """The corrections as a file for review: active rows whose entry exists or is blank. No user, no ids."""
    examples: list[dict[str, str]] = []
    tests: list[dict[str, str]] = []
    for row in rows:
        if not row.active or (row.entry and row.entry not in ENTRY_BY_KEY):
            continue
        item = {"question": row.question, "entry": row.entry}
        if row.kind == Kind.TEST:
            tests.append(item)
        else:
            examples.append(item)
    return {"exported_at": timezone.localtime().isoformat(), "examples": examples, "tests": tests}
