"""Word matching for the assistant's questions, in plain Python (no database search features).

A question's words are compared with a name or a help entry's words by their folded forms (`people.name_forms`: the
folded word plus its case-ending-stripped stems). A phrase word matches a name word when one of its forms of at least
MIN_PREFIX letters is the start of a form of the name word, so «санхүү» matches «Санхүүгийн». Generic words of
organisation («хэлтэс», «алба», «салбар» ...) name no one and are left out, so they never stop a match.
"""

import re
from collections.abc import Sequence

from employees.palette import _fold

from assistant.entry import HelpEntry
from assistant.people import name_forms

MIN_PREFIX = 3  # a phrase form shorter than this matches nothing

# Folded stems that name the kind of unit, not the unit: «хэлтэс», «хэлтсийн», «албаны», «газрын», «салбарын» ...
GENERIC_WORDS: frozenset[str] = frozenset({"хэлтс", "хэлтэс", "алба", "газар", "газр", "салбар", "тасаг", "тасг"})

# The endings the generic check takes off (two or more letters; «албан» must not turn into «алба»). «албаны» is
# «алба» + «ны»; «газрын», «хэлтсийн» are the stems + «ын», «ийн».
_GENERIC_ENDINGS: tuple[str, ...] = ("ийн", "ийг", "ын", "ыг", "ны")

# Genitive and accusative after a vowel stem («санхүү» + «гийн»). `people.CASE_ENDINGS` does not have them, so the
# stems are added here for the phrase forms only.
_GENITIVE_ENDINGS: tuple[str, ...] = ("гийн", "гийг")

_WORD = re.compile(r"[^\W\d_]+")  # a run of letters, as in people.py


def _is_generic(folded: str) -> bool:
    """A word is generic when it, or it minus one of _GENERIC_ENDINGS, is a generic stem."""
    if folded in GENERIC_WORDS:
        return True
    return any(folded.endswith(e) and folded[: -len(e)] in GENERIC_WORDS for e in _GENERIC_ENDINGS)


def _genitive_stems(folded: str) -> set[str]:
    """The word minus a genitive ending, from MIN_PREFIX letters («санхүүгийн» gives «санхуу»)."""
    return {folded[: -len(e)] for e in _GENITIVE_ENDINGS if folded.endswith(e) and len(folded) - len(e) >= MIN_PREFIX}


def _all_word_forms(text: str) -> list[set[str]]:
    """One set of forms per word of the text, generic words included (a name may hold «Газрын» as a surname)."""
    return [name_forms(word) | _genitive_stems(word) for word in _WORD.findall(_fold(text))]


def word_forms(text: str) -> list[set[str]]:
    """One set of forms per word of the text (letters only, folded, case endings stripped), generic words left out.
    A text made only of generic words keeps them, so «Газрын» on its own is still a phrase."""
    words = _WORD.findall(_fold(text))
    kept = [word for word in words if not _is_generic(word)] or words
    return [name_forms(word) | _genitive_stems(word) for word in kept]


def only_generic(text: str) -> bool:
    """True when every letter-word of the text is a generic word, or the text has no words (it names no unit)."""
    return all(_is_generic(word) for word in _WORD.findall(_fold(text)))


def _matches(phrase: set[str], word: set[str]) -> bool:
    """True when a form of the phrase word, at least MIN_PREFIX letters, starts a form of the other word."""
    return any(len(p) >= MIN_PREFIX and any(f.startswith(p) for f in word) for p in phrase)


def covers(phrase_forms: list[set[str]], name: str) -> bool:
    """True when every phrase word matches some word of the name. The name is compared whole, generic words included.
    An empty phrase names nothing, so it is never covered."""
    if not phrase_forms:
        return False
    name_words = _all_word_forms(name)
    return all(any(_matches(phrase, word) for word in name_words) for phrase in phrase_forms)


def _entry_forms(entry: HelpEntry) -> list[set[str]]:
    text = " ".join((entry.title, *entry.words, *entry.examples, *entry.learned))
    return word_forms(text)


def narrow_entries(question: str, entries: Sequence[HelpEntry], limit: int = 15) -> list[HelpEntry]:
    """The entries sharing a word with the question, best first, at most `limit`. Each question word counts for
    1 / (number of entries it is shared with), so a rare word («амралт») outranks a common one («бүртгэх»); ties keep
    the original order. When there are `limit` entries or fewer, or no entry shares a word, all entries are returned
    unchanged. If more than `limit` entries share words, the lowest-ranked are cut."""
    if len(entries) <= limit:
        return list(entries)
    question_words = word_forms(question)
    hits = [
        [j for j, phrase in enumerate(question_words) if any(_matches(phrase, word) for word in _entry_forms(entry))]
        for entry in entries
    ]
    shared = [0] * len(question_words)
    for entry_hits in hits:
        for j in entry_hits:
            shared[j] += 1
    scored = [
        (-sum(1 / shared[j] for j in entry_hits), index, entries[index])
        for index, entry_hits in enumerate(hits)
        if entry_hits
    ]
    if not scored:
        return list(entries)
    scored.sort(key=lambda item: (item[0], item[1]))
    return [entry for _, _, entry in scored[:limit]]
