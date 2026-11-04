"""Tests for the eval set rules and the assistant_eval command."""

import difflib
import re
from collections.abc import Sequence
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from pytest import MonkeyPatch

from assistant.entries import ENTRIES, HelpEntry
from assistant.evalset import CASES, ROLE_ENTRIES, ROLES, EvalCase, expected
from assistant.management.commands import assistant_eval
from assistant.models import HelpExample, HelpQuestion, Kind
from assistant.providers import Choice


def _case(question: str) -> EvalCase:
    """The shipped case with this question, or the local test row that asks it."""
    case = next((c for c in CASES if c.question == question), None)
    if case is not None:
        return case
    row = HelpExample.objects.get(question=question, kind=Kind.TEST)
    return EvalCase(row.question, row.entry)


class PerfectProvider:
    name = "fake"
    model = "fake-model"

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        keys = tuple(e.key for e in entries)
        role = next(r for r in ROLES if ROLE_ENTRIES[r] == keys)
        return Choice(entry=expected(_case(question), role), also="", lead="")


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
    assert len(CASES) == 30


@pytest.mark.django_db
def test_command_with_perfect_fake(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: PerfectProvider())
    out = StringIO()
    call_command("assistant_eval", stdout=out)
    assert "hr: 30/30" in out.getvalue()
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
    assert "Cases: shipped 30, local 1" in text
    assert text.splitlines()[0].startswith("Cases: shipped 30, local 1, newest ")
    assert "hr: 31/31" in text


@pytest.mark.django_db
def test_shipped_only(monkeypatch: MonkeyPatch) -> None:
    HelpExample.objects.create(question="Тест асуулт", entry="leave.record", kind=Kind.TEST)
    HelpExample.objects.create(question="Жишээ асуулт", entry="leave.record", kind=Kind.EXAMPLE)
    HelpExample.objects.create(question="Хэн ч биш асуулт", entry="", kind=Kind.EXAMPLE)
    provider = RecordingProvider()
    monkeypatch.setattr(assistant_eval, "get_provider", lambda: provider)
    out = StringIO()
    call_command("assistant_eval", shipped_only=True, stdout=out)
    assert out.getvalue().splitlines()[0] == "Cases: shipped 30, local 0"
    assert "hr: 30/30" in out.getvalue()
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

    monkeypatch.setattr(assistant_eval, "get_provider", lambda: MissingProvider(hr_answerable[:3]))
    out = StringIO()
    call_command("assistant_eval", stdout=out)
    assert "hr: 28/31" in out.getvalue()

    monkeypatch.setattr(assistant_eval, "get_provider", lambda: MissingProvider(hr_answerable[:4]))
    with pytest.raises(CommandError, match=re.escape(message)):
        call_command("assistant_eval", stdout=StringIO())


def test_cases_differ_from_entry_examples() -> None:
    """A test question the model has already seen as an entry example would only measure memory."""
    examples = [x for e in ENTRIES for x in (*e.examples, *e.words)]
    too_close = [
        (c.question, x) for c in CASES for x in examples if difflib.SequenceMatcher(None, c.question, x).ratio() >= 0.8
    ]
    assert too_close == []
