"""Tests for the answer service's table path: a staff_table plan gives a table outcome, the model's lead is ignored,
the previous answer's query is passed on, and the not-applied words are logged."""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date

import pytest
from accounts.models import User
from employees.services import macs_writes
from employees.tests.conftest import _no_offboarding_templates  # noqa: F401 (autouse)

from assistant import resolver, services
from assistant.entries import HelpEntry
from assistant.models import HelpQuestion, Outcome
from assistant.plan import Part, Plan
from assistant.providers import Choice
from assistant.services import ASK_PER_HOUR, answer
from assistant.tables import TableAnswer
from assistant.tests.helpers import fake_plan, hire_one
from assistant.words import FilterWords, offered_words

DAY = date(2026, 11, 4)
QUESTION = "Санхүүгийн хэлтэст хэдэн хүн байна"


class PlanProvider:
    """A fake provider whose plan() is the `table` Plan it was given, and which records what it was asked."""

    name = "fake"
    model = "fake-model"

    def __init__(self, table: Plan) -> None:
        self.table = table
        self.calls = 0
        self.entries_seen: list[Sequence[HelpEntry]] = []
        self.phrases_seen: list[Mapping[str, list[str]]] = []
        self.previous_seen: list[str] = []
        self.words_seen: list[Sequence[FilterWords]] = []

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        raise AssertionError("answer() asks plan(), not choose()")

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
    ) -> Plan:
        self.calls += 1
        self.entries_seen.append(entries)
        self.phrases_seen.append(phrases)
        self.previous_seen.append(previous)
        self.words_seen.append(words)
        return fake_plan(self, question, entries, refusals)


def _table_plan(
    parts: tuple[Part, ...] = (Part(param="department", value="Санхүү"),),
    *,
    lead: str = "",
    unmapped: tuple[str, ...] = (),
    want: str = "count",
) -> Plan:
    return Plan(
        tool="staff_table",
        entry="",
        also="",
        lead=lead,
        parts=parts,
        unmapped=unmapped,
        want=want,
        chart_kind="",
        chart_by="",
    )


@pytest.mark.django_db
def test_table_plan_gives_table_outcome(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    hire_one(user)  # one hire: the helper makes a new Санхүү department on every call, which would be "ask"
    provider = PlanProvider(_table_plan())

    result = answer(user, QUESTION, DAY, provider)

    assert result.outcome == Outcome.TABLE
    assert isinstance(result.table, TableAnswer)
    assert result.table.status == "list"
    assert result.table.count == 1
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == "table"
    assert row.tool == "staff_table"
    assert "department=" in row.query


@pytest.mark.django_db
def test_entry_plan_unchanged(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("hr")
    plan = Plan(
        tool="entry",
        entry="leave.record",
        also="",
        lead="Чөлөө бүртгэх хэсэг.",
        parts=(),
        unmapped=(),
        want="list",
        chart_kind="",
        chart_by="",
    )
    result = answer(user, "чөлөө бүртгэх", DAY, PlanProvider(plan))

    assert result.outcome == Outcome.ANSWERED
    assert result.table is None
    assert result.lead == "Чөлөө бүртгэх хэсэг."
    row = HelpQuestion.objects.get(user=user)
    assert row.tool == "entry"
    assert row.query == ""


@pytest.mark.django_db
def test_model_lead_is_ignored_for_tables(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    hire_one(user)
    result = answer(user, QUESTION, DAY, PlanProvider(_table_plan(lead="42 хүн байна")))

    assert result.outcome == Outcome.TABLE
    assert result.lead == ""


@pytest.mark.django_db
def test_entry_key_outside_allowed_is_none(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("accountant")
    plan = Plan(
        tool="entry",
        entry="leave.record",
        also="",
        lead="Чөлөө.",
        parts=(),
        unmapped=(),
        want="list",
        chart_kind="",
        chart_by="",
    )
    result = answer(user, "чөлөө бүртгэх", DAY, PlanProvider(plan))

    assert result.outcome == Outcome.NONE
    assert result.entry is None
    assert HelpQuestion.objects.get(user=user).outcome == "none"


@pytest.mark.django_db
def test_not_applied_is_logged(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    hire_one(user)
    plan = _table_plan(unmapped=("дараа нь",))
    result = answer(user, QUESTION, DAY, PlanProvider(plan))

    assert result.table is not None
    assert result.table.not_applied
    row = HelpQuestion.objects.get(user=user)
    assert "дараа нь" in row.not_applied


@pytest.mark.django_db
def test_table_counts_toward_the_hour_limit(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    for _ in range(ASK_PER_HOUR):
        HelpQuestion.objects.create(user=user, question="хүснэгт", outcome=Outcome.TABLE)
    provider = PlanProvider(_table_plan())

    result = answer(user, QUESTION, DAY, provider)

    assert result.outcome == Outcome.LIMITED
    assert provider.calls == 0


@pytest.mark.django_db
def test_previous_is_passed_to_the_table(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    hire_one(user)
    provider = PlanProvider(_table_plan())

    result = answer(user, QUESTION, DAY, provider, previous="emptype=5")

    assert provider.previous_seen == ["emptype=5"]
    assert result.table is not None
    assert "emptype=5" in result.table.query
    assert "department=" in result.table.query
    assert "emptype=5" in HelpQuestion.objects.get(user=user).query


@pytest.mark.django_db
def test_staff_table_without_the_report_right_is_none(role_user: Callable[[str], User]) -> None:
    user = role_user("staff")
    result = answer(user, QUESTION, DAY, PlanProvider(_table_plan()))

    assert result.outcome == Outcome.NONE
    assert result.table is None
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == "none"
    assert row.query == ""


@pytest.mark.django_db
def test_plan_gets_narrowed_entries_and_phrases(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    hire_one(user)
    many = [
        HelpEntry(
            key=f"test.entry{index}",
            title=f"Санхүүгийн хэсэг {index}",
            steps=("Нээнэ.",),
            url_name="employees:list",
            modal=False,
            need=lambda user, day: True,
            labels=(),
            person_tab="",
        )
        for index in range(40)
    ]
    monkeypatch.setattr("assistant.services.allowed_entries", lambda user, day: many)
    provider = PlanProvider(_table_plan())

    answer(user, QUESTION, DAY, provider)

    assert len(provider.entries_seen[0]) == 30  # all 40 share the word «санхүүгийн»; the best 30 are kept
    assert provider.phrases_seen[0]["department"] == ["Санхүү"]
    assert {word.param for word in provider.words_seen[0]} >= {"department", "emptype"}


def _one_error_row(user: User) -> None:
    """Exactly one logged row, and it is the failed answer (no exception reached the caller)."""
    rows = HelpQuestion.objects.filter(user=user)
    assert rows.count() == 1
    assert rows.get().outcome == "error"


@pytest.mark.django_db
def test_table_error_is_one_error_row(role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    user = role_user("hr")

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(services, "table_answer", broken)
    result = answer(user, QUESTION, DAY, PlanProvider(_table_plan()))

    assert result.outcome == Outcome.ERROR
    assert result.error == "RuntimeError (unexpected)"
    _one_error_row(user)


@pytest.mark.django_db
def test_offered_words_error_is_one_error_row(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")

    def broken(*args: object, **kwargs: object) -> None:
        raise ValueError("bad filter")

    monkeypatch.setattr(services, "offered_words", broken)
    result = answer(user, QUESTION, DAY, PlanProvider(_table_plan()))

    assert result.outcome == Outcome.ERROR
    assert result.error == "ValueError (unexpected)"
    _one_error_row(user)


@pytest.mark.django_db
def test_allowed_entries_error_is_one_error_row(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")

    def broken(user: User, day: date) -> None:
        raise ValueError("bad entry")

    monkeypatch.setattr("assistant.services.allowed_entries", broken)
    result = answer(user, QUESTION, DAY, PlanProvider(_table_plan()))

    assert result.outcome == Outcome.ERROR
    _one_error_row(user)


@pytest.mark.django_db
def test_phrases_load_each_lookup_once_and_cap_at_15(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    for letter in "абвгдеёжзийклмноп":  # twenty departments that the word «Санхүү» names
        macs_writes.save_department(f"Санхүү{letter}")
    letters = "абвгдеёжзийклмнопрстуф"
    words = [a + b + c for a in letters for b in letters for c in letters][:100]  # a hostile question
    text = ("Санхүү " + " ".join(words))[:300]
    loads: list[str] = []
    real_rows = resolver._rows

    def counting(param: str) -> list[tuple[int, str]]:
        loads.append(param)
        return real_rows(param)

    monkeypatch.setattr(resolver, "_rows", counting)
    phrases = services.phrases_for(offered_words(user), text)

    assert max(Counter(loads).values()) == 1
    assert "department" in loads
    assert len(phrases["department"]) == 15
