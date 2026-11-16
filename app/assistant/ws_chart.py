"""Chart specs for the assistant workspace: check the spec the AI model returns, and turn rows into a chart payload.

A spec names a chart type, the category column (x), one or more value columns (y), an optional series column
(series_by), a title, a sort and a top-N limit. Every column name is checked against the tab's real result columns.
The payload is the same shape the report's chart reads (see ``app/reports/views.py`` ``_chart_payload``).

Plain Python only. No Django, no HR imports, no database connection.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

CHART_TYPES: tuple[str, ...] = ("bar", "hbar", "stacked_bar", "line", "area", "donut", "pie")
DEFAULT_TOP_N = 12
MAX_TOP_N = 30
OTHER_LABEL = "Бусад"  # the folded rest of the categories: «Other»
CHART_MAX_ROWS = 2000  # rows beyond this are not charted
SORTS: tuple[str, ...] = ("none", "label", "value_desc")
TITLE_MAX = 80
TIME_SERIES_TYPES: frozenset[str] = frozenset({"line", "area"})  # never folded into «Бусад»
KINDS: dict[str, str] = {
    "bar": "bar",
    "hbar": "hbar",
    "stacked_bar": "stacked",
    "line": "line",
    "area": "area",
    "donut": "donut",
    "pie": "pie",
}


@dataclass(frozen=True)
class ChartSpec:
    type: str
    x: str
    y: tuple[str, ...]
    series_by: str = ""
    title: str = ""
    sort: str = "none"
    top_n: int = DEFAULT_TOP_N


def _resolve(name: object, columns: tuple[str, ...]) -> str | None:
    """The column named ``name``, matched case-insensitively, returned as it is spelt in ``columns``. None if no such
    column or the name is not text."""
    if not isinstance(name, str):
        return None
    wanted = name.strip()
    if wanted in columns:
        return wanted
    folded = wanted.casefold()
    for column in columns:
        if column.casefold() == folded:
            return column
    return None


def _top_n(raw: object) -> int:
    """A whole number from 0 to MAX_TOP_N. Booleans, non-numbers or a negative number gives DEFAULT_TOP_N; 0 is kept
    (it means no folding for a time series only; _arrange gives a bar, pie or donut the default); anything above
    MAX_TOP_N is clamped to it."""
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return DEFAULT_TOP_N
    return min(raw, MAX_TOP_N)


def _validate(data: dict[str, Any], columns: tuple[str, ...]) -> ChartSpec | None:
    """Check a decoded spec. Returns None when the type is unknown, a column is unknown, or there is no value column.
    An unknown sort becomes "none"; a missing or bad title becomes "" and a long title is cut to TITLE_MAX."""
    chart_type = data.get("type")
    if not isinstance(chart_type, str) or chart_type not in CHART_TYPES:
        return None
    x = _resolve(data.get("x"), columns)
    if x is None:
        return None

    raw_y = data.get("y")
    if not isinstance(raw_y, list):
        return None
    ys: list[str] = []
    for item in raw_y:
        column = _resolve(item, columns)
        if column is None:
            return None
        if column not in ys:
            ys.append(column)
    if not ys:
        return None

    raw_series = data.get("series_by")
    series_by = ""
    if raw_series not in (None, ""):
        resolved = _resolve(raw_series, columns)
        if resolved is None:
            return None
        series_by = resolved
    if x in ys or (series_by and (series_by == x or series_by in ys)):
        return None  # a column cannot be both the category and a value, or both the series and a value

    raw_title = data.get("title")
    title = raw_title.strip()[:TITLE_MAX] if isinstance(raw_title, str) else ""
    sort = data.get("sort")
    sort = sort if isinstance(sort, str) and sort in SORTS else "none"
    return ChartSpec(chart_type, x, tuple(ys), series_by, title, sort, _top_n(data.get("top_n")))


def chart_spec_from_json(text: str, columns: tuple[str, ...]) -> ChartSpec | None:
    """Read a saved chart spec. None for anything that is not a valid spec against ``columns``. Never raises."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    return _validate(data, columns)


def chart_spec_to_json(spec: ChartSpec | None) -> str:
    """The spec as JSON text, or "" for None."""
    if spec is None:
        return ""
    data = {
        "type": spec.type,
        "x": spec.x,
        "y": list(spec.y),
        "series_by": spec.series_by,
        "title": spec.title,
        "sort": spec.sort,
        "top_n": spec.top_n,
    }
    return json.dumps(data, ensure_ascii=False)


def chart_spec_from_reply(raw: object, columns: tuple[str, ...]) -> ChartSpec | None | Literal["none"]:
    """Check the model's chart reply (a dict, already decoded). ``{"type": "none"}`` means remove the chart and gives
    "none". Anything else is checked the same way as ``chart_spec_from_json``."""
    if not isinstance(raw, dict):
        return None
    if raw.get("type") == "none":
        return "none"
    return _validate(raw, columns)


def _number(value: object) -> float | None:
    """The value as a float. Integers, floats and decimals count; None stays None; anything else, a boolean and a
    NaN or infinite number count as no number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return None
        return number if math.isfinite(number) else None
    return None


def _cell(row: Sequence[object], at: int) -> object:
    return row[at] if at < len(row) else None


def _label(value: object) -> str:
    return "" if value is None else str(value)


def _sum_or_none(values: Iterable[float | None]) -> float | None:
    """The sum of the non-null values; None when there are none."""
    total: float | None = None
    for value in values:
        if value is not None:
            total = value if total is None else total + value
    return total


def _column_numbers(columns: tuple[str, ...], data: Sequence[Sequence[object]], name: str) -> list[float | None] | None:
    """The column's numbers, one per row. None when the column holds text and no number at all (a value column that
    cannot be charted). Empty cells and text cells among numbers stay null."""
    at = columns.index(name)
    raw = [_cell(row, at) for row in data]
    numbers = [_number(value) for value in raw]
    if any(value is not None for value in raw) and all(number is None for number in numbers):
        return None
    return numbers


def _sort_key(value: float | None) -> tuple[bool, float]:
    """Largest first, nulls last."""
    return (value is None, -value if value is not None else 0.0)


def _arrange(
    spec: ChartSpec, labels: list[str], table: list[list[float | None]], keys: list[float | None]
) -> tuple[list[str], list[list[float | None]]]:
    """Sort the categories, then fold the ones beyond top_n into «Бусад». The top categories are chosen by their key
    (largest first) whatever the sort, and the sort only sets the order they are shown in. Folding happens only when
    there are more categories than top_n and top_n > 0; the folded rest is summed per series, nulls skipped.
    Line and area charts are time series: they never fold, so every period stays in the chart."""
    count = len(labels)
    ranked = sorted(range(count), key=lambda c: _sort_key(keys[c]))
    if spec.sort == "label":
        display = sorted(range(count), key=lambda c: labels[c])
    elif spec.sort == "value_desc":
        display = ranked
    else:
        display = list(range(count))

    folded: list[int] = []
    # 0 means "no folding" only for time series; a bar, pie or donut with top_n 0 gets the default top count.
    top_n = spec.top_n if spec.type in TIME_SERIES_TYPES else (spec.top_n or DEFAULT_TOP_N)
    if spec.type not in TIME_SERIES_TYPES and 0 < top_n < count:
        kept = set(ranked[:top_n])
        folded = [c for c in range(count) if c not in kept]
        display = [c for c in display if c in kept]

    out_labels = [labels[c] for c in display]
    out_rows = [table[c] for c in display]
    if folded:
        series_count = len(table[0])
        out_labels.append(OTHER_LABEL)
        out_rows.append([_sum_or_none(table[c][k] for c in folded) for k in range(series_count)])
    return out_labels, out_rows


def _payload(
    spec: ChartSpec,
    names: dict[str, str],
    labels: list[str],
    values: list[float | None],
    series: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "kind": KINDS[spec.type],
        "labels": labels,
        "values": values,
        "money": False,
        "percent": False,
        "value_label": names.get(spec.y[0], spec.y[0]),
        "series": series,
        "hrefs": [],
    }


def _plain_payload(
    spec: ChartSpec,
    columns: tuple[str, ...],
    data: list[Sequence[object]],
    labels: list[str],
    names: dict[str, str],
) -> dict[str, Any] | None:
    """One point per row. With several value columns, each one is a series; the values are the first column's."""
    numbers: list[list[float | None]] = []
    for name in spec.y:
        column = _column_numbers(columns, data, name)
        if column is None:
            return None
        numbers.append(column)
    table = [[column[c] for column in numbers] for c in range(len(data))]
    out_labels, out_rows = _arrange(spec, labels, table, [row[0] for row in table])
    cols = [[row[k] for row in out_rows] for k in range(len(spec.y))]
    series: list[dict[str, Any]] = []
    if len(spec.y) > 1:
        series = [{"label": names.get(y, y), "values": cols[k]} for k, y in enumerate(spec.y)]
    return _payload(spec, names, out_labels, cols[0], series)


def _series_payload(
    spec: ChartSpec,
    columns: tuple[str, ...],
    data: list[Sequence[object]],
    labels: list[str],
    names: dict[str, str],
) -> dict[str, Any] | None:
    """Categories by label; one series per distinct series_by value. Cells with the same category and series are
    summed. The values are each category's total across the series, and the first value column is the one charted."""
    numbers = _column_numbers(columns, data, spec.y[0])
    if numbers is None:
        return None
    series_at = columns.index(spec.series_by)
    category_index: dict[str, int] = {}
    series_index: dict[str, int] = {}
    cells: dict[tuple[int, int], float] = {}
    for label, row, number in zip(labels, data, numbers, strict=True):
        series_label = _label(_cell(row, series_at))
        c = category_index.setdefault(label, len(category_index))
        s = series_index.setdefault(series_label, len(series_index))
        if number is not None:
            cells[(c, s)] = cells.get((c, s), 0.0) + number
    table = [[cells.get((c, s)) for s in range(len(series_index))] for c in range(len(category_index))]
    out_labels, out_rows = _arrange(spec, list(category_index), table, [_sum_or_none(row) for row in table])
    series = [
        {"label": series_label, "values": [row[k] for row in out_rows]} for k, series_label in enumerate(series_index)
    ]
    return _payload(spec, names, out_labels, [_sum_or_none(row) for row in out_rows], series)


def build_payload(
    spec: ChartSpec,
    columns: tuple[str, ...],
    rows: Sequence[Sequence[object]],
    names: dict[str, str],
) -> dict[str, Any] | None:
    """The chart payload for ``rows`` (the query result, in ``columns`` order), or None when there is nothing to chart:
    no rows, a column the spec names is missing, or a value column holds text and no numbers. Only the first
    CHART_MAX_ROWS rows are used. ``names`` maps a column to its heading, for value_label and series labels."""
    if spec.type not in KINDS or spec.x not in columns:
        return None
    if any(name not in columns for name in spec.y):
        return None
    if spec.series_by and spec.series_by not in columns:
        return None
    width = len(columns)
    # rows that are not lists or tuples, or are shorter than the columns, are skipped
    usable: list[Sequence[object]] = [row for row in rows if isinstance(row, (list, tuple)) and len(row) >= width]
    data = usable[:CHART_MAX_ROWS]
    if not data:
        return None
    x_at = columns.index(spec.x)
    labels = [_label(_cell(row, x_at)) for row in data]
    if spec.series_by:
        return _series_payload(spec, columns, data, labels, names)
    return _plain_payload(spec, columns, data, labels, names)
