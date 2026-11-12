"""The governed SQL fields of the question log (HelpQuestion.sql, sql_rows, salary_flag) and Outcome.SQL."""

import pytest

from assistant.models import HelpQuestion, Outcome

pytestmark = pytest.mark.django_db


def test_outcome_sql_exists() -> None:
    assert Outcome.SQL.value == "sql"
    assert Outcome.SQL.label == "SQL хариулт"  # needs native read


def test_log_row_stores_sql_rows_and_salary_flag() -> None:
    sql = "SELECT COUNT(*) FROM GOV_CHILDREN"
    row = HelpQuestion.objects.create(
        question="хэдэн хүүхэдтэй вэ", outcome=Outcome.SQL, sql=sql, sql_rows=42, salary_flag=True
    )
    row.refresh_from_db()
    assert row.sql == sql
    assert row.sql_rows == 42
    assert row.salary_flag is True


def test_log_row_defaults_for_the_sql_fields() -> None:
    row = HelpQuestion.objects.create(question="q", outcome=Outcome.NONE)
    row.refresh_from_db()
    assert (row.sql, row.sql_rows, row.salary_flag) == ("", 0, False)
