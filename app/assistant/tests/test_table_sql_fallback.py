"""A staff-table answer that left part of the question unapplied falls back to governed SQL (services._table_fell_short).

The SQL answer is replaced by a fake through the `services._sql_answer` seam. The table answer stands whenever SQL
does not answer, and the fallback never runs for a complete table answer, a follow-up, a chart or an "ask"."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from employees.tests.conftest import _no_offboarding_templates  # noqa: F401 (autouse)

from assistant import services
from assistant.models import HelpQuestion, Outcome
from assistant.services import answer
from assistant.sqlanswer import SqlAnswer
from assistant.tests.helpers import hire_one
from assistant.tests.test_services_table import PlanProvider, _table_plan

DAY = date(2026, 11, 12)
QUESTION = "Төрсөн жилээр нь бүлэглэж харуул"
UNMAPPED = ("төрсөн жилээр",)  # the table has no such filter, so the question is only partly applied


def _sql(status: str = "ok") -> SqlAnswer:
    return SqlAnswer(
        status=status,
        reason="" if status == "ok" else "The data you may see cannot answer this question.",
        columns=("BIRTH_YEAR", "PEOPLE"),
        rows=((1990, 3),) if status == "ok" else (),
        sql="SELECT EXTRACT(YEAR FROM BIRTH_DATE) AS BIRTH_YEAR, COUNT(*) AS PEOPLE FROM GOV_EMPLOYEES GROUP BY 1"
        if status == "ok"
        else "",
        explanation=None,
        row_count=1 if status == "ok" else 0,
        salary=False,
    )


@pytest.fixture
def sql_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake(asker: User, text: str, day: date, provider: Any) -> SqlAnswer:
        calls.append(text)
        return _sql("ok")

    monkeypatch.setattr(services, "_sql_answer", fake)
    return calls


def _plan(**changes: Any) -> Any:
    base = _table_plan(parts=(), unmapped=UNMAPPED, want="list")
    return replace(base, **changes)


@pytest.mark.django_db
def test_unmapped_part_on_a_fresh_question_falls_back_to_sql(
    role_user: Callable[[str], User], sql_calls: list[str]
) -> None:
    user = role_user("hr")
    hire_one(user)

    result = answer(user, QUESTION, DAY, PlanProvider(_plan(fresh=True)))

    assert result.outcome == Outcome.SQL
    assert result.tool == "sql"
    assert result.table is None
    assert sql_calls == [QUESTION]
    row = HelpQuestion.objects.get(user=user)
    assert row.outcome == "sql"


@pytest.mark.django_db
def test_no_earlier_answer_counts_as_fresh(role_user: Callable[[str], User], sql_calls: list[str]) -> None:
    user = role_user("hr")
    hire_one(user)

    result = answer(user, QUESTION, DAY, PlanProvider(_plan(fresh=False)), previous="")

    assert result.outcome == Outcome.SQL
    assert len(sql_calls) == 1


@pytest.mark.django_db
def test_sql_that_cannot_answer_leaves_the_table_answer(
    role_user: Callable[[str], User], monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("hr")
    hire_one(user)
    monkeypatch.setattr(services, "_sql_answer", lambda asker, text, day, provider: _sql("refused"))

    result = answer(user, QUESTION, DAY, PlanProvider(_plan(fresh=True)))

    assert result.outcome == Outcome.TABLE
    assert result.table is not None
    assert result.table.not_applied  # the table's own «could not apply» lines are still shown


@pytest.mark.django_db
def test_a_fully_applied_table_answer_never_calls_sql(role_user: Callable[[str], User], sql_calls: list[str]) -> None:
    user = role_user("hr")
    hire_one(user)

    result = answer(user, "Санхүүгийн хэлтэст хэдэн хүн байна", DAY, PlanProvider(_table_plan()))

    assert result.outcome == Outcome.TABLE
    assert sql_calls == []


@pytest.mark.django_db
def test_a_follow_up_never_falls_back(role_user: Callable[[str], User], sql_calls: list[str]) -> None:
    # A refinement depends on the earlier answer's filters, which SQL does not see.
    user = role_user("hr")
    hire_one(user)

    result = answer(user, QUESTION, DAY, PlanProvider(_plan(fresh=False)), previous="department=1")

    assert result.outcome == Outcome.TABLE
    assert sql_calls == []


@pytest.mark.django_db
def test_a_chart_with_no_grouping_of_its_own_keeps_the_table_line(
    role_user: Callable[[str], User], sql_calls: list[str]
) -> None:
    # «график харуул»: nothing the table could not map, only «name a grouping». SQL is not asked.
    user = role_user("hr")
    hire_one(user)

    result = answer(user, "график харуул", DAY, PlanProvider(_plan(fresh=True, want="chart", unmapped=())))

    assert result.outcome == Outcome.TABLE
    assert result.table is not None
    assert result.table.not_applied
    assert sql_calls == []


@pytest.mark.django_db
def test_a_chart_by_a_grouping_the_table_lacks_falls_back(
    role_user: Callable[[str], User], sql_calls: list[str]
) -> None:
    # The planner reads «бүлэглэж» as a chart; the table has no birth-year grouping and the plan left it unmapped.
    user = role_user("hr")
    hire_one(user)

    result = answer(user, QUESTION, DAY, PlanProvider(_plan(fresh=False, want="chart")))

    assert result.outcome == Outcome.SQL
    assert sql_calls == [QUESTION]
