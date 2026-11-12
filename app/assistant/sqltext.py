"""The text of the SQL answer card: cell formats, the plain-words explanation and the caution line.

Plain Python. The card needs no request: the template gets a SqlCard built here (services.Answer.sql_card).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlcore.explain import Warning

if TYPE_CHECKING:
    from assistant.sqlanswer import SqlAnswer

CARD_ROWS = 100  # rows drawn in the card; the card says how many exist

_CENT = Decimal("0.01")

_WARNING_MN: dict[Warning, str] = {
    # needs native read
    Warning.JOIN_COUNTS_ROWS: (
        "Тоо нь холбосон хүснэгтээр бодогдсон тул хүний тоо биш, мөрийн тоо. "
        "Нэг хүн хэд хэдэн мөрт орсон бол давтагдсан байна."
    ),
    # needs native read
    Warning.TRUNCATED: "Мөрийн хязгаараас хэтэрсэн тул эхний хэсгийг л харуулж байна. Бодит нийт илүү байж болно.",
    # needs native read
    Warning.EMPTY: (
        "Нөхцөлд тохирох мөр олдсонгүй. Шүүлтүүр хэт нарийн байж болно, "
        "эсвэл таньд харагдах өгөгдөл байхгүй байж болно."
    ),
    # needs native read
    Warning.MONEY_ROUNDED: "Мөнгөн дүнг 2 оронгоор бөөрөнхийлж харуулав.",
}

# needs native read
_CAUTION_MN = "Энэ хариултыг хиймэл оюун ухаан өгөгдлөөс бичсэн. Дээрх нөхцөл, эх сурвалжийг шалгаж үзнэ үү."


@dataclass(frozen=True)
class SqlCell:
    text: str
    numeric: bool


@dataclass(frozen=True)
class SqlColumn:
    name: str
    numeric: bool  # any drawn row holds a number in this column: the header is right-aligned too


@dataclass(frozen=True)
class SqlCard:
    lines: tuple[str, ...]
    salary: bool
    columns: tuple[SqlColumn, ...]
    rows: tuple[tuple[SqlCell, ...], ...]
    shown: int
    total: int
    sql: str
    caution: str


def cell_text(value: object) -> str:
    """One cell as the card shows it. Money keeps at most 2 decimals; dates are YYYY-MM-DD."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Тийм" if value else "Үгүй"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (Decimal, float)):
        return _decimal_text(value)
    return str(value)


def is_number(value: object) -> bool:
    """True for a finite number that is right-aligned. A bool is not a number here; inf and nan show as text."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, Decimal):
        return value.is_finite()
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def explanation_lines(answer: SqlAnswer) -> list[str]:
    """The plain-words lines of the card: the source, the row count, then one sentence per warning. The filters, the
    grouping and the calculations are SQL fragments (COUNT(CASE WHEN ...)): an ordinary user cannot read them, so they
    are not listed here; the exact SQL is folded away on the workspace page. Without an explanation only the row count
    is given."""
    explanation = answer.explanation
    if explanation is None:
        return [f"Нийт {answer.row_count} мөр."]

    descriptions = _view_descriptions()
    lines: list[str] = []
    sources = [_source_name(name, descriptions) for name in explanation.views]
    if sources:
        lines.append("Эх сурвалж: " + ", ".join(sources))  # needs native read
    lines.append(f"Нийт {explanation.row_count} мөр.")
    lines.extend(_WARNING_MN[warning] for warning in explanation.warnings)
    return lines


def caution_line() -> str:
    """The fixed sentence under every SQL answer: the answer was written from the data, check the conditions."""
    return _CAUTION_MN


def card_of(answer: SqlAnswer) -> SqlCard:
    """Everything the card template draws, computed here so the template needs no Python calls."""
    drawn = answer.rows[:CARD_ROWS]
    cells = tuple(tuple(SqlCell(text=cell_text(value), numeric=is_number(value)) for value in row) for row in drawn)
    columns = tuple(
        SqlColumn(name=str(name), numeric=any(index < len(row) and row[index].numeric for row in cells))
        for index, name in enumerate(answer.columns)
    )
    return SqlCard(
        lines=tuple(explanation_lines(answer)),
        salary=answer.salary,
        columns=columns,
        rows=cells,
        shown=len(cells),
        total=answer.row_count,
        sql=answer.sql,
        caution=caution_line(),
    )


def _decimal_text(value: Decimal | float) -> str:
    number = value if isinstance(value, Decimal) else Decimal(repr(value))
    if not number.is_finite():
        return str(value)
    try:
        # The default 28-digit context cannot hold a value of 1e26 and up with 2 decimals; this one holds 80.
        rounded = number.quantize(_CENT, context=Context(prec=80, rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return str(number)  # too large even for 80 digits: show it as plain text, never fail the card
    text = f"{rounded:,.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(",", " ")


def _view_descriptions() -> dict[str, str]:
    """The Mongolian description of each governed view. A broken description file gives no descriptions (the card
    then shows the view names), it never breaks the answer."""
    from hr_sql.descriptions import load_all

    try:
        return {name: view.description_mn for name, view in load_all().items()}
    except ValueError:
        return {}


def _source_name(name: str, descriptions: dict[str, str]) -> str:
    return descriptions.get(name) or name
