"""The answer service: one question in, one checked answer out, and one log row per question."""

import dataclasses
import json
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from accounts.models import User
from django.db import transaction
from django.utils import timezone
from employees.palette import PersonHit, _fold

from assistant import learning, resolver
from assistant.actions import FieldAnswer, LeaveFormAnswer, field_answer, leave_form_answer
from assistant.columns import plan_extras
from assistant.entries import HelpEntry, allowed_entries
from assistant.fields import hints_for
from assistant.matching import named_first, narrow_entries, only_generic
from assistant.models import HelpQuestion, Outcome
from assistant.people import match_people
from assistant.plan import Plan
from assistant.providers import Provider, ProviderError
from assistant.tables import MAX_BASE, TableAnswer, can_open_table, table_answer
from assistant.words import FilterWords, offered_words

if TYPE_CHECKING:  # the runtime imports are lazy (in _sql_answer, sql_card): they load the Firebird and HR code
    from assistant.sqlanswer import SqlAnswer
    from assistant.sqltext import SqlCard

QUESTION_LIMIT = 300  # characters of a question that are kept and sent
ASK_PER_HOUR = 20  # questions per user in any rolling hour that reach the provider or are answered
LEAD_LIMIT = 200  # characters of the one-sentence lead
PLAN_ENTRIES = 30  # help entries the plan call sees at most: the ones that share a word with the question
FIELD_HINTS = 8  # field hints the plan call sees at most; the field tool answers only for these keys
MAX_TOKENS = 12  # distinct question words that are looked up in the lookups (a long question cannot multiply the work)

logger = logging.getLogger(__name__)

_COUNTED = (Outcome.ANSWERED, Outcome.NONE, Outcome.ERROR, Outcome.TABLE, Outcome.ACTION, Outcome.SQL)
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
    tool: str = ""  # the plan's tool ("entry", "staff_table", "field", "leave_form", "sql", "none"); "" when no plan
    table: TableAnswer | None = None  # the staff table answer, for a TABLE outcome only
    field: FieldAnswer | None = None  # the field answer, for an ACTION outcome from the "field" tool only
    leave: LeaveFormAnswer | None = None  # the leave form answer, for an ACTION outcome from "leave_form" only
    query: str = ""  # the log's query for an action: the field key (only a known one) or "leave_form"
    sql: "SqlAnswer | None" = None  # the SQL answer, for an SQL outcome (status "ok") only
    sql_status: str = ""  # the SQL answer's status ("ok", "off", "unavailable", "refused") for a `sql` tool answer
    question_id: int = 0  # the pk of this question's log row (set after logging); 0 when no row was written

    @property
    def sql_card(self) -> "SqlCard | None":
        """The SQL answer card's data, for an SQL outcome only. The import is lazy (sqltext loads the HR code)."""
        if self.sql is None:
            return None
        from assistant.sqltext import card_of

        return card_of(self.sql)


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


def _tokens(provider: Provider) -> tuple[int, int]:
    """The tokens the provider has used so far (0, 0 for a provider that does not count them, such as a test fake)."""
    return int(getattr(provider, "tokens_in", 0) or 0), int(getattr(provider, "tokens_out", 0) or 0)


def _log(
    user: User,
    question: str,
    result: Answer,
    provider: Provider,
    started: float,
    allowed: str,
    used: tuple[int, int] = (0, 0),
) -> int:
    """Writes the log row and returns its pk."""
    row = HelpQuestion.objects.create(
        tokens_in=used[0],
        tokens_out=used[1],
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
        query=result.table.query[:300] if result.table is not None else result.query[:300],
        not_applied=" | ".join(result.table.not_applied)[:300] if result.table is not None else "",
        # Only the checked SQL of an ok answer is logged; the model's own text never is.
        sql=result.sql.sql if result.sql is not None else "",
        sql_rows=result.sql.row_count if result.sql is not None else 0,
        salary_flag=result.sql.salary if result.sql is not None else False,
        sql_labels=json.dumps(result.sql.labels, ensure_ascii=False) if result.sql is not None and result.sql.labels else "",
    )
    return row.pk


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


def _sql_answer(user: User, text: str, day: date, provider: Provider) -> "SqlAnswer":
    """The SQL answer for a question the plan sent to the `sql` tool. A module-level seam: the tests replace it. The
    import is lazy because sqlanswer loads the Firebird driver code."""
    from assistant.sqlanswer import sql_answer

    return sql_answer(user, text, day, provider)


def _table_fell_short(table: TableAnswer, plan: Plan, previous: str) -> bool:
    """True when a staff-table answer left part of the question unapplied and governed SQL may try the whole question.

    Only a finished answer (not an "ask" for a choice), and only a question that starts fresh (a refinement depends on
    the earlier answer's filters, which SQL does not see). A chart asked for with no grouping of its own keeps the
    table's «name a grouping» line; it falls back only when the plan also left words the table could not map (the
    grouping the user named is one the table does not offer, for example «төрсөн жилээр»)."""
    if table.status != "list" or not table.not_applied:
        return False
    if table.want == "chart" and not plan.unmapped:
        return False
    return plan.fresh or not previous


def _from_plan(
    user: User,
    text: str,
    day: date,
    allowed: Sequence[HelpEntry],
    words: Sequence[FilterWords],
    plan: Plan,
    previous: str,
    hint_keys: frozenset[str],
    open_chart: tuple[str, str] | None = None,
    provider: Provider | None = None,
) -> Answer:
    """The answer for a plan. An entry answer needs a key the user is allowed; a table answer needs the user to have
    offered words and the right to open the table (a denied table gives no answer); a field answer needs a key the
    question hinted (`hint_keys`). Anything else is NONE."""
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
            base_query="" if plan.fresh else previous,
            unmapped=plan.unmapped,
            want=plan.want,
            chart_kind=plan.chart_kind,
            # A chart question with no grouping of its own keeps the open chart's grouping.
            chart_by=plan.chart_by or (open_chart[1] if open_chart and plan.want == "chart" else ""),
            group_by=plan.group_by,
            conditions=plan.conditions,
        )
        if table.status != "denied":
            if _table_fell_short(table, plan, previous) and provider is not None:
                # Part of the question was not applied (a filter or grouping the table does not have). Governed SQL is
                # the fallback for what the typed table cannot express; when it cannot answer either (off, refused),
                # the table answer below stands, with its not-applied lines.
                sql = _sql_answer(user, text, day, provider)
                if sql.status == "ok":
                    return Answer(
                        outcome=Outcome.SQL, entry=None, also=None, lead="", tool="sql", sql=sql, sql_status=sql.status
                    )
            return Answer(outcome=Outcome.TABLE, entry=None, also=None, lead="", tool=plan.tool, table=table)
    if plan.tool == "field":
        # A key the question did not hint is no answer, even if the registry has it: the model may not pick a field the
        # words do not name. Nothing is logged as the query then (the key could be made up).
        if plan.field not in hint_keys:
            return Answer(outcome=Outcome.NONE, entry=None, also=None, lead="", tool=plan.tool)
        field = field_answer(user, text, day, plan.field, plan.own)
        if field.status == "none":
            return Answer(outcome=Outcome.NONE, entry=None, also=None, lead="", tool=plan.tool, query=plan.field)
        return Answer(
            outcome=Outcome.ACTION, entry=None, also=None, lead="", tool=plan.tool, field=field, query=plan.field
        )
    if plan.tool == "leave_form":
        leave = leave_form_answer(user, text, day, plan.own, plan.leave_type, plan.start, plan.end)
        if leave.status == "none":
            return Answer(outcome=Outcome.NONE, entry=None, also=None, lead="", tool=plan.tool, query="leave_form")
        return Answer(
            outcome=Outcome.ACTION, entry=None, also=None, lead="", tool=plan.tool, leave=leave, query="leave_form"
        )
    if plan.tool == "sql" and provider is not None:
        sql = _sql_answer(user, text, day, provider)
        if sql.status != "ok":  # off, unavailable or refused: no answer, the reason is logged (never shown as one)
            return Answer(
                outcome=Outcome.NONE,
                entry=None,
                also=None,
                lead="",
                tool=plan.tool,
                error=sql.reason[:300],
                sql_status=sql.status,
            )
        return Answer(
            outcome=Outcome.SQL, entry=None, also=None, lead="", tool=plan.tool, sql=sql, sql_status=sql.status
        )
    return Answer(outcome=Outcome.NONE, entry=None, also=None, lead="", tool=plan.tool)


def answer(
    user: User,
    question: str,
    day: date,
    provider: Provider,
    previous: str = "",
    open_chart: tuple[str, str] | None = None,
) -> Answer:
    """Answer one question for `user` on `day`, and log it. `previous` is the address query of the earlier answer
    (untrusted: the table keeps only the parameters this user may use)."""
    started = time.monotonic()
    tokens_before = _tokens(provider)  # a provider object may serve several questions: log only this one's tokens
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
                    narrowed = named_first(text, call_entries, narrow_entries(text, call_entries, limit=PLAN_ENTRIES))
                    hints = hints_for(text, limit=FIELD_HINTS)
                    # Only the real adapters take open_chart; it is sent only when a chart is open.
                    extra: dict[str, Any] = {"open_chart": open_chart} if open_chart is not None else {}
                    plan = provider.plan(
                        text,
                        narrowed,
                        words,
                        phrases_for(words, text),
                        day,
                        previous,
                        learning.no_entry_questions(),
                        table_examples=learning.table_examples(),
                        field_hints=hints,
                        **extra,
                        **plan_extras(provider, user),
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
                            result = _from_plan(
                                user,
                                text,
                                day,
                                allowed,
                                words,
                                plan,
                                previous,
                                frozenset(h.key for h in hints),
                                open_chart,
                                provider,
                            )
                    except Exception as exc:
                        logger.exception("The help assistant could not turn the plan into an answer.")
                        result = _unexpected(exc)

    tokens_after = _tokens(provider)
    used = (max(tokens_after[0] - tokens_before[0], 0), max(tokens_after[1] - tokens_before[1], 0))
    question_id = _log(user, text, result, provider, started, allowed_keys, used)
    return dataclasses.replace(result, question_id=question_id)
