"""Column kinds: text, number or date, from the column's flags or from its values."""

from datetime import date, datetime
from decimal import Decimal

from reports.kinds import column_kind
from reports.types import Column


def _col(**kwargs: object) -> Column:
    return Column(key="x", label="X", value=lambda r: r, **kwargs)  # type: ignore[arg-type]


def test_explicit_date_kind_wins_over_values() -> None:
    column = _col(kind="date")
    assert column_kind(column, ["a", "b"]) == "date"


def test_all_date_values_make_a_date_column() -> None:
    assert column_kind(_col(), [date(2026, 1, 1), date(2026, 2, 2), None]) == "date"


def test_int_decimal_and_float_with_none_make_a_number_column() -> None:
    assert column_kind(_col(), [1, None, 2]) == "number"
    assert column_kind(_col(), [Decimal("1.50"), None]) == "number"
    assert column_kind(_col(), [1.5, 2]) == "number"


def test_only_booleans_are_text() -> None:
    assert column_kind(_col(), [True, False, True]) == "text"


def test_mix_of_date_and_text_is_text() -> None:
    assert column_kind(_col(), [date(2026, 1, 1), "илгээсэн"]) == "text"


def test_no_rows_or_only_none_is_text() -> None:
    assert column_kind(_col(), []) == "text"
    assert column_kind(_col(), [None, None]) == "text"


def test_numeric_or_money_flag_is_number_even_without_rows() -> None:
    assert column_kind(_col(numeric=True), []) == "number"
    assert column_kind(_col(money=True), []) == "number"


def test_kind_looks_at_only_the_first_200_values() -> None:
    rows = ["a"] * 200 + [date(2026, 1, 1)] * 100  # 300 rows: the first 200 are text
    assert column_kind(_col(), rows) == "text"


def test_none_rows_do_not_use_up_the_200_value_sample() -> None:
    rows = [None] * 150 + [date(2026, 1, 1)] * 50 + ["a"] * 100  # the first 200 rows hold only 50 values
    assert column_kind(_col(), rows) == "text"


def test_invalid_explicit_kind_falls_through_to_values() -> None:
    assert column_kind(_col(kind="money"), [1, 2]) == "number"


def test_datetime_value_is_a_date() -> None:
    assert column_kind(_col(), [datetime(2026, 1, 1, 9, 30)]) == "date"


def test_bool_mixed_with_ints_is_text() -> None:
    assert column_kind(_col(), [True, 2, 3]) == "text"
