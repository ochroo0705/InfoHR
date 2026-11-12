"""The headcount trend («Ажилтны тоо, эргэц сараар»): one row per month with the staff at its end, the hires, the
leavers and the turnover. A statistic report: its rows are months, not people, so it has no person column and no
count line.
"""

from calendar import monthrange
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from accounts.models import User
from django.utils import timezone
from employees import access, listing
from employees.services.movements import changes
from macs.models import Employee

from reports.filters import Filters, period_of
from reports.staff_list import kept_rows
from reports.starter import view_template
from reports.types import Column, Report

MAX_MONTHS = 24  # the months one page counts; a longer period shows its last 24
HIRE_KINDS = frozenset({"hire", "rehire"})
LEAVE_KINDS = frozenset({"termination"})


@dataclass(frozen=True)
class MonthRow:
    month: str  # "2026-03"
    headcount: int  # people working on the month's last day (today for the current month)
    hired: int  # hire and rehire changes dated in the month
    left: int  # termination changes dated in the month
    net: int  # hired - left
    turnover: Decimal | None  # left / average headcount * 100, one decimal; None when the average is 0


def month_ends(start: date, end: date, today: date) -> list[date]:
    """The last day of every month from `start`'s month to `end`'s month, never after `today` (the current month ends
    today; later months are left out), at most the last MAX_MONTHS of them."""
    ends: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        last = date(year, month, monthrange(year, month)[1])
        if last > today:
            if (year, month) != (today.year, today.month):
                break  # a month after today's: not counted yet
            last = today
        ends.append(last)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return ends[-MAX_MONTHS:]


def _headcount(user: User, f: Filters, day: date) -> int:
    """The people working on `day` with the page's branch and department filters: one staff read."""
    working = replace(Filters(), state="working", as_of=day, branch=f.branch, department=f.department)
    return len(kept_rows(user, working)[0])


def rows(user: User, f: Filters) -> list[MonthRow]:
    """One row per month of the period (see month_ends). Hires and leavers come from one read of the changes."""
    start, end = period_of(f)
    ends = month_ends(start, end, timezone.localdate())
    if not ends:
        return []
    first_day = ends[0].replace(day=1)
    people = access.visible_employees(user).exclude(emptype__in=listing.NEVER_WORKED)
    if f.branch is not None:
        people = people.filter(branch_id=f.branch)
    found = changes(people, first_day, ends[-1], HIRE_KINDS | LEAVE_KINDS)
    hired: Counter[tuple[int, int]] = Counter()
    left: Counter[tuple[int, int]] = Counter()
    for change in found:
        if f.department is not None and (change.department is None or change.department.pk != f.department):
            continue
        key = (change.day.year, change.day.month)
        if change.kind in HIRE_KINDS:
            hired[key] += 1
        else:
            left[key] += 1

    result: list[MonthRow] = []
    previous = _headcount(user, f, first_day - timedelta(days=1))
    for day in ends:
        count = _headcount(user, f, day)
        key = (day.year, day.month)
        average = Decimal(previous + count) / 2
        turnover = (Decimal(left[key]) * 100 / average).quantize(Decimal("0.1")) if average else None
        result.append(
            MonthRow(
                month=f"{day:%Y-%m}",
                headcount=count,
                hired=hired[key],
                left=left[key],
                net=hired[key] - left[key],
                turnover=turnover,
            )
        )
        previous = count
    return result


COLUMNS: tuple[Column, ...] = (
    Column(key="month", label="Сар", value=lambda r: r.month, kind="text"),
    Column(key="headcount", label="Ажилтны тоо", value=lambda r: r.headcount, numeric=True, kind="number"),
    Column(key="hired", label="Орсон", value=lambda r: r.hired, numeric=True, kind="number"),
    Column(key="left", label="Гарсан", value=lambda r: r.left, numeric=True, kind="number"),
    Column(key="net", label="Цэвэр өөрчлөлт", value=lambda r: r.net, numeric=True, kind="number"),
    Column(key="turnover", label="Эргэц, %", value=lambda r: r.turnover, numeric=True, kind="number"),
)


def _note(f: Filters) -> str:
    return (
        "Сар бүрийн сүүлийн өдрийн ажилтны тоо. Эргэц = тухайн сард гарсан хүний тоо ÷ сарын дундаж ажилтны тоо × 100. "
        "Хамгийн ихдээ сүүлийн 24 сар. "
        "Хуучин програмаас ирсэн, ажлын түүхгүй ажилтныг өнөөдрийн төлвөөр нь тоолно: тэдний өмнөх саруудын тоо болон "
        "ажлаас гарсан нь бүрэн биш байж болно."
    )


REPORT = Report(
    key="headcount-trend",
    title="Ажилтны тоо, эргэц сараар",
    filters=("branch", "department", "period"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=rows,
    needs=("macs.view_employees",),
    source=Employee,
    group_options=("month",),
    shows_count=False,  # the rows are months, not people
    note=_note,
    layouts=("chart",),
    templates=(
        view_template("Ажилтны тоо (шугаман)", layout="chart", lby="month", lval="headcount:sum", lchart="line"),
        view_template("Эргэц, % (шугаман)", layout="chart", lby="month", lval="turnover:sum", lchart="line"),
    ),
)
