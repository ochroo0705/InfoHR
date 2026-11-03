"""Company figures for the Today page strip: headcount trend, turnover, departments, tenure.

Every number is computed from the rows (and the people) the user may see, never from the whole company. The
trend walks back from today's headcount over the hires and leavers of `services.movements.changes`, the same
source the movement reports use, so the page and the reports agree.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from accounts.models import User
from macs.models import Department

from employees import access, listing, scope
from employees import today as today_facts
from employees.listing import Row
from employees.services.movements import changes

MONTHS = 12
TOP_DEPARTMENTS = 8
OTHER = "Бусад"
UNKNOWN = "Тодорхойгүй"
TENURE_BANDS = ("0–6 сар", "6–12 сар", "1–2 жил", "2–5 жил", "5+ жил")
HIRE_KINDS = frozenset({"hire", "rehire"})
LEAVE_KINDS = frozenset({"termination"})


@dataclass(frozen=True)
class Point:
    label: str  # "YYYY-MM"
    value: float | None


@dataclass(frozen=True)
class Bar:
    label: str
    value: int
    pct: int  # 0-100 of the largest bar


@dataclass(frozen=True)
class Company:
    partial_scope: bool  # the user sees only part of the company
    partial_history: bool  # some working person has no HR job history (old MACS only)
    headcount: list[Point]  # 12 points, oldest first, last = today
    turnover: list[Point]  # 12 calendar months, last = this month so far, % or None
    departments: list[Bar]  # top 8 + «Бусад», largest first
    tenure: list[Bar]  # the five bands, in band order
    hires_month: int
    leavers_month: int


def _month_index(day: date) -> int:
    return day.year * 12 + day.month - 1


def _label(index: int) -> str:
    return f"{index // 12}-{index % 12 + 1:02d}"


def _bars(counts: list[tuple[str, int]]) -> list[Bar]:
    largest = max((v for _, v in counts), default=0)
    return [Bar(name, v, round(v * 100 / largest) if largest else 0) for name, v in counts]


def _departments(working: list[Row]) -> list[Bar]:
    ids = {r.job.department_id for r in working if r.job is not None and r.job.department_id}
    names = Department.objects.in_bulk(ids)
    counts: Counter[str] = Counter()
    for r in working:
        dept_id = r.job.department_id if r.job is not None else None
        dept = names.get(dept_id) if dept_id else None
        counts[(dept.name or UNKNOWN) if dept is not None else UNKNOWN] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    shown, rest = ranked[:TOP_DEPARTMENTS], ranked[TOP_DEPARTMENTS:]
    if rest:
        shown.append((OTHER, sum(v for _, v in rest)))
    return _bars(shown)


def _band(first_hire: date, today: date) -> int:
    months = (today.year - first_hire.year) * 12 + today.month - first_hire.month - (today.day < first_hire.day)
    for index, limit in enumerate((6, 12, 24, 60)):
        if months < limit:
            return index
    return 4


def _tenure(working: list[Row], today: date) -> list[Bar]:
    counts = [0] * len(TENURE_BANDS)
    for r in working:
        if r.employee.first_hire_date is not None:
            counts[_band(r.employee.first_hire_date, today)] += 1
    return _bars(list(zip(TENURE_BANDS, counts, strict=True)))


def company(user: User, rows: list[Row], today: date) -> Company | None:
    """The strip's figures, or None when the user lacks the employee-list right (no strip)."""
    if not user.has_perm("macs.view_employees"):
        return None
    now = today_facts.headcount(rows)
    working = [r for r in rows if r.state in today_facts.WORKING_STATES]

    this_month = _month_index(today)
    first_month = this_month - (MONTHS - 1)
    start = date(first_month // 12, first_month % 12 + 1, 1)
    people = access.visible_employees(user).filter(ext__isnull=False).exclude(emptype__in=listing.NEVER_WORKED)
    found = changes(people, start, today, HIRE_KINDS | LEAVE_KINDS)

    hires: dict[int, set[int]] = {}  # month index -> people hired (once each)
    leavers: dict[int, set[int]] = {}
    hired_on: Counter[int] = Counter()  # month index -> hire changes, for the walk back
    left_on: Counter[int] = Counter()
    for c in found:
        index = _month_index(c.day)
        if c.kind in HIRE_KINDS:
            hires.setdefault(index, set()).add(c.employee.pk)
            hired_on[index] += 1
        else:
            leavers.setdefault(index, set()).add(c.employee.pk)
            left_on[index] += 1

    # closing[i] = headcount at the end of month i (this month: today); walk back one month at a time.
    closing: dict[int, int] = {this_month: now}
    for index in range(this_month, first_month - 1, -1):
        closing[index - 1] = max(0, closing[index] - hired_on[index] + left_on[index])

    months = range(first_month, this_month + 1)
    headcount = [Point(_label(i), closing[i]) for i in months]
    turnover: list[Point] = []
    for i in months:
        average = (closing[i - 1] + closing[i]) / 2
        count = len(leavers.get(i, ()))
        turnover.append(Point(_label(i), round(count * 100 / average, 1) if average else None))

    return Company(
        partial_scope=scope.restriction(user, today) is not None,
        partial_history=any(r.legacy for r in working),
        headcount=headcount,
        turnover=turnover,
        departments=_departments(working),
        tenure=_tenure(working, today),
        hires_month=len(hires.get(this_month, ())),
        leavers_month=len(leavers.get(this_month, ())),
    )
