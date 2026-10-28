"""C2 «Чөлөөний тайлан»: each person's leave per leave type.

Types that use the annual balance get one row per person (the C1 population) for the work year that contains the
as-of date; the numbers come from `ledger.periods` through `annual_leave.annual_lines`, so they match C1 and the
employee page. Every other type gets a row only when the person has a counted leave of that type starting in the as-of
date's calendar year; it shows the days taken and no balance. Nothing here writes or changes the ledger.
"""

from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.utils import timezone
from leave.services import ledger, rows
from macs.models import LeaveTypeRow

from reports.annual_leave import Line as C1Line
from reports.annual_leave import annual_lines
from reports.filters import Filters
from reports.leave_common import LEAVE_NEEDS, Person, detail_url
from reports.types import Column, Report

NOTE = (
    "Ээлжийн амралтын төрөл: эрх, эдэлсэн, үлдэгдэл (ажлын жилээр). Бусад төрөл: тухайн оны эдэлсэн хоног, үлдэгдэлгүй."
)
NO_BALANCE = "үлдэгдэл тооцохгүй"
NO_PERIOD = "Ажлын жилийн эрх бүртгэгдээгүй"


@dataclass(frozen=True)
class Line:
    person: Person
    leave_type: LeaveTypeRow
    granted: int | None  # None for types with no balance, and for an annual type with no period
    taken: int | None  # None only for an annual type with no period
    left: int | None  # None for types with no balance, and for an annual type with no period
    counts_balance: bool  # True for annual types
    has_period: bool = True  # False only for an annual type when no work year contains the as-of date


def _annual_line(c1: C1Line, annual_type: LeaveTypeRow) -> Line:
    """The annual row of one person; `c1.period` is None when no work year contains the as-of date."""
    period = c1.period
    return Line(
        person=c1.person,
        leave_type=annual_type,
        granted=period.granted if period is not None else None,
        taken=period.taken if period is not None else None,
        left=period.left if period is not None else None,
        counts_balance=True,
        has_period=period is not None,
    )


def _other_lines(f: Filters, by_person: dict[int, Person], year: int) -> list[Line]:
    """Per person and other leave type: days taken by counted leaves that start in `year`."""
    if not by_person:
        return []
    totals: dict[tuple[int, int], tuple[LeaveTypeRow, int]] = {}
    for lv in rows.leaves(employee_ids=list(by_person), start=date(year, 1, 1), end=date(year, 12, 31)):
        if not lv.counts or lv.type_ext.uses_annual_balance:
            continue
        if lv.start.year != year or (f.leave_type is not None and lv.leave_type.pk != f.leave_type):
            continue
        key = (lv.employee_id, lv.leave_type.pk)
        leave_type, days = totals.get(key, (lv.leave_type, 0))
        totals[key] = (leave_type, days + lv.days)
    out: list[Line] = []
    for (employee_id, _), (leave_type, days) in sorted(totals.items(), key=lambda kv: (kv[0][0], kv[1][0].name)):
        if days > 0:
            out.append(
                Line(
                    person=by_person[employee_id],
                    leave_type=leave_type,
                    granted=None,
                    taken=days,
                    left=None,
                    counts_balance=False,
                )
            )
    return out


def _rows(user: User, f: Filters) -> list[Line]:
    as_of = f.as_of or timezone.localdate()
    c1_lines = [line for line in annual_lines(user, f) if f.employee is None or line.person.employee.pk == f.employee]
    annual = ledger.annual_types()
    lines: list[Line] = []
    # One pooled annual row per person, labelled with the first annual type: the ledger and the employee page pool
    # all annual types into one balance, so C2 does the same (no per-type split). Picking any annual type keeps it.
    annual_ids = {t.pk for t in annual}
    if annual and (f.leave_type is None or f.leave_type in annual_ids):
        lines = [_annual_line(line, annual[0]) for line in c1_lines]
    by_person = {line.person.employee.pk: line.person for line in c1_lines}
    lines += _other_lines(f, by_person, as_of.year)
    order = {pk: i for i, pk in enumerate(by_person)}
    lines.sort(key=lambda line: order[line.person.employee.pk])  # stable: annual row first, then other types
    return lines


def _note_text(line: Line) -> str | None:
    if line.counts_balance:
        return None if line.has_period else NO_PERIOD
    return NO_BALANCE


def _note(f: Filters) -> str:
    """The same grey line whatever the filters: it says how the two kinds of row are counted."""
    return NOTE


COLUMNS: tuple[Column, ...] = (
    Column(key="code", label="Код", value=lambda line: line.person.employee.code),
    Column(
        key="name",
        label="Ажилтан",
        value=lambda line: line.person.employee.full_name,
        href=lambda line: detail_url(line.person.employee),
    ),
    Column(key="department", label="Хэлтэс", value=lambda line: line.person.department),
    Column(key="type", label="Төрөл", value=lambda line: line.leave_type.name),
    Column(key="granted", label="Эрх", value=lambda line: line.granted, numeric=True),
    Column(key="taken", label="Эдэлсэн", value=lambda line: line.taken, numeric=True),
    Column(key="left", label="Үлдэгдэл", value=lambda line: line.left, numeric=True),
    Column(key="note", label="Тайлбар", value=_note_text),
)

REPORT = Report(
    key="leave-balance",
    title="Чөлөөний тайлан",
    filters=("as_of", "department", "leave_type", "employee"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=LEAVE_NEEDS,
    source=None,
    group_options=("department", "type"),
    note=_note,
)
