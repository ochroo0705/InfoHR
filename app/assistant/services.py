"""The answer service: one question in, one checked answer out, and one log row per question."""

import dataclasses
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta

from accounts.models import User
from django.utils import timezone
from employees.palette import _fold

from assistant import learning
from assistant.entries import HelpEntry, allowed_entries
from assistant.models import HelpQuestion, Outcome
from assistant.providers import Provider, ProviderError

QUESTION_LIMIT = 300  # characters of a question that are kept and sent
ASK_PER_HOUR = 20  # questions per user in any rolling hour that reach the provider or are answered
LEAD_LIMIT = 200  # characters of the one-sentence lead

logger = logging.getLogger(__name__)

_COUNTED = (Outcome.ANSWERED, Outcome.NONE, Outcome.ERROR)
_QUESTION_WORDS = ("яаж", "хаана", "хаанаас", "хэрхэн", "яах")
_QUESTION_ENDINGS = ("вэ", "бэ")


@dataclass(frozen=True)
class Answer:
    outcome: Outcome
    entry: HelpEntry | None
    also: HelpEntry | None
    lead: str


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
    )


def answer(user: User, question: str, day: date, provider: Provider) -> Answer:
    """Answer one help question for `user` on `day`, and log it."""
    started = time.monotonic()
    text = question.strip()[:QUESTION_LIMIT]
    empty = Answer(outcome=Outcome.NONE, entry=None, also=None, lead="")
    allowed_keys = ""  # stays blank on the LIMITED path, where no entry list is built

    if _recent_count(user) >= ASK_PER_HOUR:
        result = Answer(outcome=Outcome.LIMITED, entry=None, also=None, lead="")
        if _limited_logged(user):  # one limited row an hour is enough; repeated tries are not logged
            return result
    else:
        allowed = allowed_entries(user, day)
        allowed_keys = ",".join(e.key for e in allowed)
        if not allowed:
            result = empty
        else:
            try:
                learned = learning.learned_by_entry()
                call_entries = [dataclasses.replace(e, learned=learned.get(e.key, ())) for e in allowed]
                choice = provider.choose(text, call_entries, learning.no_entry_questions())
            except ProviderError:
                result = Answer(outcome=Outcome.ERROR, entry=None, also=None, lead="")
            except Exception:  # any other failure is still one logged, failed answer
                logger.exception("The help assistant provider raised an unexpected error.")
                result = Answer(outcome=Outcome.ERROR, entry=None, also=None, lead="")
            else:
                by_key = {entry.key: entry for entry in allowed}
                entry = by_key.get(choice.entry)
                also = by_key.get(choice.also)
                if entry is None:
                    result = empty
                else:
                    if also is not None and also.key == entry.key:
                        also = None
                    result = Answer(
                        outcome=Outcome.ANSWERED,
                        entry=entry,
                        also=also,
                        lead=choice.lead.strip()[:LEAD_LIMIT],
                    )

    _log(user, text, result, provider, started, allowed_keys)
    return result
