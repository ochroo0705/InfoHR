"""D4 «Нэмэгдэх гүйцэтгэлийн үнэлгээ»: each person's indicators (old `hr_addedvalbudg`, AddedValBudgetRow) for a
year and a quarter, with the monthly norm, the execution, the percent of norm and the weighted percent (the
indicator's weight, AddedValStat.percentm). The three months are the quarter's first, second and third month, as the
old CALC_HRADDEDVALREP2 reads them. The percent scale of the weights is an assumption (OQ-058).

D5 «Ажилчдын гүйцэтгэлийн үнэлгээний нэгтгэл» (`performance-summary`): the same numbers summed per person, the average
of the three months and the KPI step of that average (`kpi_for`). Both reports use
`month_percent` and `_budget_lines`."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from accounts.models import User
from django.utils import timezone
from macs.models import AddedValBudgetRow, AddedValStat, EmployeeGradeRow

from reports import survey_common
from reports.filters import Filters, this_quarter
from reports.survey_common import NEEDS_PERSONAL, Person, on_person
from reports.types import Column, Report

HUNDRED = Decimal(100)
ONE_DECIMAL = Decimal("0.1")


@dataclass(frozen=True)
class MonthResult:
    budget: Decimal  # the norm of the month
    executed: Decimal  # the execution of the month
    percent: Decimal  # executed ÷ norm × 100 (month_percent)
    weighted: Decimal  # percent × the indicator's weight ÷ 100


@dataclass(frozen=True)
class Line:
    person: Person
    stat: AddedValStat | None  # the indicator; None when the budget row points at a missing one
    months: tuple[MonthResult, MonthResult, MonthResult]  # the quarter's first, second and third month


@dataclass(frozen=True)
class Summary:
    person: Person
    perc: tuple[Decimal, Decimal, Decimal]  # the three months: the sum over indicators of percent × weight ÷ 100
    avg: Decimal  # (perc1 + perc2 + perc3) ÷ 3, unrounded: the KPI step reads it
    kpi: Decimal  # the KPI step of avg (kpi_for)
    grade: Decimal | None  # the grade percent (Employee.grade_perc); None without the salary right


# The KPI steps of the old table, in order: (limit, kpi, inclusive). An average below the limit takes the step's kpi;
# an inclusive limit also takes an average equal to it. The first matching step wins; above the last one KPI_ABOVE.
KPI_STEPS: tuple[tuple[Decimal, Decimal, bool], ...] = (
    (Decimal(80), Decimal(-2), False),
    (Decimal(85), Decimal("-1.5"), False),
    (Decimal(90), Decimal(-1), False),
    (Decimal(95), Decimal("-0.5"), False),
    (Decimal(100), Decimal(0), True),  # 95 to 100 inclusive
    (Decimal(105), Decimal("0.5"), True),  # over 100 to 105 inclusive
    (Decimal(110), Decimal(1), True),  # over 105 to 110 inclusive
    (Decimal(115), Decimal("1.5"), True),  # over 110 to 115 inclusive
)
KPI_ABOVE = Decimal(2)  # over 115


def kpi_for(avg: Decimal) -> Decimal:
    """The KPI step (the percent that moves the pay) of an average percent, as the old CALC_HRADDEDVALREP2."""
    for limit, kpi, inclusive in KPI_STEPS:
        if avg < limit or (inclusive and avg == limit):
            return kpi
    return KPI_ABOVE


def month_percent(budget: Decimal, executed: Decimal) -> Decimal:
    """The percent of norm of one month. A zero norm counts 100 when nothing was executed, else 0 (as the old
    procedure)."""
    if budget == 0:
        return HUNDRED if executed == 0 else Decimal(0)
    return executed / budget * HUNDRED


def quarter_of(day: date) -> int:
    """The quarter (1-4) a day falls in."""
    return (day.month - 1) // 3 + 1


def _month(budget: Decimal, executed: Decimal, weight: Decimal) -> MonthResult:
    percent = month_percent(budget, executed)
    return MonthResult(budget=budget, executed=executed, percent=percent, weighted=percent * weight / HUNDRED)


def _one(value: Decimal | None) -> Decimal | None:
    """A percent shown with one decimal."""
    return None if value is None else value.quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP)


def _budget_lines(by_pk: dict[int, Person], year: int, quarter: int) -> list[Line]:
    """One line per budget row of the year for the people in `by_pk`, in their order, then by indicator. Two queries
    (budget rows, indicators) whoever the people are; a person with no rows has no line."""
    order = {pk: i for i, pk in enumerate(by_pk)}
    items = sorted(
        AddedValBudgetRow.objects.filter(year=year, employee_id__in=list(by_pk)),
        key=lambda r: (order[r.employee_id], r.stat),
    )
    stats: dict[int, AddedValStat] = AddedValStat.objects.in_bulk({r.stat for r in items})
    lines: list[Line] = []
    for r in items:
        stat = stats.get(r.stat)
        weight = stat.percentm if stat is not None else Decimal(0)  # a missing indicator counts 0
        first, second, third = (_month(budget, executed, weight) for budget, executed in r.months(quarter))
        lines.append(Line(person=by_pk[r.employee_id], stat=stat, months=(first, second, third)))
    return lines


def _rows(user: User, f: Filters) -> list[Line]:
    """One line per budget row of the year for the people the user may see, in the staff list's name order, then by
    indicator. The employee filter is applied here: the staff selection does not read it."""
    year = f.year or timezone.localdate().year
    quarter = f.quarter or this_quarter()
    # state "all": a person who has left keeps the budget of the year they worked
    by_pk: dict[int, Person] = {
        p.row.employee.pk: p
        for p in survey_common.people(user, Filters(state="all"))
        if f.employee is None or p.row.employee.pk == f.employee
    }
    return _budget_lines(by_pk, year, quarter)


def _person_of(row: Line | Summary) -> Person:
    """The person of a D4 line or a D5 summary (both hold one `person`)."""
    return row.person


# The month keys are letters and underscores only. The address key regex (filters.py `_KEY`) allows no digit, so a
# key such as `p_1` would be dropped from ?cols=, ?sort= and ?group=; the words below keep every key usable.
MONTH_WORDS: tuple[str, str, str] = ("first", "second", "third")


def _month_columns(index: int, word: str) -> tuple[Column, ...]:
    """The four columns of one month of the quarter: `index` 0-2 picks the month, `word` names its keys."""
    label = f"Сар {index + 1}"
    return (
        Column(key=f"b_{word}", label=f"{label}: норм", value=lambda x: x.months[index].budget, numeric=True),
        Column(key=f"e_{word}", label=f"{label}: гүйцэтгэл", value=lambda x: x.months[index].executed, numeric=True),
        Column(key=f"p_{word}", label=f"{label}: хувиар", value=lambda x: _one(x.months[index].percent), numeric=True),
        Column(
            key=f"w_{word}", label=f"{label}: эзлэх %", value=lambda x: _one(x.months[index].weighted), numeric=True
        ),
    )


_PERSON = {c.key: c for c in survey_common.PERSON_COLUMNS}

COLUMNS: tuple[Column, ...] = (
    on_person(_PERSON["code"], _person_of),
    on_person(_PERSON["name"], _person_of),
    on_person(_PERSON["department"], _person_of),
    Column(key="indicator", label="Үзүүлэлт", value=lambda x: x.stat.description if x.stat is not None else None),
    # shown with one decimal; the stored weight keeps two (the note below says so)
    Column(
        key="weight",
        label="Эзлэх хувь",
        value=lambda x: _one(x.stat.percentm) if x.stat is not None else None,
        numeric=True,
    ),
    *_month_columns(0, MONTH_WORDS[0]),
    *_month_columns(1, MONTH_WORDS[1]),
    *_month_columns(2, MONTH_WORDS[2]),
)

NOTE = (
    "Сар 1–3 нь сонгосон улирлын эхний, хоёр дахь, гурав дахь сар. Хувиар = гүйцэтгэл ÷ норм × 100. "
    "Эзлэх хувь нэг аравтын орноор харагдана (хадгалсан утга хоёр орон)."
)


def _note(f: Filters) -> str:
    return NOTE


REPORT = Report(
    key="performance",
    title="Нэмэгдэх гүйцэтгэлийн үнэлгээний тайлан",
    filters=("year", "quarter", "employee"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=NEEDS_PERSONAL,
    source=AddedValBudgetRow,
    group_options=("name",),
    note=_note,
)


# ---- D5: the summary per person --------------------------------------------------------------------------------


def _grades(user: User, ids: list[int]) -> dict[int, Decimal]:
    """The grade percent of each person in one query. Without the salary right nothing is read (the column is
    hidden)."""
    if not user.has_perm("macs.view_salary"):
        return {}
    return dict(EmployeeGradeRow.objects.filter(pk__in=ids).values_list("pk", "grade_perc"))


def _summary_rows(user: User, f: Filters) -> list[Summary]:
    """D5: every working person the filters pass (branch, department), with the three months' percents and the KPI
    step. A person with no budget rows is listed with zeros (the old left join gives 0)."""
    year = f.year or timezone.localdate().year
    quarter = f.quarter or this_quarter()
    persons = survey_common.people(user, Filters(state="working", branch=f.branch, department=f.department))
    by_pk = {p.row.employee.pk: p for p in persons}
    totals: dict[int, list[Decimal]] = {pk: [Decimal(0), Decimal(0), Decimal(0)] for pk in by_pk}
    for line in _budget_lines(by_pk, year, quarter):
        sums = totals[line.person.row.employee.pk]
        for i, month in enumerate(line.months):
            sums[i] += month.weighted
    grades = _grades(user, list(by_pk))
    rows: list[Summary] = []
    for pk, person in by_pk.items():
        p1, p2, p3 = totals[pk]
        avg = (p1 + p2 + p3) / 3
        rows.append(Summary(person=person, perc=(p1, p2, p3), avg=avg, kpi=kpi_for(avg), grade=grades.get(pk)))
    return rows


SUMMARY_COLUMNS: tuple[Column, ...] = (
    on_person(_PERSON["code"], _person_of),
    on_person(_PERSON["name"], _person_of),
    on_person(_PERSON["department"], _person_of),
    Column(key="p_first", label="Сар 1", value=lambda s: _one(s.perc[0]), numeric=True),
    Column(key="p_second", label="Сар 2", value=lambda s: _one(s.perc[1]), numeric=True),
    Column(key="p_third", label="Сар 3", value=lambda s: _one(s.perc[2]), numeric=True),
    Column(key="avg", label="Дундаж", value=lambda s: _one(s.avg), numeric=True),
    Column(key="kpi", label="KPI нөлөөлөх хувь", value=lambda s: s.kpi, numeric=True),
    Column(
        key="grade",
        label="Зэргийн хувь",
        value=lambda s: s.grade,
        needs="macs.view_salary",
        numeric=True,
    ),
)

SUMMARY_NOTE = (
    "Олгох хувь тооцоогүй (хуучин програмын томьёо мэдэгдэхгүй). "
    "Төсвийн мөргүй хүн 0 хувьтай харагдаж, KPI-ийн нөлөө -2 болно (хуучин програм мөн адил)."
)


def _summary_note(f: Filters) -> str:
    return SUMMARY_NOTE


SUMMARY = Report(
    key="performance-summary",
    title="Ажилчдын гүйцэтгэлийн үнэлгээний нэгтгэл",
    filters=("year", "quarter", "branch", "department"),
    columns=SUMMARY_COLUMNS,
    default_columns=tuple(c.key for c in SUMMARY_COLUMNS),
    rows=_summary_rows,
    needs=NEEDS_PERSONAL,
    source=AddedValBudgetRow,
    group_options=("department",),
    note=_summary_note,
)
