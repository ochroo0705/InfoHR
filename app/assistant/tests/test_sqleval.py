"""Tests for the SQL eval set (Task 14b): the case checker, the set itself, and the --sql flag of assistant_eval.

No provider and no Firebird here: the provider and the host are fakes, and the two settings seams of sqlanswer are
patched on. The one database test runs every truth function on the test database (PostgreSQL), so a typo in a
truth query fails here and not in a paid run.
"""

from collections.abc import Iterator
from typing import Any, cast
from uuid import uuid4

import pytest
from accounts.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.limits import Result

from assistant import sqlanswer
from assistant.learning import fold
from assistant.management.commands import assistant_eval
from assistant.models import VerifiedQuery, VerifiedStatus
from assistant.providers import Provider, ProviderError
from assistant.role_users import make_role_user
from assistant.sqleval import COMPARE_KINDS, SQL_CASES, SQL_ROLES, SqlCase, check_sql_case

FAKE_USER: Any = object()  # the fakes ignore the user; the real host is not used in this file

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="One row per visible employee.",
    columns=(Column("EMP_ID", "Employee id"), Column("FIRST_NAME", "First name"), Column("WORKING", "Working 1/0")),
)
COUNT_SQL = "SELECT COUNT(*) AS N FROM GOV_EMPLOYEES"
NAMES_SQL = "SELECT EMP_ID, FIRST_NAME FROM GOV_EMPLOYEES"


class FakeProvider:
    """Returns the replies in order. A reply that is an exception is raised. An extra call fails the test."""

    name = "fake"
    model = "fake-model"

    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)

    def complete_json(self, system: str, user: str, schema: Any = None) -> Any:
        if not self.replies:
            pytest.fail("the provider was called more times than the test allows")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class FakeHost:
    """A fixed catalogue and a fixed result for every query."""

    def __init__(self, result: Result) -> None:
        self.catalogue = Catalogue(views=(EMPLOYEES,))
        self.result = result

    def catalogue_for(self, user: object) -> Catalogue:
        return self.catalogue

    def execute(self, user: object, query: Any, limits: Any) -> Result:
        return self.result

    def cancel(self, user: object) -> None:
        pass


def _rows(*rows: tuple[object, ...], columns: tuple[str, ...] = ("N",)) -> Result:
    return Result(columns=columns, rows=tuple(rows), truncated=False)


def _fake(replies: list[Any]) -> Provider:
    return cast(Provider, FakeProvider(replies))


def _replies(sql: str) -> Provider:
    return _fake([{"sql": sql}])


@pytest.fixture
def switched_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The setting is on and the governed database is ready; no database is touched and no examples are read."""
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)
    monkeypatch.setattr(sqlanswer, "examples_for", lambda catalogue, question: ())


def test_scalar_case_passes_and_fails(switched_on: None) -> None:
    case = SqlCase("Хэд вэ?", "hr", truth=lambda user: [(2,)], compare="scalar")
    host = FakeHost(_rows((2,)))
    assert check_sql_case(case, FAKE_USER, _replies(COUNT_SQL), host).passed

    wrong = SqlCase("Хэд вэ?", "hr", truth=lambda user: [(3,)], compare="scalar")
    result = check_sql_case(wrong, FAKE_USER, _replies(COUNT_SQL), FakeHost(_rows((2,))))
    assert not result.passed
    assert result.reason  # one line the eval prints


def test_set_case_ignores_row_order(switched_on: None) -> None:
    truth = SqlCase(
        "Нэрс?", "hr", truth=lambda user: [(2, "Бат"), (1, "Дорж")], compare="set"
    )
    host = FakeHost(_rows((1, "Дорж"), (2, "Бат"), columns=("EMP_ID", "FIRST_NAME")))
    assert check_sql_case(truth, FAKE_USER, _replies(NAMES_SQL), host).passed

    extra = SqlCase("Нэрс?", "hr", truth=lambda user: [(1, "Дорж")], compare="set")
    assert not check_sql_case(extra, FAKE_USER, _replies(NAMES_SQL), host).passed


def test_refused_case_passes_only_when_refused(switched_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    refused = SqlCase("Цалин?", "hr", truth=lambda user: [], compare="refused")
    # The model writes nothing usable on both attempts: a refusal from the checker.
    assert check_sql_case(refused, FAKE_USER, _fake([{"sql": ""}, {"sql": ""}]), FakeHost(_rows((1,)))).passed

    # The model writes a valid query: the case is answered, so it is not a refusal.
    assert not check_sql_case(refused, FAKE_USER, _replies(COUNT_SQL), FakeHost(_rows((1,)))).passed

    # A set case that is refused fails.
    names = SqlCase("Нэрс?", "hr", truth=lambda user: [(1, "Дорж")], compare="set")
    assert not check_sql_case(names, FAKE_USER, _fake([{"sql": ""}, {"sql": ""}]), FakeHost(_rows((1,)))).passed

    # A provider failure is not the model's refusal, so a refused case does not pass on it.
    failing = _fake([ProviderError("down"), ProviderError("down")])
    assert not check_sql_case(refused, FAKE_USER, failing, FakeHost(_rows((1,)))).passed


def test_every_case_has_a_known_role_and_a_nonempty_question() -> None:
    assert len(SQL_CASES) >= 25
    for case in SQL_CASES:
        assert case.role in SQL_ROLES, case.question
        assert case.question.strip(), case.role
        assert case.compare in COMPARE_KINDS, case.question


@pytest.mark.django_db
def test_cases_do_not_repeat_the_verified_examples_text() -> None:
    # The questions are unique for each role (the salary question is asked by two roles), and no eval question is the
    # question of an approved example: the model would see the answer in its prompt.
    pairs = [(case.role, case.question) for case in SQL_CASES]
    assert len(pairs) == len(set(pairs))
    approved = VerifiedQuery.objects.filter(status=VerifiedStatus.APPROVED).values_list("question", flat=True)
    approved_folded = {fold(question) for question in approved}
    assert not {fold(case.question) for case in SQL_CASES} & approved_folded


def test_command_refuses_without_yes_spend(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_provider_please() -> None:
        raise AssertionError("the provider must not be asked without --yes-spend")

    monkeypatch.setattr(assistant_eval, "get_provider", no_provider_please)
    with pytest.raises(CommandError, match="yes-spend"):
        call_command("assistant_eval", sql=True)


@pytest.fixture
def db_user_of() -> Iterator[Any]:
    """A role user of the kind, made inside the test's transaction (pytest-django rolls it back)."""

    def make(kind: str) -> User:
        actor = User.objects.create_user(f"sqleval_actor_{uuid4().hex[:8]}")
        return make_role_user(actor, kind, f"sqleval_{kind}_{uuid4().hex[:8]}")

    yield make


@pytest.mark.django_db
def test_every_truth_runs_on_the_database(db_user_of: Any) -> None:
    users = {role: db_user_of(role) for role in SQL_ROLES}
    for case in SQL_CASES:
        rows = case.truth(users[case.role])
        assert isinstance(rows, list), case.question
