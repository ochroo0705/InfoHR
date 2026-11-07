"""Footer totals: the address text, the dump, and the aggregates (sum, avg, min, max, count)."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from reports.totals import AGGS, aggregate, dump_totals, parse_totals

# ---- the agreed names and the parser ----


def test_aggregate_names() -> None:
    assert AGGS == ("sum", "avg", "min", "max", "count")


def test_parse_good_text() -> None:
    assert parse_totals("salary:sum,age:avg") == (("salary", "sum"), ("age", "avg"))


def test_parse_strips_whitespace() -> None:
    assert parse_totals(" salary : sum , age:count ") == (("salary", "sum"), ("age", "count"))


@pytest.mark.parametrize("text", ["", None, ",,", " , "])
def test_parse_empty_or_blank_gives_nothing(text: str) -> None:
    assert parse_totals(text) == ()


@pytest.mark.parametrize(
    "text",
    [
        "salary",  # no aggregate
        ":sum",  # no column
        "salary:xyz",  # unknown aggregate
        "salary:SUM",  # aggregates are lower case
        "Salary:sum",  # columns are lower case
        "a-b:sum",  # a dash is not allowed in a column key
        "x" * 41 + ":sum",  # 41 characters is too long
        "salary:sum:extra",  # the aggregate is "sum:extra", unknown
    ],
)
def test_parse_garbage_pairs_are_dropped(text: str) -> None:
    assert parse_totals(text) == ()


def test_parse_drops_unknown_aggregate_and_keeps_the_rest() -> None:
    assert parse_totals("salary:median,age:max") == (("age", "max"),)


def test_parse_repeated_column_keeps_the_first_aggregate() -> None:
    assert parse_totals("salary:sum,salary:max") == (("salary", "sum"),)


def test_parse_key_of_40_characters_is_allowed() -> None:
    key = "a" * 40
    assert parse_totals(f"{key}:sum") == ((key, "sum"),)


def test_parse_at_most_twenty_pairs() -> None:
    names = [f"col_{chr(97 + i)}" for i in range(25)]  # col_a .. col_y, all distinct
    text = ",".join(f"{name}:sum" for name in names)
    pairs = parse_totals(text)
    assert len(pairs) == 20
    assert pairs == tuple((name, "sum") for name in names[:20])


def test_parse_never_raises_on_odd_types() -> None:
    assert parse_totals(123) == ()  # type: ignore[arg-type]
    assert parse_totals([("salary", "sum")]) == ()  # type: ignore[arg-type]


# ---- the dump ----


def test_dump_writes_the_same_text_back() -> None:
    assert dump_totals((("salary", "sum"), ("age", "avg"))) == "salary:sum,age:avg"


def test_dump_empty_is_empty_text() -> None:
    assert dump_totals(()) == ""


def test_dump_then_parse_gives_the_same_pairs() -> None:
    pairs = (("salary", "sum"), ("hired", "max"), ("name", "count"))
    assert parse_totals(dump_totals(pairs)) == pairs


# ---- the aggregates ----


@pytest.mark.parametrize("agg", AGGS)
def test_empty_list_gives_none_except_count(agg: str) -> None:
    expected = 0 if agg == "count" else None
    assert aggregate([], agg) == expected


@pytest.mark.parametrize("agg", AGGS)
def test_all_none_gives_none_except_count(agg: str) -> None:
    expected = 0 if agg == "count" else None
    assert aggregate([None, None], agg) == expected


def test_unknown_aggregate_gives_none() -> None:
    assert aggregate([1, 2], "median") is None


def test_sum_skips_none_and_adds_numbers() -> None:
    assert aggregate([1, 2, None, 3], "sum") == 6


def test_sum_of_decimals_stays_exact() -> None:
    assert aggregate([Decimal("1.10"), Decimal("2.20")], "sum") == Decimal("3.30")


def test_sum_of_int_and_float_is_a_float() -> None:
    result = aggregate([1, 2.5], "sum")
    assert result == 3.5
    assert isinstance(result, float)


def test_sum_mixes_decimal_and_float_without_error() -> None:
    assert aggregate([Decimal("1.10"), 2.5], "sum") == Decimal("3.60")


def test_sum_ignores_text_and_bool() -> None:
    assert aggregate(["a", 2, True], "sum") == 2


def test_sum_ignores_not_a_number_floats() -> None:
    assert aggregate([float("nan"), 2], "sum") == 2


def test_sum_of_only_text_is_none() -> None:
    assert aggregate(["a", "b"], "sum") is None


def test_avg_of_ints_is_a_decimal_rounded_to_two_places() -> None:
    result = aggregate([1, 2], "avg")
    assert result == Decimal("1.50")
    assert isinstance(result, Decimal)


def test_avg_of_decimals_rounds_half_up() -> None:
    # 0.025 rounds to 0.03 with ROUND_HALF_UP (banker's rounding would give 0.02)
    assert aggregate([Decimal("0.00"), Decimal("0.05")], "avg") == Decimal("0.03")


def test_avg_of_decimals_rounds_to_two_places() -> None:
    assert aggregate([Decimal("1.00"), Decimal("2.00"), Decimal("2.00")], "avg") == Decimal("1.67")


def test_avg_of_floats_is_a_float_rounded_to_two() -> None:
    result = aggregate([1.0, 2.0, 2.0], "avg")
    assert result == 1.67
    assert isinstance(result, float)


def test_avg_mixing_decimal_and_float_is_a_decimal() -> None:
    result = aggregate([Decimal("1.00"), 2.0], "avg")
    assert result == Decimal("1.50")
    assert isinstance(result, Decimal)


def test_avg_skips_none_and_text() -> None:
    assert aggregate([None, "x", 4, 6], "avg") == Decimal("5.00")


def test_avg_of_only_text_is_none() -> None:
    assert aggregate(["a", None], "avg") is None


def test_min_and_max_of_numbers() -> None:
    values = [3, Decimal("1.5"), None, 2.25]
    assert aggregate(values, "min") == Decimal("1.5")
    assert aggregate(values, "max") == 3


def test_min_and_max_of_dates() -> None:
    values = [date(2026, 1, 5), date(2025, 3, 1), None]
    assert aggregate(values, "min") == date(2025, 3, 1)
    assert aggregate(values, "max") == date(2026, 1, 5)


def test_max_of_dates_and_datetimes_gives_a_date() -> None:
    result = aggregate([datetime(2026, 1, 5, 10, 30), date(2026, 1, 4)], "max")
    assert result == date(2026, 1, 5)
    assert type(result) is date


def test_min_and_max_of_mixed_numbers_and_dates_are_none() -> None:
    assert aggregate([1, date(2026, 1, 1)], "min") is None
    assert aggregate([1, date(2026, 1, 1)], "max") is None


def test_min_and_max_of_text_are_none() -> None:
    assert aggregate(["b", "a"], "min") is None
    assert aggregate(["2026-01-01", "2025-01-01"], "max") is None


def test_min_and_max_of_text_mixed_with_numbers_are_none() -> None:
    assert aggregate([1, "2"], "max") is None


def test_count_counts_every_value_that_is_not_none() -> None:
    assert aggregate([1, "a", None, Decimal("0"), ""], "count") == 4


def test_count_of_numbers_and_text_alike() -> None:
    assert aggregate(["x", "y"], "count") == 2


# ---- never raises: arithmetic errors and overflow give None ----


@pytest.mark.parametrize(
    ("values", "agg", "expected"),
    [
        ([Decimal("1e28"), Decimal("1e28")], "avg", None),  # too many digits for the Decimal precision
        ([10**40, 1], "avg", None),  # the same for a big int avg
        ([Decimal("1E+999999"), Decimal("1")], "avg", None),  # huge Decimal exponent in avg
        ([Decimal("9E+999999"), Decimal("9E+999999")], "sum", None),  # sum overflows the Decimal context
        ([Decimal("1e28"), Decimal("1e28")], "min", Decimal("1e28")),  # min and max only compare, no error
        ([10**40, 1], "max", 10**40),
        ([Decimal("1E+999999"), Decimal("1")], "min", Decimal("1")),
        ([Decimal("1e28"), Decimal("1e28")], "count", 2),
    ],
)
def test_decimal_and_int_overflow_never_raises(values: list[object], agg: str, expected: object) -> None:
    assert aggregate(values, agg) == expected


@pytest.mark.parametrize("agg", ["sum", "avg"])
def test_big_int_with_float_overflows_to_none(agg: str) -> None:
    assert aggregate([10**400, 1.5], agg) is None


@pytest.mark.parametrize("agg", ["sum", "avg"])
def test_float_overflow_to_inf_gives_none(agg: str) -> None:
    assert aggregate([1e308, 1e308], agg) is None


def test_float_sum_of_huge_values_that_stay_finite_is_kept() -> None:
    assert aggregate([1e308, 1.0], "sum") == 1e308 + 1.0


# ---- NaN is skipped by min and max, as by sum and avg ----


def test_min_and_max_skip_nan() -> None:
    values = [float("nan"), 2, 5]
    assert aggregate(values, "min") == 2
    assert aggregate(values, "max") == 5


def test_min_and_max_skip_decimal_nan() -> None:
    values = [Decimal("NaN"), Decimal("3.5")]
    assert aggregate(values, "min") == Decimal("3.5")
    assert aggregate(values, "max") == Decimal("3.5")


@pytest.mark.parametrize("agg", ["min", "max"])
def test_min_and_max_of_only_nan_is_none(agg: str) -> None:
    assert aggregate([float("nan"), None], agg) is None
