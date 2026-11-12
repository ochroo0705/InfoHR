"""Tests for the SQL answer card (Task 13): the rendered `assistant/_answer.html` for a `sql` tool answer. The card
is rendered from a services.Answer built by hand, the same way the existing card tests render one. No database."""

from decimal import Decimal

import pytest
from django.template.loader import render_to_string
from sqlcore.explain import Explanation, Warning

from assistant.models import Outcome
from assistant.services import Answer
from assistant.sqlanswer import SqlAnswer

REFUSAL = "Table GOV_SALARY is not a governed view you may use."
ROW_CLASS = 'class="border-t border-slate-200"'

# The assistant conftest's session fixture reads CompanySettings: the database must be set up first, or a
# pure test that runs first in the session hits the wrong database. These tests use no rows.
pytestmark = pytest.mark.django_db


def _ok(
    rows: tuple[tuple[object, ...], ...],
    columns: tuple[str, ...] = ("N",),
    sql: str = "SELECT COUNT(*) FROM GOV_CHILDREN",
    salary: bool = False,
    warnings: tuple[Warning, ...] = (),
) -> SqlAnswer:
    explanation = Explanation(
        views=("GOV_CHILDREN",),
        filters=(),
        group_by=(),
        aggregates=("COUNT(*)",),
        row_count=len(rows),
        warnings=warnings,
        sql=sql,
    )
    return SqlAnswer(
        status="ok",
        reason="",
        columns=columns,
        rows=rows,
        sql=sql,
        explanation=explanation,
        row_count=len(rows),
        salary=salary,
    )


def _render(sql: SqlAnswer) -> str:
    result = Answer(outcome=Outcome.SQL, entry=None, also=None, lead="", tool="sql", sql=sql)
    return render_to_string("assistant/_answer.html", {"result": result})


def test_card_shows_table_header_rows_and_sql() -> None:
    html = _render(_ok(((3, "Бат"), (5, "Дорж")), columns=("Тоо", "Нэр")))
    assert "Өгөгдлөөс гарсан хариулт" in html
    assert ">Тоо<" in html and ">Нэр<" in html
    assert ">3<" in html and ">Дорж<" in html
    assert "SQL харах" in html
    assert "SELECT COUNT(*) FROM GOV_CHILDREN" in html
    assert "Нийт 2 мөр." in html
    assert "Энэ боломж одоогоор идэвхгүй байна" not in html


def test_card_escapes_cell_values_and_sql() -> None:
    evil = "<script>alert(1)</script>"
    html = _render(_ok(((evil,),), sql="SELECT 'PLACEHOLDER' FROM GOV_CHILDREN".replace("PLACEHOLDER", evil)))
    assert evil not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_card_caps_rows_at_100_and_says_how_many_exist() -> None:
    html = _render(_ok(tuple((index,) for index in range(250))))
    assert html.count(ROW_CLASS) == 100
    assert "Эхний 100 мөрийг харуулав." in html
    assert "Нийт 250 мөр." in html


def test_empty_result_row() -> None:
    html = _render(_ok((), columns=("Тоо", "Нэр")))
    assert 'colspan="2"' in html
    assert "py-6 text-center text-slate-500" in html
    assert "Олдсонгүй" in html


def test_numbers_are_right_aligned() -> None:
    html = _render(_ok(((Decimal("1234.50"), "Бат"),), columns=("Цалин", "Нэр")))
    assert 'class="py-1 text-right"' in html
    assert "1 234.5" in html
    assert 'class="py-1 pl-6"' in html  # the text column after the number is not right-aligned


def test_salary_chip_only_when_flagged() -> None:
    assert "Цалингийн мэдээлэл" not in _render(_ok(((1,),), salary=False))
    assert "Цалингийн мэдээлэл" in _render(_ok(((1,),), salary=True))


def test_card_renders_huge_and_non_finite_values_without_error() -> None:
    # Finding 7: a 1E30 money value used to raise InvalidOperation while the card rendered (HTTP 500).
    rows = ((Decimal("1E30"), "a"), (float("1e30"), "b"), (float("inf"), "c"), (float("nan"), "d"))
    html = _render(_ok(rows, columns=("Тоо", "Нэр")))
    assert "1 000 000" in html
    assert ">inf<" in html
    assert ">nan<" in html


def test_join_warning_is_written_out() -> None:
    html = _render(_ok(((1,),), warnings=(Warning.JOIN_COUNTS_ROWS,)))
    assert "хүний тоо биш, мөрийн тоо" in html


def test_off_unavailable_and_refused_lines_do_not_leak_the_reason() -> None:
    lines = {
        "off": "Энэ боломж одоогоор идэвхгүй байна. Байгууллагын тохиргооноос асаана.",
        "unavailable": "Энэ асуултад өгөгдлөөс хариулах боломжгүй байна.",
        "refused": "Энэ асуултад өгөгдлөөс найдвартай хариулж чадсангүй. Асуултаа тодруулаад үзнэ үү.",
    }
    for status, line in lines.items():
        result = Answer(
            outcome=Outcome.NONE,
            entry=None,
            also=None,
            lead="",
            tool="sql",
            sql=None,
            error=REFUSAL,
            sql_status=status,
        )
        html = render_to_string("assistant/_answer.html", {"result": result})
        assert line in html
        assert REFUSAL not in html
        assert "GOV_SALARY" not in html


def test_answer_without_a_sql_status_keeps_the_generic_none_line() -> None:
    result = Answer(outcome=Outcome.NONE, entry=None, also=None, lead="", tool="none")
    html = render_to_string("assistant/_answer.html", {"result": result})
    assert "Энэ асуултад хариулт олдсонгүй" in html
