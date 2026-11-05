"""Named people in a help question: the employees the question names, among the people the Ctrl+K search finds.

A word of the question names a person when, folded (`_fold`), it equals the person's given or family name, or that
name with a Mongolian case ending taken off («Номины», «Номинд», «Номинтой» name Номин; «батлах» does not name Бат).
Only the people `find_people` searches are looked at (`access.visible_employees` with an HR row), so a person outside
the asker's data scope is no match. Nothing is stored here: the matched people are not written to the question log.
"""

import re
from datetime import date

from accounts.models import User
from django.db.models import F, Q
from employees import access
from employees.listing import employee_rows
from employees.palette import QUERY_LIMIT, PersonHit, _fold, _person_hits, _sql_fold

PEOPLE_SHOWN = 5  # people listed in the answer; one more is read so the card can say there are more
MIN_NAME = 3  # a name shorter than this never matches (a stem of a word is kept only from this length)

# Mongolian case endings, folded (ө→о, ү→у), longest first.
CASE_ENDINGS: tuple[str, ...] = (
    "ийг",
    "ийн",
    "аас",
    "ээс",
    "оос",
    "тай",
    "тэй",
    "той",
    "руу",
    "луу",
    "аар",
    "ээр",
    "оор",
    "ын",
    "ий",
    "ыг",
    "ад",
    "ид",
    "од",
    "ы",
    "н",
    "д",
    "т",
    "г",
)

_WORD = re.compile(r"[^\W\d_]+")  # a run of letters: punctuation and digits separate words


def name_forms(word: str) -> set[str]:
    """The folded word itself, and the word minus each case ending it ends with. A stem is kept only from MIN_NAME
    letters, so a short stem never names anyone."""
    folded = _fold(word)
    forms = {folded}
    for ending in CASE_ENDINGS:
        if folded.endswith(ending):
            stem = folded[: -len(ending)]
            if len(stem) >= MIN_NAME:
                forms.add(stem)
    return forms


def _forms(text: str) -> list[str]:
    """Every candidate name in the text, folded and sorted (sorted so the SQL is the same every time)."""
    forms: set[str] = set()
    for word in _WORD.findall(_fold(text[:QUERY_LIMIT])):
        forms |= name_forms(word)
    return sorted(form for form in forms if len(form) >= MIN_NAME)


def match_people(user: User, text: str, today: date) -> list[PersonHit]:
    """The people the question names, at most PEOPLE_SHOWN + 1, in family name, given name, pk order.

    One query finds the names; when some person matches on both the family and the given name, only those people are
    kept (two words narrow the result). Rows are built only for the people returned, as the Ctrl+K search does.
    """
    if not user.is_active:
        return []
    forms = _forms(text)
    if not forms:
        return []
    base = (
        access.visible_employees(user)
        .filter(ext__isnull=False)
        .alias(
            f_family=_sql_fold(F("family_name")),
            f_given=_sql_fold(F("given_name")),
        )
    )
    named = base.filter(Q(f_given__in=forms) | Q(f_family__in=forms))
    both = named.filter(f_given__in=forms, f_family__in=forms)
    pool = both if both.exists() else named
    shown = list(pool.order_by("family_name", "given_name", "pk").values_list("pk", flat=True)[: PEOPLE_SHOWN + 1])
    if not shown:
        return []
    rows = employee_rows(base.filter(pk__in=shown).order_by("family_name", "given_name", "pk"), today)
    hits = _person_hits(rows)
    return [hits[pk] for pk in shown if pk in hits]
