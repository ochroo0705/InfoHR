"""The numbers behind an assistant chart: the staff table's people counted by one grouping column, as bar or pie data.
The table itself decides the rows, the filters and the groups (reports.table.build_table), so the chart and the table
always count the same people."""

from dataclasses import dataclass, replace

from accounts.models import User
from django.core.exceptions import TooManyFieldsSent
from django.http import QueryDict
from reports.filters import parse_filters
from reports.staff_list import REPORT
from reports.table import allowed_columns, build_table
from reports.types import Column

from assistant.tables import MAX_BASE, can_open_table

CHART_KINDS = ("bar", "pie")


@dataclass(frozen=True)
class ChartData:
    kind: str
    by: str  # a group option key
    by_label: str  # the column label
    labels: tuple[str, ...]
    counts: tuple[int, ...]
    total: int  # the people the table counts; equals sum(counts)


def _column(user: User, kind: str, by: str) -> Column | None:
    """The grouping column when this kind and grouping may be charted for the user (without building any table)."""
    if kind not in CHART_KINDS or by not in REPORT.group_options or not can_open_table(user):
        return None
    return next((c for c in allowed_columns(REPORT, user) if c.key == by), None)


def chart_possible(user: User, kind: str, by: str) -> bool:
    """Whether a chart of this kind and grouping may be offered to the user: the cheap part of `chart_data`."""
    return _column(user, kind, by) is not None


def chart_data(user: User, query: str, kind: str, by: str) -> ChartData | None:
    """The chart for the staff table's `query` grouped by `by`, or None when the kind is unknown, the column is not a
    group option, or the user may not see that column. Labels and counts come from the table's groups; the empty group
    keeps its own label."""
    column = _column(user, kind, by)
    if column is None:
        return None
    try:
        filters = parse_filters(QueryDict(query[:MAX_BASE]))
    except (TooManyFieldsSent, ValueError, UnicodeError):
        filters = parse_filters(QueryDict())  # the address is untrusted: a malformed one means no filters
    table = build_table(REPORT, user, replace(filters, group=by))
    # Biggest group first (a tie keeps the table's order): the bars, the list and the Excel file share this order.
    ranked = sorted(((name, len(rows)) for name, rows in table.groups), key=lambda pair: -pair[1])
    return ChartData(
        kind=kind,
        by=by,
        by_label=column.label,
        labels=tuple(name for name, _ in ranked),
        counts=tuple(count for _, count in ranked),
        total=table.count,
    )
