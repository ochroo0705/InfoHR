"""Batch B report columns: the date columns declare kind "date", and every declared kind is a known one."""

import pytest

from reports.kinds import KINDS
from reports.registry import REPORTS

# (report key, column key) -> the declared kind, for every column this batch gave a kind to.
DECLARED: dict[tuple[str, str], str] = {
    ("leave-requests", "start"): "date",
    ("leave-requests", "end"): "date",
    ("loans", "date"): "date",
    ("loans", "end_date"): "date",
    ("movements", "day"): "date",
    ("history", "day"): "date",
    ("leavers", "day"): "date",
    ("orders", "date"): "date",
    ("discipline", "date"): "date",
    ("discipline", "end"): "date",
    ("awards", "date"): "date",
}

# Every report built from the batch B modules (their columns are the ones checked for a known kind).
BATCH_REPORTS: tuple[str, ...] = (
    "leave-requests",
    "loans",
    "movements",
    "history",
    "leavers",
    "orders",
    "discipline",
    "awards",
    "performance",
    "performance-summary",
    "accidents",
    "poisoning",
    "sizes",
    "statistics",
)


@pytest.mark.parametrize(("report_key", "column_key"), sorted(DECLARED))
def test_declared_kind(report_key: str, column_key: str) -> None:
    columns = {c.key: c for c in REPORTS[report_key].columns}
    assert columns[column_key].kind == DECLARED[(report_key, column_key)]


def test_every_declared_kind_in_batch_is_known() -> None:
    for report_key in BATCH_REPORTS:
        for column in REPORTS[report_key].columns:
            if column.kind:
                assert column.kind in KINDS, (report_key, column.key)
