"""The answer service: one question in, one checked answer out, and one log row per question."""

import dataclasses
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from accounts.models import User
from django.db import transaction
from django.utils import timezone
from employees.palette import PersonHit, _fold

from assistant import learning, resolver
from assistant.entries import HelpEntry, allowed_entries
from assistant.matching import narrow_entries, only_generic
from assistant.models import HelpQuestion, Outcome
from assistant.people import match_people
from assistant.plan import Plan
from assistant.providers import Provider, ProviderError
from assistant.tables import MAX_BASE, TableAnswer, can_open_table, table_answer
from assistant.words import FilterWords, offered_words

QUESTION_LIMIT = 300  # characters of a question that are kept and sent
ASK_PER_HOUR = 20  # questions per user in any rolling hour that reach the provider or are answered
LEAD_LIMIT = 200  # characters of the one-sentence lead
PLAN_ENTRIES = 30  # help entries the plan call sees at most: the ones that share a word with the question
MAX_TOKENS = 12  # distinct question words that are looked up in the lookups (a long question cannot multiply the work)

logger = logging.getLogger(__name__)

_COUNTED = (Outcome.ANSWERED, Outcome.NONE, Outcome.ERROR, Outcome.TABLE)
_WORD = re.compile(r"[^\W\d_]+")  # a run of letters, as in matching.py
_QUESTION_WORDS = ("яаж", "хаана", "хаанаас", "хэрхэн", "яах")
_QUESTION_ENDINGS = ("вэ", "бэ")


@dataclass(frozen=True)
class Answer:
    outcome: Outcome
    entry: HelpEntry | None
    also: HelpEntry | None
    lead: str
    people: tuple[PersonHit, ...] = ()  # the people the question names, only for a person-bound entry
    error: str = ""  # why a failed call failed, for the admin log (never shown to the asker)
    tool: str = ""  # the plan's tool ("entry", "staff_table", "none"); "" when no plan was made
    table: TableAnswer | None = None  # the staff table answer, for a TABLE outcome only


def looks_like_question(q: str) -> bool:
    """True when the text reads as a question: ends with ?, ends with вэ/бэ, or starts with a question word."""
    text = _fold(q.strip().rstrip(".!"))
    words = text.split()
    if not words:
        return False
    if text.endswith("?") or words[-1] in _QUESTION_ENDINGS:
        return True
    return words[0] in {_fold(word) for word in _QUESTION_WORDS}


def _recent_count(user: User) -> int:
    since = timezone.now() - timedelta(hours=1)
    return HelpQuestion.objects.filter(user=user, asked_at__gte=since, outcome__in=_COUNTED).count()


def _limited_logged(user: User) -> bool:
    since = timezone.now() - timedelta(hours=1)
    return HelpQuestion.objects.filter(user=user, asked_at__gte=since, outcome=Outcome.LIMITED).exists()


def _log(user: User, question: str, result: Answer, provider: Provider, started: float, allowed: str) -> None:
    HelpQuestion.objects.create(
        user=user,
        question=question,
        entry=result.entry.key if result.entry else "",
        also=result.also.key if result.also else "",
        outcome=result.outcome,
        provider=provider.name,
        model=provider.model,
        duration_ms=int((time.monotonic() - started) * 1000),
        allowed=allowed,
        error=result.error[:300],
        tool=result.tool,
        query=result.table.query[:300] if result.table is not None else "",
        not_applied=" | ".join(result.table.not_applied)[:300] if result.table is not None else "",
    )


def _people_for(user: User, text: str, day: date, entry: HelpEntry) -> tuple[PersonHit, ...]:
    """The people the question names, for a person-bound entry. A lookup failure gives no people (the answer is still
    logged); the savepoint keeps a database error from breaking the log row that follows."""
    if not entry.person:
        return ()
    try:
        with transaction.atomic():
            return tuple(match_people(user, text, day))
    except Exception:
        logger.exception("The help assistant could not look up the people in a question.")
        return ()


def phrases_for(words: Sequence[FilterWords], text: str) -> dict[str, list[str]]:
    """For each offered lookup filter, the names that share a word with the question (at most MAX_CANDIDATES).

    Deviation from the brief, on purpose: the candidates are looked up per question word, not on the whole question.
    The resolver needs every phrase word covered by a name, so the whole question would name almost nothing. The cost
    is bounded: distinct words only (case folded), generic-only words skipped, at most MAX_TOKENS words, and each
    lookup's rows are loaded once for all of them."""
    tokens: list[str] = []
    seen: set[str] = set()
    for token in _WORD.findall(text):
        key = _fold(token)
        if key in seen or only_generic(token):
            continue
        seen.add(key)
        tokens.append(token)
        if len(tokens) == MAX_TOKENS:
            break
    phrases: dict[str, list[str]] = {}
    for word in words:
        if word.kind != "lookup" or word.param not in resolver.LOOKUPS:
            continue
        phrases[word.param] = resolver.candidate_names_many(word.param, tokens)
    return phrases


def _unexpected(exc: Exception) -> Answer:
    """The one logged, failed answer for an error that is not the provider's own (the class name only, not the text)."""
    return Answer(outcome=Outcome.ERROR, entry=None, also=None, lead="", error=f"{type(exc).__name__} (unexpected)")


def _from_plan(
    user: User,
    text: str,
    day: date,
    allowed: Sequence[HelpEntry],
    words: Sequence[FilterWords],
    plan: Plan,
    previous: str,
) -> Answer:
    """The answer for a plan. An entry answer needs a key the user is allowed; a table answer needs the user to have
    offered words and the right to open the table (a denied table gives no answer). Anything else is NONE."""
    if plan.tool == "entry":
        by_key = {entry.key: entry for entry in allowed}
        entry = by_key.get(plan.entry)
        if entry is None:
            return Answer(outcome=Outcome.NONE, entry=None, also=None, lead="", tool=plan.tool)
        also = by_key.get(plan.also)
        if also is not None and also.key == entry.key:
            also = None
        return Answer(
            outcome=Outcome.ANSWERED,
            entry=entry,
            also=also,
            lead=plan.lead.strip()[:LEAD_LIMIT],
            people=_people_for(user, text, day, entry),
            tool=plan.tool,
        )
    if plan.tool == "staff_table" and words:
        # The model's lead is not used here: it could hold a number the code did not count. The lead and the count
        # are written from the table itself.
        table = table_answer(
            user,
            plan.parts,
            base_query=previous,
            unmapped=plan.unmapped,
            want=plan.want,
            chart_kind=plan.chart_kind,
            chart_by=plan.chart_by,
        )
        if table.status != "denied":
            return Answer(outcome=Outcome.TABLE, entry=None, also=None, lead="", tool=plan.tool, table=table)
    return Answer(outcome=Outcome.NONE, entry=None, also=None, lead="", tool=plan.tool)


def answer(user: User, question: str, day: date, provider: Provider, previous: str = "") -> Answer:
    """Answer one question for `user` on `day`, and log it. `previous` is the address query of the earlier answer
    (untrusted: the table keeps only the parameters this user may use)."""
    started = time.monotonic()
    text = question.strip()[:QUESTION_LIMIT]
    previous = previous[:MAX_BASE]  # bounds what the provider reads and what the table parses
    empty = Answer(outcome=Outcome.NONE, entry=None, also=None, lead="")
    allowed_keys = ""  # stays blank on the LIMITED path, where no entry list is built

    if _recent_count(user) >= ASK_PER_HOUR:
        result = Answer(outcome=Outcome.LIMITED, entry=None, also=None, lead="")
        if _limited_logged(user):  # one limited row an hour is enough; repeated tries are not logged
            return result
    else:
        try:
            allowed = allowed_entries(user, day)
            allowed_keys = ",".join(e.key for e in allowed)
            # No words for a user who may not open the table: no table is asked for, and no provider call is made.
            words = offered_words(user) if can_open_table(user) else []
        except Exception as exc:  # a failure before the provider is still one logged, failed answer
            logger.exception("The help assistant could not load the entries or the table filters.")
            result = _unexpected(exc)
        else:
            if not allowed and not words:
                result = empty
            else:
                try:
                    learned = learning.learned_by_entry()
                    call_entries = [dataclasses.replace(e, learned=learned.get(e.key, ())) for e in allowed]
                    narrowed = narrow_entries(text, call_entries, limit=PLAN_ENTRIES)
                    plan = provider.plan(
                        text,
                        narrowed,
                        words,
                        phrases_for(words, text),
                        day,
                        previous,
                        learning.no_entry_questions(),
                        table_examples=learning.table_examples(),
                    )
                except ProviderError as exc:
                    result = Answer(outcome=Outcome.ERROR, entry=None, also=None, lead="", error=str(exc))
                except Exception as exc:  # any other failure is still one logged, failed answer
                    logger.exception("The help assistant provider raised an unexpected error.")
                    result = _unexpected(exc)
                else:
                    # A savepoint: a database error in the table or the people lookup rolls back only this step, so
                    # the log row that follows is still written.
                    try:
                        with transaction.atomic():
                            result = _from_plan(user, text, day, allowed, words, plan, previous)
                    except Exception as exc:
                        logger.exception("The help assistant could not turn the plan into an answer.")
                        result = _unexpected(exc)

    _log(user, text, result, provider, started, allowed_keys)
    return result
