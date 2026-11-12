"""The SQL answer of the assistant: one governed query, checked and run as the asker, retried once on a refusal.

Flow: the setting must be on and the governed database ready; the asker's catalogue must not be empty. Then the
model is asked for one query (ask_sql), the checker and the runner run it as the asker (run_question). A refusal
goes back to the model once, with our own refusal reason and the same catalogue text. At most two model calls
happen per question. The model's own text is never shown as an answer.

No new migration. This module may import hr_sql and sqlcore; sqlcore imports nothing from HR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from accounts.models import User
from django.db import connections
from employees.models import CompanySettings
from hr_sql.connection import GOVERNED_ALIAS
from hr_sql.host import HrHost
from sqlcore.catalogue import Catalogue
from sqlcore.explain import Explanation, explain, tidy_result
from sqlcore.runner import Answered, Host, Refused, run_question
from sqlcore.tools import describe_text

from assistant.providers import Provider
from assistant.sqlask import ask_sql_reply
from assistant.verified import examples_for

MAX_ATTEMPTS = 2
SALARY_VIEWS = frozenset({"GOV_SALARY", "GOV_LOANS"})

OFF_REASON = "Answers from the data are switched off."
UNAVAILABLE_REASON = "Answers from the data are not available here."
NO_VIEWS_REASON = "You have no data views to ask about."
# A provider failure: the text is ours, the provider's own message never goes into the answer or the log.
PROVIDER_REASON = "The question could not be answered from the data just now."
# The model wrote an empty query: by the instruction that means the views the asker may see cannot answer it (for
# example a gender split for a user who has no GENDER column). It is not retried: a retry made the model drop the
# part it could not answer and return a different, partial answer.
NOT_ANSWERABLE_REASON = "The data you may see cannot answer this question."


@dataclass(frozen=True)
class SqlAnswer:
    status: str  # "ok", "refused", "off" or "unavailable"
    reason: str  # "" when ok
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]  # tidied: money rounded to 2 places
    sql: str  # the checked SQL when ok; "" otherwise
    explanation: Explanation | None
    row_count: int
    salary: bool  # the checked SQL read GOV_SALARY or GOV_LOANS
    labels: dict[str, str] = field(default_factory=dict)  # the model's Mongolian column headings {"COLUMN": "heading"}


def _setting_enabled() -> bool:
    """The governed SQL switch (CompanySettings.governed_sql_enabled). Patched in the no-database tests."""
    return CompanySettings.get().governed_sql_enabled


def _database_ready() -> bool:
    """True on Firebird with the governed alias configured. Patched in the no-database tests."""
    return connections["default"].vendor == "firebird" and GOVERNED_ALIAS in connections.databases


def _empty(status: str, reason: str) -> SqlAnswer:
    return SqlAnswer(
        status=status, reason=reason, columns=(), rows=(), sql="", explanation=None, row_count=0, salary=False
    )


def _answered(outcome: Answered, catalogue: Catalogue, labels: dict[str, str]) -> SqlAnswer:
    # Explain the raw result first: MONEY_ROUNDED must reflect the rounding the user will see.
    explanation = explain(outcome.query, outcome.result, catalogue)
    tidied, _changed = tidy_result(outcome.result)
    return SqlAnswer(
        status="ok",
        reason="",
        columns=tuple(tidied.columns),
        rows=tuple(tidied.rows),
        sql=outcome.query.sql,
        explanation=explanation,
        row_count=explanation.row_count,
        salary=bool(outcome.query.views & SALARY_VIEWS),
        labels=labels,
    )


def sql_answer(user: User, text: str, day: date, provider: Provider, host: Host | None = None) -> SqlAnswer:
    """Answer one question with a governed query, or say why it cannot be answered. Never raises for a provider or
    checker failure; the reason is for the log and for the card."""
    if not _setting_enabled():
        return _empty("off", OFF_REASON)
    if not _database_ready():
        return _empty("unavailable", UNAVAILABLE_REASON)

    governed: Host = host if host is not None else HrHost()
    catalogue = governed.catalogue_for(user)
    if not catalogue.views:
        return _empty("unavailable", NO_VIEWS_REASON)
    catalogue_text = describe_text(catalogue)
    # Only approved examples whose views the asker's own catalogue covers (assistant/verified.py).
    examples = examples_for(catalogue, text)

    refusal = ""
    for _attempt in range(MAX_ATTEMPTS):
        try:
            reply = ask_sql_reply(provider, catalogue_text, text, day, refusal=refusal, examples=examples)
        except Exception as error:
            return _empty("refused", f"{PROVIDER_REASON} ({type(error).__name__})")
        sql = reply.sql
        if not sql.strip():
            return _empty("refused", NOT_ANSWERABLE_REASON)
        outcome = run_question(governed, user, sql)
        if isinstance(outcome, Refused):
            refusal = outcome.reason
            continue
        return _answered(outcome, catalogue, reply.labels)
    return _empty("refused", refusal)
