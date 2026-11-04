"""Tests for the answer service: question cut, rate limit, entry checks, lead cut and the log row."""

from collections.abc import Callable, Sequence
from datetime import date, timedelta

import pytest
from accounts.models import User
from django.utils import timezone

from assistant.entries import HelpEntry
from assistant.models import HelpExample, HelpQuestion, Kind, Outcome
from assistant.providers import Choice, ProviderError
from assistant.services import ASK_PER_HOUR, LEAD_LIMIT, QUESTION_LIMIT, answer, looks_like_question

DAY = date(2026, 11, 4)
QUESTION = "яаж чөлөө бүртгэх вэ"


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, choice: Choice | None = None, exc: Exception | None = None) -> None:
        self.choice = choice
        self.exc = exc
        self.calls = 0
        self.questions: list[str] = []
        self.entries_seen: list[Sequence[HelpEntry]] = []
        self.refusals_seen: list[Sequence[str]] = []

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Choice:
        self.calls += 1
        self.questions.append(question)
        self.entries_seen.append(entries)
        self.refusals_seen.append(refusals)
        if self.exc is not None:
            raise self.exc
        assert self.choice is not None
        return self.choice


@pytest.mark.django_db
def test_answered_for_allowed_key(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө бүртгэх хэсэг."))
    result = answer(user, QUESTION, DAY, provider)
    assert result.outcome == Outcome.ANSWERED
    assert result.entry is not None
    assert result.entry.key == "leave.record"
    row = HelpQuestion.objects.get(user=user)
    assert row.entry == "leave.record"
    assert row.outcome == "answered"


@pytest.mark.django_db
def test_disallowed_key_counts_as_none(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("accountant")
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө."))
    result = answer(user, QUESTION, DAY, provider)
    assert result.outcome == Outcome.NONE
    assert result.entry is None
    assert result.lead == ""


@pytest.mark.django_db
def test_unknown_key_counts_as_none(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("hr")
    provider = FakeProvider(Choice(entry="admin.everything", also="", lead="Тайлбар."))
    result = answer(user, "бүх зүйл", DAY, provider)
    assert result.outcome == Outcome.NONE


@pytest.mark.django_db
def test_also_kept_only_if_allowed_and_different(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("hr")
    same = FakeProvider(Choice(entry="leave.record", also="leave.record", lead="Чөлөө."))
    assert answer(user, "чөлөө", DAY, same).also is None

    other = FakeProvider(Choice(entry="leave.record", also="leave.balances", lead="Чөлөө."))
    result = answer(user, "чөлөө", DAY, other)
    assert result.also is not None
    assert result.also.key == "leave.balances"


@pytest.mark.django_db
def test_no_allowed_entries_skips_provider(role_user: Callable[[str], User]) -> None:
    user = role_user("none")
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө."))
    result = answer(user, "чөлөө", DAY, provider)
    assert result.outcome == Outcome.NONE
    assert provider.calls == 0
    assert HelpQuestion.objects.filter(user=user, outcome="none").count() == 1


@pytest.mark.django_db
def test_provider_error_logged(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("hr")
    provider = FakeProvider(exc=ProviderError("boom"))
    result = answer(user, "чөлөө", DAY, provider)
    assert result.outcome == Outcome.ERROR
    assert HelpQuestion.objects.get(user=user).outcome == "error"


@pytest.mark.django_db
def test_unexpected_error_logged(role_user: Callable[[str], User]) -> None:
    user = role_user("hr")
    provider = FakeProvider(exc=RuntimeError("boom"))
    result = answer(user, "чөлөө", DAY, provider)
    assert result.outcome == Outcome.ERROR
    assert result.entry is None
    rows = HelpQuestion.objects.filter(user=user)
    assert rows.count() == 1
    assert rows.get().outcome == "error"


@pytest.mark.django_db
def test_rate_limit(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("hr")
    for _ in range(ASK_PER_HOUR):
        HelpQuestion.objects.create(user=user, question="чөлөө", outcome=Outcome.ANSWERED)
    old = HelpQuestion.objects.create(user=user, question="хуучин", outcome=Outcome.ANSWERED)
    HelpQuestion.objects.filter(pk=old.pk).update(asked_at=timezone.now() - timedelta(hours=2))

    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө."))
    result = answer(user, "чөлөө", DAY, provider)
    assert result.outcome == Outcome.LIMITED
    assert provider.calls == 0
    assert HelpQuestion.objects.filter(user=user, outcome="limited").count() == 1
    assert HelpQuestion.objects.filter(user=user).count() == ASK_PER_HOUR + 2

    again = answer(user, "чөлөө", DAY, provider)
    assert again.outcome == Outcome.LIMITED
    assert provider.calls == 0
    assert HelpQuestion.objects.filter(user=user, outcome="limited").count() == 1
    assert HelpQuestion.objects.filter(user=user).count() == ASK_PER_HOUR + 2


@pytest.mark.django_db
def test_rows_older_than_an_hour_do_not_count(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("hr")
    for _ in range(ASK_PER_HOUR):
        row = HelpQuestion.objects.create(user=user, question="хуучин", outcome=Outcome.ANSWERED)
        HelpQuestion.objects.filter(pk=row.pk).update(asked_at=timezone.now() - timedelta(hours=2))

    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө."))
    result = answer(user, "чөлөө", DAY, provider)
    assert result.outcome == Outcome.ANSWERED
    assert provider.calls == 1


@pytest.mark.django_db
def test_long_question_is_cut(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("hr")
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="Чөлөө."))
    answer(user, "а" * 1000, DAY, provider)
    assert len(provider.questions[0]) == QUESTION_LIMIT
    assert len(HelpQuestion.objects.get(user=user).question) == QUESTION_LIMIT


@pytest.mark.django_db
def test_lead_cut(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("hr")
    provider = FakeProvider(Choice(entry="leave.record", also="", lead="б" * 500))
    result = answer(user, "чөлөө", DAY, provider)
    assert result.outcome == Outcome.ANSWERED
    assert len(result.lead) == LEAD_LIMIT


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("яаж чөлөө бүртгэх вэ", True),
        ("хаанаас чөлөө бүртгэх вэ", True),
        ("чөлөө?", True),
        ("Яаж", True),
        ("Болд", False),
        ("чолоо буртгэх", False),
        ("бүртгэх вэ.", True),
        ("Болд.", False),
    ],
)
def test_looks_like_question(text: str, expected: bool) -> None:
    assert looks_like_question(text) is expected


@pytest.mark.django_db
def test_learned_examples_only_on_allowed_entries(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("staff")
    HelpExample.objects.create(question="чөлөө бүртгэх жишээ", entry="leave.record", kind=Kind.EXAMPLE, active=True)
    HelpExample.objects.create(question="чөлөө хүсэх жишээ", entry="leave.request", kind=Kind.EXAMPLE, active=True)
    provider = FakeProvider(Choice(entry="leave.request", also="", lead="Чөлөө."))
    answer(user, QUESTION, DAY, provider)
    entries = {e.key: e for e in provider.entries_seen[0]}
    assert "leave.record" not in entries
    assert entries["leave.request"].learned == ("чөлөө хүсэх жишээ",)
    assert all(e.learned == () for key, e in entries.items() if key != "leave.request")


@pytest.mark.django_db
def test_refusals_passed(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("staff")
    HelpExample.objects.create(question="энэ бол эргэлт", entry="", kind=Kind.EXAMPLE, active=True)
    provider = FakeProvider(Choice(entry="leave.request", also="", lead="Чөлөө."))
    answer(user, QUESTION, DAY, provider)
    assert provider.refusals_seen[0] == ("энэ бол эргэлт",)


@pytest.mark.django_db
def test_inactive_not_passed(role_user: Callable[[str], User], approval_on: None) -> None:
    user = role_user("staff")
    HelpExample.objects.create(question="идэвхгүй жишээ", entry="leave.request", kind=Kind.EXAMPLE, active=False)
    HelpExample.objects.create(question="идэвхгүй хоосон", entry="", kind=Kind.EXAMPLE, active=False)
    provider = FakeProvider(Choice(entry="leave.request", also="", lead="Чөлөө."))
    answer(user, QUESTION, DAY, provider)
    assert all(e.learned == () for e in provider.entries_seen[0])
    assert provider.refusals_seen[0] == ()
