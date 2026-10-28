"""A9 «Инженер, техникийн ажилтны судалгаа»: the budgeted posts (the old `nazg` table, NazgRow) per kind and position
for a year, against the people in those positions (old CALC_REPNAZG). Main counts the non-contract staff, Temporary
the contract staff. Each person counts once. The budget is kept by the old program; Info HR has no screen for it."""

from collections import Counter
from dataclasses import dataclass

from accounts.models import User
from django.utils import timezone
from macs.models import NazgRow, OccupationKind, Position

from reports import survey_common
from reports.filters import Filters
from reports.survey_common import UNKNOWN
from reports.types import Column, Report

KIND_LABELS: dict[str, str] = {"Main": "Үндсэн", "Temporary": "Түр"}
KIND_ORDER: dict[str, int] = {"Main": 0, "Temporary": 1}
CONTRACT = "yes"  # Employee.contract_flag value of contract staff


@dataclass(frozen=True)
class NazgLine:
    kind: str  # "Main" or "Temporary" (a KIND_LABELS key)
    position: Position
    character: str | None  # the old occupation category code, as stored
    budget: int  # the sum of the budgeted posts for the year
    executed: int  # the people in the position of this kind


def _rows(user: User, f: Filters) -> list[NazgLine]:
    """One line per budget group (kind and position) for the year and branch filters. A position with people
    in it but no budget row has no line."""
    year = f.year or timezone.localdate().year
    budget_rows = NazgRow.objects.filter(year=year)
    if f.branch is not None:
        budget_rows = budget_rows.filter(branch_id=f.branch)

    budget: Counter[tuple[str, int]] = Counter()
    for item in budget_rows:
        budget[(item.kind, item.position_id)] += item.qty

    executed: Counter[tuple[str, int]] = Counter()
    for p in survey_common.people(user, Filters(state="working", branch=f.branch)):
        job = p.row.job
        if job is None or job.position_id is None:
            continue  # no position: nothing to count against
        kind = "Temporary" if p.row.employee.contract_flag == CONTRACT else "Main"
        executed[(kind, job.position_id)] += 1

    positions: dict[int, Position] = Position.objects.in_bulk({pos for _, pos in budget})
    characters: dict[int, str | None] = dict(
        OccupationKind.objects.filter(pk__in={pos for _, pos in budget}).values_list("pk", "character")
    )
    lines = [
        NazgLine(
            kind=kind,
            position=position,
            character=characters.get(pos),
            budget=qty,
            executed=executed[(kind, pos)],
        )
        for (kind, pos), qty in budget.items()
        if (position := positions.get(pos)) is not None  # a budget row whose position is gone has no line
    ]
    lines.sort(key=lambda line: (KIND_ORDER.get(line.kind, 9), line.position.name))
    return lines


COLUMNS: tuple[Column, ...] = (
    Column(key="kind", label="Төрөл", value=lambda x: KIND_LABELS.get(x.kind, UNKNOWN)),
    Column(key="position", label="Албан тушаал", value=lambda x: x.position.name),
    Column(key="character", label="Ангилал (хуучин код)", value=lambda x: x.character),
    Column(key="budget", label="Орон тоо", value=lambda x: x.budget, numeric=True),
    Column(key="executed", label="Гүйцэтгэл", value=lambda x: x.executed, numeric=True),
    Column(key="diff", label="Зөрүү", value=lambda x: x.budget - x.executed, numeric=True),
)


def _note(f: Filters) -> str:
    """The grey line: where the budget comes from."""
    return (
        "Орон тооны бүртгэл хуучин програмаас; Info HR-д оруулах дэлгэц байхгүй. "
        "Харагдах ажилтны тоо нь таны эрхийн хүрээнд."
    )


REPORT = Report(
    key="engineers",
    title="Инженер, техникийн ажилтны судалгаа",
    filters=("year", "branch"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=("macs.view_employees",),
    source=NazgRow,
    group_options=("kind",),
    note=_note,
)
