"""The summary a chart or pivot address adds to print and Excel: the same numbers the screen shows, as a grid."""

from dataclasses import dataclass

from reports import layouts as layouts_mod
from reports.table import Table

CATEGORY = "Ангилал"  # the category column's label when the layout has no category, as the chart table shows
TOTAL = "Нийт"  # the stacked chart's total column
GRAND = "Дүн"  # the totals line of a pivot


@dataclass(frozen=True)
class Summary:
    """The summary grid: its title, the kind of drawing it came from, the header cells, one line per category and the
    totals line (None for a chart). Values are raw (numbers or None), so the sheet keeps them as numbers."""

    title: str
    kind: str  # "bar", "stacked", "line", "donut" for a chart; "pivot" for a pivot
    head: list[str]
    lines: list[list[object]]
    foot: list[object] | None
    money: bool
    masked: bool = False  # True when a money figure was hidden for a small group (the note under the grid)


def summary_of(table: Table) -> Summary | None:
    """None unless the table's layout is chart or pivot and it has rows."""
    spec = table.spec
    if table.count == 0 or spec.layout not in ("chart", "pivot"):
        return None
    by = spec.by.label if spec.by is not None else CATEGORY
    if spec.layout == "chart":
        chart = layouts_mod.build_chart(table, spec)
        if chart.kind == "stacked":
            head = [by, *(s.label for s in chart.series), TOTAL]
            lines = [[point.label, *values, point.value] for point, values in chart.lines]
        else:
            head = [by, chart.value_label]
            lines = [[point.label, point.value] for point in chart.points]
        return Summary(
            title=f"Диаграм: {by} · {chart.value_label}",
            kind=chart.kind,
            head=head,
            lines=lines,
            foot=None,
            money=chart.points[0].money,
            masked=chart.masked,
        )
    pivot = layouts_mod.build_pivot(table, spec)
    first = by if spec.by2 is None else f"{by} / {spec.by2.label}"
    head = [first, *pivot.col_labels, GRAND]
    lines = [
        [label, *cells, total]
        for label, cells, total in zip(pivot.row_labels, pivot.cells, pivot.row_totals, strict=True)
    ]
    return Summary(
        title=f"Хөрвүүлэлт: {first} · {pivot.value_label}",
        kind="pivot",
        head=head,
        lines=lines,
        foot=[GRAND, *pivot.col_totals, pivot.grand],
        money=pivot.money,
        masked=pivot.masked,
    )
