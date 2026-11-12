"""Tests for the SQL answer card's text helpers (Task 13): cell formats, the plain-words explanation and the
caution line. Pure functions: no request, no rows written."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlcore.explain import Explanation, Warning

from assistant.sqlanswer import SqlAnswer
from assistant.sqltext import CARD_ROWS, caution_line, cell_text, explanation_lines, is_number

# The assistant conftest's session fixture reads CompanySettings: the database must be set up first, or a
# pure test that runs first in the session hits the wrong database. These tests use no rows.
pytestmark = pytest.mark.django_db


def _answer(explanation: Explanation | None, rows: int = 3) -> SqlAnswer:
    return SqlAnswer(
        status="ok",
        reason="",
        columns=("N",),
        rows=tuple((index,) for index in range(rows)),
        sql="SELECT 1 FROM GOV_CHILDREN",
        explanation=explanation,
        row_count=rows,
        salary=False,
    )


def _explanation(
    views: tuple[str, ...] = ("GOV_CHILDREN",),
    warnings: tuple[Warning, ...] = (),
    rows: int = 3,
) -> Explanation:
    return Explanation(
        views=views,
        filters=(),
        group_by=(),
        aggregates=(),
        row_count=rows,
        warnings=warnings,
        sql="SELECT 1",
    )


def test_cell_text_formats() -> None:
    assert cell_text(None) == "—"
    assert cell_text(date(2026, 11, 11)) == "2026-11-11"
    assert cell_text(datetime(2026, 11, 11, 9, 30)) == "2026-11-11"
    assert cell_text(Decimal("1234567.89")) == "1 234 567.89"
    assert cell_text(Decimal("5.00")) == "5"
    assert cell_text(42) == "42"
    assert cell_text(True) == "Тийм"
    assert cell_text(False) == "Үгүй"
    assert cell_text("<b>Бат & Дорж</b>") == "<b>Бат & Дорж</b>"


def test_is_number() -> None:
    assert is_number(3)
    assert is_number(Decimal("1.50"))
    assert is_number(2.5)
    assert not is_number(True)  # bool is not a number here
    assert not is_number("12")
    assert not is_number(None)
    assert not is_number(float("inf"))  # not finite: shown as text, not as a right-aligned number
    assert not is_number(float("nan"))


def test_huge_decimals_format_without_an_invalid_operation() -> None:
    # Finding 7: quantize in the default 28-digit context raised InvalidOperation from about 1e26 up.
    assert cell_text(Decimal("1E30")) == "1" + " 000" * 10
    assert cell_text(Decimal("-1E40")) == "-10" + " 000" * 13
    assert cell_text(float("1e30")) == "1" + " 000" * 10


def test_a_value_too_large_even_for_the_wider_context_falls_back_to_plain_text() -> None:
    assert cell_text(Decimal("1E300")) == "1E+300"


def test_non_finite_numbers_are_shown_as_text_and_do_not_crash() -> None:
    assert cell_text(float("inf")) == "inf"
    assert cell_text(float("-inf")) == "-inf"
    assert cell_text(float("nan")) == "nan"
    assert cell_text(Decimal("Infinity")) == "Infinity"


def test_explanation_lines_order_and_warnings() -> None:
    explanation = Explanation(
        views=("GOV_CHILDREN", "GOV_EMPLOYEES"),
        filters=("GOV_EMPLOYEES.DEPARTMENT = 'X'",),
        group_by=("GOV_EMPLOYEES.DEPARTMENT",),
        aggregates=("COUNT(*)",),
        row_count=250,
        warnings=(Warning.JOIN_COUNTS_ROWS, Warning.TRUNCATED, Warning.MONEY_ROUNDED),
        sql="SELECT 1",
    )
    lines = explanation_lines(_answer(explanation, rows=250))
    source = next(i for i, line in enumerate(lines) if line.startswith("Эх сурвалж:"))
    total = lines.index("Нийт 250 мөр.")
    assert source < total
    # SQL fragments (filters, grouping, calculations) are not shown to ordinary users; they sit in the SQL fold.
    assert not any(line.startswith(("Шүүлтүүр:", "Бүлэглэлт:", "Тооцоо:")) for line in lines)
    assert not any("COUNT(" in line or "DEPARTMENT" in line for line in lines)
    warnings = lines[total + 1 :]
    assert len(warnings) == 3  # one sentence per warning, in the order given
    assert "хүний тоо биш, мөрийн тоо" in warnings[0]
    assert "хязгаараас хэтэрсэн" in warnings[1]
    assert "2 оронгоор" in warnings[2]


def test_explanation_falls_back_to_view_name() -> None:
    lines = explanation_lines(_answer(_explanation(views=("GOV_NO_SUCH_VIEW",))))
    assert "Эх сурвалж: GOV_NO_SUCH_VIEW" in lines


def test_explanation_uses_the_view_description_when_there_is_one() -> None:
    lines = explanation_lines(_answer(_explanation(views=("GOV_CHILDREN",))))
    assert any("гэр бүлийн бүртгэлд" in line for line in lines)


def test_empty_result_gets_the_empty_warning() -> None:
    lines = explanation_lines(_answer(_explanation(warnings=(Warning.EMPTY,), rows=0), rows=0))
    assert lines[-1].startswith("Нөхцөлд тохирох мөр олдсонгүй")


def test_caution_line_is_one_fixed_sentence() -> None:
    line = caution_line()
    assert line == caution_line()
    assert "\n" not in line
    assert CARD_ROWS == 100
