"""Approved verified queries as examples for the SQL model, and the drift check that finds the ones a view change broke.

Only a row with status approved is ever used. An example reaches the model only when every view it uses is in the
asker's own catalogue, so a salary example never reaches a user without the salary views. Plain Python on top of the
ORM and sqlcore; no Firebird connection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hr_sql.catalogue import RESERVED_PREFIXES
from hr_sql.descriptions import load_all
from sqlcore.catalogue import Catalogue
from sqlcore.check import CheckError, check_sql

from assistant.learning import fold
from assistant.models import VerifiedQuery, VerifiedStatus

EXAMPLE_LIMIT = 5

_WORD_SPLIT = re.compile(r"[^\w]+")  # Mongolian Cyrillic letters are word characters


@dataclass(frozen=True)
class StaleExample:
    pk: int
    question: str
    problem: str  # the checker's message, for the admin


def _words(text: str) -> frozenset[str]:
    """The folded words of a text. Folding is the one the learning loop uses for every comparison."""
    return frozenset(word for word in _WORD_SPLIT.split(fold(text)) if word)


def _views_of(row: VerifiedQuery) -> frozenset[str]:
    return frozenset(name.strip().upper() for name in row.views.split(",") if name.strip())


def examples_for(catalogue: Catalogue, question: str, limit: int = EXAMPLE_LIMIT) -> tuple[tuple[str, str], ...]:
    """The approved (question, SQL) pairs that may answer this question for this asker.

    An approved row qualifies when it uses at least one view and ALL its views are in the asker's catalogue, and when
    it shares at least one folded word with the question. Ranked by the number of shared words, most first; on a tie,
    the newest row first. At most `limit` pairs.
    """
    question_words = _words(question)
    if not question_words:
        return ()
    allowed = catalogue.view_names()
    rows = VerifiedQuery.objects.filter(status=VerifiedStatus.APPROVED).order_by("-created_at", "-pk")
    ranked: list[tuple[int, int, VerifiedQuery]] = []
    for position, row in enumerate(rows):
        views = _views_of(row)
        if not views or not views <= allowed:
            continue
        shared = len(question_words & _words(row.question))
        if shared:
            ranked.append((shared, position, row))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple((row.question, row.sql) for _, _, row in ranked[:limit])


def full_catalogue() -> Catalogue:
    """Every governed view with its reviewed description: the reference the drift check uses."""
    return Catalogue(views=tuple(load_all().values()), reserved_prefixes=RESERVED_PREFIXES)


def stale_examples() -> list[StaleExample]:
    """Approved rows whose SQL no longer passes the checker against the full catalogue (a view or column changed)."""
    catalogue = full_catalogue()
    stale: list[StaleExample] = []
    for row in VerifiedQuery.objects.filter(status=VerifiedStatus.APPROVED).order_by("pk"):
        try:
            check_sql(row.sql, catalogue)
        except CheckError as error:
            stale.append(StaleExample(pk=row.pk, question=row.question, problem=str(error)))
    return stale
