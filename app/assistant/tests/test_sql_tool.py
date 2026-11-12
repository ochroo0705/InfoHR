"""Tests for the plan's `sql` tool (Task 12d): the parse, the plan prompt line, and the answer path. A plan that picks
`sql` gives an SQL outcome when the SQL answer is ok, and otherwise a logged NONE with the reason. The SQL answer is
replaced by a fake through the `services._sql_answer` seam; the staff table path must not call it."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.template.loader import render_to_string

from assistant import services, sqlanswer
from assistant.entries import HelpEntry
from assistant.models import HelpQuestion, Outcome
from assistant.plan import Plan, parse_plan
from assistant.prompt import PLAN_INSTRUCTION, TOOLS
from assistant.services import ASK_PER_HOUR, answer
from assistant.sqlanswer import SqlAnswer
from assistant.words import FilterWords

DAY = date(2026, 11, 11)
QUESTION = "Хүүхдийн тоо хэд вэ?"
GOOD_SQL = "SELECT COUNT(*) FROM GOV_CHILDREN"


class SqlPlanProvider:
    """A fake provider whose plan() is the Plan it was given. It counts the calls it gets."""

    name = "fake"
    model = "fake-model"

    def __init__(self, plan: Plan) -> None:
        self.table = plan
        self.calls = 0

    def choose(self, question: str, entries: Sequence[HelpEntry], refusals: Sequence[str] = ()) -> Any:
        raise AssertionError("the plan path is used, not choose()")

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
        field_hints: Sequence[Any] = (),
    ) -> Plan:
        self.calls += 1
        return self.table


def _plan(**changes: Any) -> Plan:
    base: dict[str, Any] = {
        "tool": "sql",
        "entry": "",
        "also": "",
        "lead": "",
        "parts": (),
        "unmapped": (),
        "want": "list",
        "chart_kind": "",
        "chart_by": "",
    }
    base.update(changes)
    return Plan(**base)


def _reply(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "tool": "none",
        "entry": "",
        "also": "",
        "lead": "",
        "parts": [],
        "unmapped": [],
        "want": "list",
        "chart_kind": "",
        "chart_by": "",
        "fresh": False,
        "field": "",
        "own": False,
        "leave_type": "",
        "start": "",
        "end": "",
    }
    data.update(changes)
    return data


def _ok(sql: str = GOOD_SQL, rows: int = 3, salary: bool = False) -> SqlAnswer:
    return SqlAnswer(
        status="ok",
        reason="",
        columns=("N",),
        rows=((rows,),),
        sql=sql,
        explanation=None,
        row_count=rows,
        salary=salary,
    )


def _refused(reason: str) -> SqlAnswer:
    return SqlAnswer(
        status="refused", reason=reason, columns=(), rows=(), sql="", explanation=None, row_count=0, salary=False
    )


def test_parse_plan_accepts_the_sql_tool() -> None:
    assert "sql" in TOOLS
    plan = parse_plan(_reply(tool="sql"))
    assert plan.tool == "sql"


def test_unknown_tool_still_becomes_none() -> None:
    assert parse_plan(_reply(tool="sqlx")).tool == "none"
    assert parse_plan(_reply(tool="SELECT * FROM GOV_CHILDREN")).tool == "none"


def test_plan_instruction_has_the_sql_line() -> None:
    assert (
        '- "sql" when the question needs data or a combination the other tools cannot give, such as other records, '
        "joins, totals or comparisons."
    ) in PLAN_INSTRUCTION


@pytest.mark.django_db
def test_sql_plan_with_setting_off_is_none_and_logs_the_reason(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)  # the real sql_answer, switched off
    provider = SqlPlanProvider(_plan())
    result = answer(user, QUESTION, DAY, provider)
    assert result.outcome == Outcome.NONE
    assert result.sql is None
    assert result.tool == "sql"
    assert result.error == sqlanswer.OFF_REASON
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == Outcome.NONE
    assert row.tool == "sql"
    assert row.error == sqlanswer.OFF_REASON
    assert row.sql == ""
    assert row.sql_rows == 0
    assert row.salary_flag is False


@pytest.mark.django_db
def test_sql_plan_ok_returns_sql_outcome_and_logs_sql_rows_and_salary_flag(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    calls: list[tuple[str, date]] = []

    def fake(asker: User, text: str, day: date, provider: Any) -> SqlAnswer:
        calls.append((text, day))
        return _ok(sql=GOOD_SQL, rows=7, salary=True)

    monkeypatch.setattr(services, "_sql_answer", fake)
    result = answer(user, QUESTION, DAY, SqlPlanProvider(_plan()))
    assert result.outcome == Outcome.SQL
    assert result.tool == "sql"
    assert result.sql is not None
    assert result.sql.status == "ok"
    assert result.sql.row_count == 7
    assert calls == [(QUESTION, DAY)]
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == Outcome.SQL
    assert row.tool == "sql"
    assert row.sql == GOOD_SQL
    assert row.sql_rows == 7
    assert row.salary_flag is True
    assert row.error == ""


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["refused", "off", "unavailable"])
def test_sql_refusal_statuses_are_none_with_the_reason(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    user = role_user("hr")
    reason = "Таны асуултыг хариулах боломжгүй. " + "х" * 400  # longer than the log keeps

    def fake(asker: User, text: str, day: date, provider: Any) -> SqlAnswer:
        return SqlAnswer(
            status=status, reason=reason, columns=(), rows=(), sql="", explanation=None, row_count=0, salary=False
        )

    monkeypatch.setattr(services, "_sql_answer", fake)
    result = answer(user, QUESTION, DAY, SqlPlanProvider(_plan()))
    assert result.outcome == Outcome.NONE
    assert result.sql is None
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == Outcome.NONE
    assert row.tool == "sql"
    assert row.error == reason[:300]
    assert row.sql == ""
    assert row.sql_rows == 0


@pytest.mark.django_db
def test_staff_table_questions_are_unchanged(role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch) -> None:
    user = role_user("hr")

    def must_not_run(asker: User, text: str, day: date, provider: Any) -> SqlAnswer:
        raise AssertionError("a staff table question must not reach the SQL answer")

    monkeypatch.setattr(services, "_sql_answer", must_not_run)
    provider = SqlPlanProvider(_plan(tool="staff_table", want="list"))
    result = answer(user, "Ажилчдын жагсаалт", DAY, provider)
    assert result.outcome == Outcome.TABLE
    assert result.tool == "staff_table"
    assert result.sql is None
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == Outcome.TABLE
    assert row.tool == "staff_table"
    assert row.sql == ""
    assert row.sql_rows == 0
    assert row.salary_flag is False


@pytest.mark.django_db
def test_rate_limit_still_applies_to_sql_questions(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    calls: list[int] = []

    def fake(asker: User, text: str, day: date, provider: Any) -> SqlAnswer:
        calls.append(1)
        return _ok()

    monkeypatch.setattr(services, "_sql_answer", fake)
    provider = SqlPlanProvider(_plan())
    outcomes = [answer(user, QUESTION, DAY, provider).outcome for _ in range(ASK_PER_HOUR)]
    assert outcomes == [Outcome.SQL] * ASK_PER_HOUR
    limited = answer(user, QUESTION, DAY, provider)
    assert limited.outcome == Outcome.LIMITED
    assert len(calls) == ASK_PER_HOUR  # the limited question never reaches the SQL answer
    assert provider.calls == ASK_PER_HOUR  # nor the provider


@pytest.mark.django_db
def test_sql_answer_card_renders_a_plain_line(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    monkeypatch.setattr(services, "_sql_answer", lambda asker, text, day, provider: _ok(rows=5))
    result = answer(user, QUESTION, DAY, SqlPlanProvider(_plan()))
    html = render_to_string("assistant/_answer.html", {"result": result})
    assert "data-palette-answer" in html
    assert "5" in html
    assert GOOD_SQL in html  # Task 13: the checked SQL sits in the collapsed «SQL харах» fold


@pytest.mark.django_db
def test_refused_sql_card_renders_the_none_line(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    monkeypatch.setattr(services, "_sql_answer", lambda asker, text, day, provider: _refused("no"))
    result = answer(user, QUESTION, DAY, SqlPlanProvider(_plan()))
    html = render_to_string("assistant/_answer.html", {"result": result})
    assert "Энэ асуултад өгөгдлөөс найдвартай хариулж чадсангүй" in html  # Task 13: the refused line
