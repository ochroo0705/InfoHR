"""Batch A: the columns of the reports in absences, ages, annual_leave, children, development_lists, elders and gifts
that show dates or whole numbers declare their kind, so the rule pop-up offers the operators the table uses."""

import pytest

from reports.kinds import KINDS
from reports.registry import REPORTS

DECLARED: dict[tuple[str, str], str] = {
    ("absences", "start"): "date",
    ("absences", "end"): "date",
    ("away-on-date", "start"): "date",
    ("away-on-date", "end"): "date",
    ("ages", "birth_date"): "date",
    ("annual-leave", "start"): "date",
    ("annual-leave", "end"): "date",
    ("children", "birth_date"): "date",
    ("training", "date"): "date",
    ("skill-tasks", "date"): "date",
    ("complaints", "date"): "date",
    ("health-checks", "date"): "date",
    ("health-checks", "end_date"): "date",
    ("elders", "birth_date"): "date",
    ("gifts-given", "year"): "number",
    ("gifts-given", "date"): "date",
}

# every report built in the modules of batch A
BATCH_A_REPORTS = (
    "ages",
    "elders",
    "children",
    "contacts",
    "engineers",
    "household-income",
    "annual-leave",
    "leave-balance",
    "absences",
    "away-on-date",
    "absence-totals",
    "training",
    "health-checks",
    "skill-tasks",
    "complaints",
    "gifts-given",
    "gifts-due",
)


@pytest.mark.parametrize(("report_key", "column_key"), sorted(DECLARED))
def test_declared_kind(report_key: str, column_key: str) -> None:
    columns = {c.key: c for c in REPORTS[report_key].columns}
    assert columns[column_key].kind == DECLARED[(report_key, column_key)]


def test_declared_kinds_are_known() -> None:
    for report_key in BATCH_A_REPORTS:
        for column in REPORTS[report_key].columns:
            if column.kind:
                assert column.kind in KINDS, f"{report_key}.{column.key} declares {column.kind!r}"
