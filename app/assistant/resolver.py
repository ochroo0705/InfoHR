"""Value resolver: the real rows a phrase the user typed for a list filter can mean (a department, a branch, a
position or a code list such as the bank). Plain Python over the rows `values_list` returns; no database search
features.

A phrase names a row when `matching.covers` says every phrase word starts a word of the row's name (case endings and
ө/ү folded, generic words such as «хэлтэс» never stop a match). Rules: a phrase that is only generic words names
nothing; one row whose name equals the phrase (generic words kept) wins; otherwise one matching row is the answer;
several matching rows are returned ranked (fewer extra name words first, then by name), at most MAX_CANDIDATES.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from django.db import models
from employees.palette import _fold
from macs.models import Branch, Department, Position
from reports.column_filters import COLUMN_FILTERS

from assistant.matching import covers, only_generic, word_forms

MAX_CANDIDATES = 15

_WORD = re.compile(r"[^\W\d_]+")  # a run of letters, as in matching.py

# The filter parameter → the model its values are rows of: the three named lists and every code-list column filter.
LOOKUPS: dict[str, type[models.Model]] = {
    "department": Department,
    "branch": Branch,
    "position": Position,
    **{cf.name: cf.model for cf in COLUMN_FILTERS.values() if cf.kind == "code" and cf.model is not None},
}

# A lookup that is one kind of its model: the clothing and shoe sizes share ClothesSize, split by size_type.
LOOKUP_WHERE: dict[str, dict[str, str]] = {
    "clothing_size": {"size_type": "clothes"},
    "shoe_size": {"size_type": "shoes"},
}


@dataclass(frozen=True)
class Candidate:
    id: int
    name: str


@dataclass(frozen=True)
class Resolution:
    status: str  # "one" | "several" | "none"
    candidates: tuple[Candidate, ...]  # ranked, at most MAX_CANDIDATES; for "one" exactly one


_NONE = Resolution(status="none", candidates=())


def _words(text: str) -> tuple[str, ...]:
    """The folded letter-words of a text, in order."""
    return tuple(_WORD.findall(_fold(text)))


def _key(text: str) -> str:
    """The folded text with its spaces collapsed: what an exact name is compared by. Digits and short names count."""
    return " ".join(_fold(text).split())


def _rows(param: str) -> list[tuple[int, str]]:
    """Every (id, name) of the filter's lookup, the kind limit applied, rows without a name left out."""
    model = LOOKUPS[param]
    values = model._default_manager.filter(**LOOKUP_WHERE.get(param, {})).values_list("pk", "name")
    return [(int(pk), str(name)) for pk, name in values if name]


def _result(rows: list[tuple[int, str]], status_if_many: str) -> Resolution:
    """One row is "one"; several are "several" in the order given, at most MAX_CANDIDATES."""
    if len(rows) == 1:
        return Resolution(status="one", candidates=(Candidate(id=rows[0][0], name=rows[0][1]),))
    shown = tuple(Candidate(id=pk, name=name) for pk, name in rows[:MAX_CANDIDATES])
    return Resolution(status=status_if_many, candidates=shown)


def resolve(param: str, phrase: str) -> Resolution:
    """The rows of the filter's lookup that the phrase can mean. Raises KeyError for a parameter with no lookup.

    Order: an exact name (whole, folded, digits and short names included) wins first; then a phrase of only generic
    words names nothing; then every row whose name the phrase covers (one, or several ranked)."""
    return _resolve_rows(_rows(param), phrase)


def _resolve_rows(rows: list[tuple[int, str]], phrase: str) -> Resolution:
    """resolve() over rows already loaded, so several phrases can share one load."""
    key = _key(phrase)
    if not key:
        return _NONE
    exact = sorted((row for row in rows if _key(row[1]) == key), key=lambda row: (row[1], row[0]))
    if exact:
        return _result(exact, "several")
    if only_generic(phrase):
        return _NONE
    phrase_forms = word_forms(phrase)
    matched = [row for row in rows if covers(phrase_forms, row[1])]
    if not matched:
        return _NONE
    phrase_count = len(_words(phrase))
    ranked = sorted(matched, key=lambda row: (len(_words(row[1])) - phrase_count, row[1], row[0]))
    return _result(ranked, "several")


def candidate_names(param: str, phrase: str) -> list[str]:
    """The names of the candidates, for the prompt: at most MAX_CANDIDATES."""
    return [candidate.name for candidate in resolve(param, phrase).candidates]


def candidate_names_many(param: str, phrases: Sequence[str]) -> list[str]:
    """The candidate names of several phrases, in order without repeats, at most MAX_CANDIDATES. The lookup's rows are
    loaded once for all the phrases."""
    if not phrases:
        return []
    rows = _rows(param)
    names: list[str] = []
    for phrase in phrases:
        for candidate in _resolve_rows(rows, phrase).candidates:
            if candidate.name not in names:
                names.append(candidate.name)
    return names[:MAX_CANDIDATES]
