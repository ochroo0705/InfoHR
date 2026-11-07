"""Footer totals: the address text «col:agg,col:agg» and the aggregates over one column.

Pure functions only. Bad input never raises: a bad pair is dropped.
"""

import math
import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TypeGuard, cast

AGGS = ("sum", "avg", "min", "max", "count")
MAX_PAIRS = 20  # totals in one address
_KEY = re.compile(r"[a-z_]{1,40}")
_CENT = Decimal("0.01")


# ---- the address text ----


def parse_totals(text: str) -> tuple[tuple[str, str], ...]:
    """Read «salary:sum,age:avg». Unknown aggregates and bad keys are dropped, a repeated column keeps its first
    aggregate, and at most MAX_PAIRS pairs are kept. Never raises."""
    if not isinstance(text, str) or not text:
        return ()
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for part in text.split(","):
        column, _, agg = part.partition(":")
        column, agg = column.strip(), agg.strip()
        if not _KEY.fullmatch(column) or agg not in AGGS or column in seen:
            continue
        seen.add(column)
        pairs.append((column, agg))
        if len(pairs) >= MAX_PAIRS:
            break
    return tuple(pairs)


def dump_totals(pairs: Sequence[tuple[str, str]]) -> str:
    """The text of the pairs, read back by parse_totals. Empty text for no pairs."""
    return ",".join(f"{column}:{agg}" for column, agg in pairs)


# ---- the aggregates ----


def aggregate(values: Sequence[object], agg: str) -> object | None:
    """One aggregate over a column. None values are skipped; count counts the rest.

    sum and avg use only numbers (int, float, Decimal; not bool; not NaN or infinity). avg of only ints or
    Decimals is a Decimal rounded to 2 places (half up); avg with a float and no Decimal is a float rounded to 2.
    min and max use only numbers, or only dates (a datetime counts as its date); mixed kinds or text give None.
    None when there is nothing to aggregate, except count, which gives 0. Never raises: an arithmetic error
    (overflow, too many digits for the Decimal precision) or a non-finite result gives None.
    """
    try:
        result = _compute(values, agg)
    except ArithmeticError:
        return None
    if isinstance(result, float) and not math.isfinite(result):
        return None
    if isinstance(result, Decimal) and not result.is_finite():
        return None
    return result


def _compute(values: Sequence[object], agg: str) -> object | None:
    if agg not in AGGS:
        return None
    present = [value for value in values if value is not None]
    if agg == "count":
        return len(present)
    if agg in ("sum", "avg"):
        numbers = [value for value in present if _is_number(value)]
        if not numbers:
            return None
        return _sum(numbers) if agg == "sum" else _avg(numbers)
    return _extreme(present, agg)


def _is_number(value: object) -> TypeGuard[int | float | Decimal]:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return False
    if isinstance(value, Decimal):
        return value.is_finite()
    return not isinstance(value, float) or math.isfinite(value)


def _is_non_finite(value: object) -> bool:
    return isinstance(value, (float, Decimal)) and not _is_number(value)


def _to_decimal(value: int | float | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def _sum(numbers: list[int | float | Decimal]) -> object:
    if any(isinstance(value, Decimal) for value in numbers):
        return sum((_to_decimal(value) for value in numbers), Decimal(0))
    return sum(numbers)


def _avg(numbers: list[int | float | Decimal]) -> object:
    if any(isinstance(value, float) for value in numbers) and not any(isinstance(value, Decimal) for value in numbers):
        return round(sum(numbers) / len(numbers), 2)
    total = sum((_to_decimal(value) for value in numbers), Decimal(0))
    return (total / len(numbers)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _extreme(present: list[object], agg: str) -> object | None:
    """min or max over numbers or over dates; anything else (text, mixed kinds) gives None."""
    present = [value for value in present if not _is_non_finite(value)]  # NaN and infinity are skipped, as in sum
    if not present:
        return None
    pick = min if agg == "min" else max
    if all(_is_number(value) for value in present):
        numbers = cast(list[int | float | Decimal], present)
        return pick(numbers)
    if all(isinstance(value, (date, datetime)) for value in present):
        dates = [value for value in present if isinstance(value, (date, datetime))]
        return pick(_as_date(value) for value in dates)
    return None


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value
