"""Tests for the eval set rules and the assistant_eval command."""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from pytest import MonkeyPatch

from assistant.entries import ENTRIES, HelpEntry
from assistant.evalset import ACTION_CASES, CASES, ROLE_ENTRIES, ROLES, TABLE_CASES, EvalCase, expected
from assistant.management.commands import assistant_eval
from assistant.models import HelpExample, HelpQuestion, Kind
from assistant.plan import Plan
from assistant.providers import Choice
from assistant.tests.helpers import (
    action_plan_for,
    drop_narrowing,
    fake_plan,
    seed_eval_rows,
    table_plan_for,
    too_close_pairs,
)
from assistant.words import FilterWords


def _case(question: str) -> EvalCase:
    """The shipped case with this question, or the local test row that asks it."""
    case = next((c for c in CASES if c.question == question), None)
    if case is not None:
        return case
    row = HelpExample.objects.get(question=question, kind=Kind.TEST)
    return EvalCase(row.question, row.entry)


@pytest.fixture(autouse=True)
def _eval_setup(request: pytest.FixtureRequest, monkeypatch: MonkeyPatch) -> None:
    """The fakes need the whole role list (see drop_narrowing); a database test gets the rows the table cases name."""
    drop_narrowing(monkeypatch)
    if request.node.get_closest_marker("django_db") is not None:
        request.getfixturevalue("db")
        seed_eval_rows()


class PerfectProvider:
    name = "fake"
    model = "fake-model"

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        keys = tuple(e.key for e in entries)
        role = next(r for r in ROLES if ROLE_ENTRIES[r] == keys)
        return Choice(entry=expected(_case(question), role), also="", lead="")

    def plan(
        self,
        question: str,
        entries: Sequence[HelpEntry],
        words: Sequence[FilterWords],
        phrases: Mapping[str, list[str]],
        today: date,
        previous: str = "",
        refusals: Sequence[str] = (),
        table_examples: Sequence[tuple[str, str]] = (),
        field_hints: Sequence[object] = (),
    ) -> Plan:
        case = next((c for c in TABLE_CASES if c.question == question), None)
        if case is not None:
            return table_plan_for(case, today)
        action = next((c for c in ACTION_CASES if c.question == question), None)
        if action is not None:
            return action_plan_for(action)
        return fake_plan(self, question, entries, refusals)


class RecordingProvider(PerfectProvider):
    """Perfect, and keeps what each call was given."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[HelpEntry, ...], tuple[str, ...]]] = []

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        self.calls.append((tuple(entries), tuple(refusals)))
        return super().choose(question, entries, refusals)


class MissingProvider(PerfectProvider):
    """Perfect, except that role hr gets the given questions wrong (it answers with no entry)."""

    def __init__(self, questions: list[str]) -> None:
        self.wrong = set(questions)

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        if question in self.wrong and tuple(e.key for e in entries) == ROLE_ENTRIES["hr"]:
            return Choice(entry="", also="", lead="")
        return super().choose(question, entries, refusals)


def test_expected_rules() -> None:
    assert expected(EvalCase("x", "leave.record"), "staff") == "leave.request"
    assert expected(EvalCase("x", "leave.balances"), "staff") == ""
    assert expected(EvalCase("x", ""), "hr") == ""


# Who "names a person" in a case question: one of PERSON_NAMES, capitalised, as a whole word, with at most one
# CASE_ENDINGS after it («Номины», «Болдын», «Батад»). The name list is hard-coded on purpose: the cases are fixed
# text, so the list is exact and the test never looks up real staff. «Батлах» (a verb) does not match, because
# «лах» is not a case ending.
PERSON_NAMES = ("Бат", "Болд", "Номин")
CASE_ENDINGS = ("", "ы", "ын", "ийн", "ийг", "ыг", "д", "ад", "од", "өд", "т", "тай", "руу", "ээс", "оос")
_NAME_RE = "|".join(PERSON_NAMES)
_ENDING_RE = "|".join(sorted(CASE_ENDINGS, key=len, reverse=True))
_PERSON = re.compile(rf"(?<!\w)(?:{_NAME_RE})(?:{_ENDING_RE})(?!\w)")


def _names_person(question: str) -> bool:
    return _PERSON.search(question) is not None


def test_cases_cover_every_area() -> None:
    """The accuracy set covers every area of the help entries.

    Every area (the key part before the first dot, e.g. «employee») has at least 3 cases whose intent is in that
    area. Every entry has at least 1 case, except the generated report entries (report.<registry key>; the three
    hand-written report entries catalogue, export and saved_view are not generated). At least 5 cases name a person
    (see PERSON_NAMES) for a person-bound entry. At least 5 cases have intent "" (not in the system).
    """
    intents = Counter(c.intent for c in CASES)
    areas = sorted({e.key.split(".")[0] for e in ENTRIES})
    for area in areas:
        n = sum(count for intent, count in intents.items() if intent.split(".")[0] == area)
        assert n >= 3, f"area {area}: {n} cases, needs at least 3"

    generated = {e.key for e in ENTRIES if e.key.startswith("report.")} - {
        "report.catalogue",
        "report.export",
        "report.saved_view",
    }
    missing = [e.key for e in ENTRIES if e.key not in generated and intents[e.key] == 0]
    assert missing == [], f"entries without a case: {missing}"

    person_keys = {e.key for e in ENTRIES if e.person}
    named = [c for c in CASES if c.intent in person_keys and _names_person(c.question)]
    assert len(named) >= 5, f"{len(named)} cases name a person for a person-bound entry, needs at least 5"

    assert intents[""] >= 5, f'{intents[""]} cases with intent "", needs at least 5'


@pytest.mark.django_db
def test_command_with_perfect_fake(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: PerfectProvider())
    out = StringIO()
    call_command("assistant_eval", stdout=out)
    assert f"hr: {len(CASES)}/{len(CASES)}" in out.getvalue()
    assert HelpQuestion.objects.count() == 0


@pytest.mark.django_db
def test_command_pauses_before_each_call(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: PerfectProvider())
    sleeps: list[float] = []
    monkeypatch.setattr("assistant.management.commands.assistant_eval.time.sleep", sleeps.append)
    call_command("assistant_eval", pause=2.0, stdout=StringIO())
    assert sleeps
    assert all(s == 2.0 for s in sleeps)


@pytest.mark.django_db
def test_command_does_not_pause_by_default(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: PerfectProvider())
    sleeps: list[float] = []
    monkeypatch.setattr("assistant.management.commands.assistant_eval.time.sleep", sleeps.append)
    call_command("assistant_eval", stdout=StringIO())
    assert sleeps == []


class EmptyProvider:
    name = "fake"
    model = "fake-model"

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        return Choice(entry="", also="", lead="")

    def plan(
        self,
        question: str,
        entries: Sequence[HelpEntry],
        words: Sequence[FilterWords],
        phrases: Mapping[str, list[str]],
        today: date,
        previous: str = "",
        refusals: Sequence[str] = (),
        table_examples: Sequence[tuple[str, str]] = (),
        field_hints: Sequence[object] = (),
    ) -> Plan:
        return fake_plan(self, question, entries, refusals)


@pytest.mark.django_db
def test_command_fails_below_pass_mark(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: EmptyProvider())
    message = "Pass mark not reached: every role needs at least 90%."
    with pytest.raises(CommandError, match=re.escape(message)):
        call_command("assistant_eval", stdout=StringIO())


def test_command_fails_when_off(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: None)
    with pytest.raises(CommandError, match=re.escape("Туслах идэвхгүй: .env-д ASSISTANT_* тохиргоо алга.")):
        call_command("assistant_eval")


@pytest.mark.django_db
def test_local_tests_counted(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: PerfectProvider())
    HelpExample.objects.create(question="Тест асуулт нэг", entry="leave.record", kind=Kind.TEST)
    out = StringIO()
    call_command("assistant_eval", stdout=out)
    text = out.getvalue()
    assert f"Cases: shipped {len(CASES)}, local 1" in text
    assert text.splitlines()[0].startswith(f"Cases: shipped {len(CASES)}, local 1, newest ")
    assert f"hr: {len(CASES) + 1}/{len(CASES) + 1}" in text


@pytest.mark.django_db
def test_shipped_only(monkeypatch: MonkeyPatch) -> None:
    HelpExample.objects.create(question="Тест асуулт", entry="leave.record", kind=Kind.TEST)
    HelpExample.objects.create(question="Жишээ асуулт", entry="leave.record", kind=Kind.EXAMPLE)
    HelpExample.objects.create(question="Хэн ч биш асуулт", entry="", kind=Kind.EXAMPLE)
    provider = RecordingProvider()
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: provider)
    out = StringIO()
    call_command("assistant_eval", shipped_only=True, stdout=out)
    assert out.getvalue().splitlines()[0] == f"Cases: shipped {len(CASES)}, local 0"
    assert f"hr: {len(CASES)}/{len(CASES)}" in out.getvalue()
    assert provider.calls
    assert all(e.learned == () for entries, _ in provider.calls for e in entries)
    assert all(refusals == () for _, refusals in provider.calls)


@pytest.mark.django_db
def test_local_examples_sent_by_default(monkeypatch: MonkeyPatch) -> None:
    HelpExample.objects.create(question="Жишээ асуулт нэг", entry="leave.record", kind=Kind.EXAMPLE)
    HelpExample.objects.create(question="Хэн ч биш асуулт", entry="", kind=Kind.EXAMPLE)
    provider = RecordingProvider()
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: provider)
    call_command("assistant_eval", stdout=StringIO())
    seen = [e for entries, _ in provider.calls for e in entries if e.key == "leave.record"]
    assert any("Жишээ асуулт нэг" in e.learned for e in seen)
    assert any("Хэн ч биш асуулт" in refusals for _, refusals in provider.calls)


@pytest.mark.django_db
def test_ninety_percent_mark(monkeypatch: MonkeyPatch) -> None:
    HelpExample.objects.create(question="Тест асуулт нэг", entry="leave.record", kind=Kind.TEST)
    hr_answerable = [c.question for c in CASES if expected(c, "hr")]
    message = "Pass mark not reached: every role needs at least 90%."

    total = len(CASES) + 1  # the shipped cases and the one local test row
    allowed = total // 10  # at most 10% of the cases may be wrong

    monkeypatch.setattr(assistant_eval, "get_provider", lambda: MissingProvider(hr_answerable[:allowed]))
    out = StringIO()
    call_command("assistant_eval", stdout=out)
    assert f"hr: {total - allowed}/{total}" in out.getvalue()

    monkeypatch.setattr(assistant_eval, "get_provider", lambda: MissingProvider(hr_answerable[: allowed + 1]))
    with pytest.raises(CommandError, match=re.escape(message)):
        call_command("assistant_eval", stdout=StringIO())


def test_cases_differ_from_entry_examples() -> None:
    """A test question the model has already seen as an entry example would only measure memory."""
    examples = [x for e in ENTRIES for x in (*e.examples, *e.words)]
    assert too_close_pairs([c.question for c in CASES], examples) == []
