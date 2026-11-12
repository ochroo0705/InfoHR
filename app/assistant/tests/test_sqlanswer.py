"""Tests for the SQL answer (Task 12c): the gate, one run, one retry after a refusal, and the explanation.

No database here: the host and the provider are fakes, and the two settings seams are patched where a test needs
them on. The only test that touches the database reads the real default of CompanySettings.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.explain import Warning
from sqlcore.limits import Result

from assistant import sqlanswer
from assistant.models import VerifiedQuery, VerifiedStatus
from assistant.providers import ProviderError
from assistant.sqlanswer import SqlAnswer, sql_answer

TODAY = date(2026, 11, 11)
QUESTION = "Хүүхдийн тоо?"
FAKE_USER: Any = object()  # the fakes ignore the user; the real host is not used in this file

CHILDREN = View(
    name="GOV_CHILDREN",
    description="One row per child of an employee.",
    columns=(Column("EMP_ID", "Employee id"), Column("CHILD_NAME", "Child name"), Column("AMOUNT", "Amount")),
)
SALARY = View(
    name="GOV_SALARY",
    description="Salary records.",
    columns=(Column("EMP_ID", "Employee id"), Column("BASE_SALARY", "Base salary")),
)
GOOD_SQL = "SELECT EMP_ID, CHILD_NAME FROM GOV_CHILDREN"
MISSING_VIEW = "Table GOV_NOPE is not a governed view you may use."


class FakeProvider:
    """Records each complete_json call and returns the replies in order. An extra call fails the test."""

    name = "fake"
    model = "fake-model"

    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str, Any]] = []

    def complete_json(self, system: str, user: str, schema: Any = None) -> Any:
        self.calls.append((system, user, schema))
        if not self.replies:
            pytest.fail("the provider was called more times than the test allows")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class FakeHost:
    """A host with a fixed catalogue and a fixed result. Records every SQL it was asked to run."""

    def __init__(self, views: tuple[View, ...], result: Result | None = None) -> None:
        self.catalogue = Catalogue(views=views)
        self.result = result or Result(columns=("EMP_ID", "CHILD_NAME"), rows=((1, "Bat"),), truncated=False)
        self.executed: list[str] = []

    def catalogue_for(self, user: object) -> Catalogue:
        return self.catalogue

    def execute(self, user: object, query: Any, limits: Any) -> Result:
        self.executed.append(query.sql)
        return self.result

    def cancel(self, user: object) -> None:
        pass


@pytest.fixture
def switched_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The setting is on and the governed database is ready; no database is touched and no examples are read."""
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)
    monkeypatch.setattr(sqlanswer, "examples_for", lambda catalogue, question: ())


def _ask(provider: FakeProvider, host: FakeHost) -> SqlAnswer:
    return sql_answer(FAKE_USER, QUESTION, TODAY, provider, host)  # type: ignore[arg-type]


@pytest.mark.django_db
def test_setting_defaults_to_off_in_the_database() -> None:
    provider = FakeProvider([])
    answer = sql_answer(FAKE_USER, QUESTION, TODAY, provider, FakeHost((CHILDREN,)))  # type: ignore[arg-type]

    assert answer.status == "off"
    assert provider.calls == []


def test_off_never_calls_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)
    provider = FakeProvider([])

    answer = _ask(provider, FakeHost((CHILDREN,)))

    assert answer.status == "off"
    assert provider.calls == []


def test_unavailable_when_the_governed_database_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: False)
    provider = FakeProvider([])

    answer = _ask(provider, FakeHost((CHILDREN,)))

    assert answer.status == "unavailable"
    assert provider.calls == []


def test_unavailable_when_catalogue_is_empty(switched_on: None) -> None:
    provider = FakeProvider([])

    answer = _ask(provider, FakeHost(()))

    assert answer.status == "unavailable"
    assert provider.calls == []


def test_ok_path_returns_rows_explanation_and_sql(switched_on: None) -> None:
    provider = FakeProvider([{"sql": GOOD_SQL}])
    host = FakeHost((CHILDREN,))

    answer = _ask(provider, host)

    assert answer.status == "ok"
    assert answer.reason == ""
    assert answer.columns == ("EMP_ID", "CHILD_NAME")
    assert answer.rows == ((1, "Bat"),)
    assert answer.row_count == 1
    assert answer.explanation is not None
    assert answer.explanation.row_count == 1
    assert "GOV_CHILDREN" in answer.sql
    assert answer.sql == answer.explanation.sql
    assert answer.salary is False
    assert host.executed == [answer.sql]
    assert len(provider.calls) == 1


def test_rows_are_tidied_and_explained_from_the_raw_result(switched_on: None) -> None:
    raw = Result(columns=("EMP_ID", "AMOUNT"), rows=((1, Decimal("1.005")),), truncated=False)
    provider = FakeProvider([{"sql": "SELECT EMP_ID, AMOUNT FROM GOV_CHILDREN"}])

    answer = _ask(provider, FakeHost((CHILDREN,), raw))

    assert answer.status == "ok"
    assert answer.rows == ((1, Decimal("1.01")),)
    assert answer.explanation is not None
    assert Warning.MONEY_ROUNDED in answer.explanation.warnings


def test_one_retry_after_a_refusal_then_ok(switched_on: None) -> None:
    provider = FakeProvider([{"sql": "SELECT EMP_ID FROM GOV_NOPE"}, {"sql": GOOD_SQL}])
    host = FakeHost((CHILDREN,))

    answer = _ask(provider, host)

    assert answer.status == "ok"
    assert len(provider.calls) == 2
    assert host.executed == [answer.sql]  # the refused query never reached the host


def test_retry_gets_the_refusal_reason_and_the_same_catalogue_text(switched_on: None) -> None:
    provider = FakeProvider([{"sql": "SELECT EMP_ID FROM GOV_NOPE"}, {"sql": GOOD_SQL}])

    _ask(provider, FakeHost((CHILDREN,)))

    first_system, first_user, _ = provider.calls[0]
    second_system, second_user, _ = provider.calls[1]
    assert MISSING_VIEW not in first_user
    assert MISSING_VIEW in second_user
    assert second_system == first_system
    assert "GOV_CHILDREN" in second_system


def test_two_refusals_give_refused_with_the_second_reason(switched_on: None) -> None:
    provider = FakeProvider([{"sql": "SELECT EMP_ID FROM GOV_NOPE"}, {"sql": "SELECT EMP_ID FROM GOV_NOPE2"}])
    host = FakeHost((CHILDREN,))

    answer = _ask(provider, host)

    assert answer.status == "refused"
    assert answer.reason == "Table GOV_NOPE2 is not a governed view you may use."
    assert answer.rows == ()
    assert answer.explanation is None
    assert len(provider.calls) == 2
    assert host.executed == []


def test_sql_naming_a_real_table_gets_one_retry_then_is_refused(switched_on: None) -> None:
    real_table = "SELECT EMP_ID FROM IHR_EMPLOYEE"
    provider = FakeProvider([{"sql": real_table}, {"sql": real_table}])
    host = FakeHost((CHILDREN,))

    answer = _ask(provider, host)

    assert answer.status == "refused"
    assert answer.reason == "Table IHR_EMPLOYEE is not a governed view you may use."
    assert len(provider.calls) == 2
    assert host.executed == []


def test_salary_view_refused_for_a_catalogue_without_it(switched_on: None) -> None:
    salary_sql = "SELECT EMP_ID, BASE_SALARY FROM GOV_SALARY"
    provider = FakeProvider([{"sql": salary_sql}, {"sql": salary_sql}])
    host = FakeHost((CHILDREN,))

    answer = _ask(provider, host)

    assert answer.status == "refused"
    assert answer.reason == "Table GOV_SALARY is not a governed view you may use."
    assert len(provider.calls) == 2
    assert host.executed == []


def test_salary_flag_set_for_salary_views(switched_on: None) -> None:
    provider = FakeProvider([{"sql": "SELECT EMP_ID, BASE_SALARY FROM GOV_SALARY"}])

    answer = _ask(provider, FakeHost((CHILDREN, SALARY)))

    assert answer.status == "ok"
    assert answer.salary is True


def test_provider_error_is_refused_not_raised(switched_on: None) -> None:
    provider = FakeProvider([ProviderError("the key sk-secret-123 was rejected by the server")])
    host = FakeHost((CHILDREN,))

    answer = _ask(provider, host)

    assert answer.status == "refused"
    assert "ProviderError" in answer.reason
    assert "sk-secret-123" not in answer.reason
    assert "server" not in answer.reason
    assert len(provider.calls) == 1
    assert host.executed == []


def test_provider_error_on_the_retry_is_refused_not_raised(switched_on: None) -> None:
    provider = FakeProvider([{"sql": "SELECT EMP_ID FROM GOV_NOPE"}, ProviderError("timeout")])

    answer = _ask(provider, FakeHost((CHILDREN,)))

    assert answer.status == "refused"
    assert "ProviderError" in answer.reason
    assert len(provider.calls) == 2


def test_an_empty_query_means_cannot_answer_and_is_not_retried(switched_on: None) -> None:
    # The model says "" when the views the asker may see cannot answer. A retry made it drop the part it could not
    # answer and return a different, partial answer, so one call is made and nothing is run.
    provider = FakeProvider([{"sql": ""}])
    host = FakeHost((CHILDREN,))

    answer = _ask(provider, host)

    assert answer.status == "refused"
    assert answer.reason == sqlanswer.NOT_ANSWERABLE_REASON
    assert answer.sql == ""
    assert len(provider.calls) == 1
    assert host.executed == []


def test_at_most_two_provider_calls_per_question(switched_on: None) -> None:
    # Two replies only: a third call would hit pytest.fail inside the fake and fail the test.
    provider = FakeProvider([{"sql": "SELECT EMP_ID FROM GOV_NOPE"}, {"sql": "SELECT EMP_ID FROM GOV_NOPE"}])

    _ask(provider, FakeHost((CHILDREN,)))

    assert len(provider.calls) == 2


@pytest.mark.django_db
def test_sqlanswer_passes_examples_for_the_askers_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)
    VerifiedQuery.objects.create(
        question="Хүүхдийн тоо", sql=GOOD_SQL, views="GOV_CHILDREN", status=VerifiedStatus.APPROVED
    )
    VerifiedQuery.objects.create(
        question="Хүүхдийн цалин",
        sql="SELECT EMP_ID FROM GOV_SALARY",
        views="GOV_SALARY",
        status=VerifiedStatus.APPROVED,
    )
    provider = FakeProvider([{"sql": GOOD_SQL}])

    answer = _ask(provider, FakeHost((CHILDREN,)))

    assert answer.status == "ok"
    system, _, _ = provider.calls[0]
    assert "Хүүхдийн тоо" in system
    assert "Хүүхдийн цалин" not in system
    assert "GOV_SALARY" not in system
