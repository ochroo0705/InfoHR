"""Annual leave entitlement (Labor Law art. 99, order А/191; leave-scope §3)."""

import calendar as cal
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from employees.models import Employee, EventType, JobStatus, LeaveKind

from leave.models import AnnualLeaveRule


def add_months(day: date, months: int) -> date:
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    return date(year, month, min(day.day, cal.monthrange(year, month)[1]))


def employment_start(employee: Employee) -> date:
    rehire = employee.events.filter(type=EventType.REHIRE, cancelled_at__isnull=True).order_by("-effective").first()
    return rehire.effective if rehire else employee.first_hire_date


def year_starts(employee: Employee, until: date) -> list[date]:
    start = employment_start(employee)
    out: list[date] = []
    n = 0
    while (d := add_months(start, 12 * n)) <= until:
        out.append(d)
        n += 1
    return out


def next_year_start(employee: Employee, year_start: date) -> date:
    """Start of the leave year after `year_start`: anniversary-based, so a Feb 29 hire gets Feb 29 again."""
    n = len(year_starts(employee, year_start)) - 1
    return add_months(employment_start(employee), 12 * (n + 1))


def year_start_for(employee: Employee, day: date) -> date:
    starts = year_starts(employee, day)
    if not starts:
        raise ValueError("Ажилд орохоос өмнөх огноо")
    return starts[-1]


def _childcare_starts(employee: Employee) -> set[date]:
    return set(
        employee.events.filter(
            type=EventType.LEAVE_START, reason=LeaveKind.CHILDCARE, cancelled_at__isnull=True
        ).values_list("effective", flat=True)
    )


def service_months(employee: Employee, at: date) -> int:
    childcare = _childcare_starts(employee)
    days = 0
    for rec in employee.job_records.exclude(status=JobStatus.LEFT):
        lower = rec.period.lower
        upper = min(rec.period.upper or at, at)
        if rec.status == JobStatus.LONG_LEAVE and lower in childcare:
            continue
        if upper > lower:
            days += (upper - lower).days
    prior = employee.prior_service_years * 12 + employee.prior_service_months
    return days * 12 // 365 + prior


def rule_for(day: date) -> AnnualLeaveRule:
    rules = AnnualLeaveRule.objects
    rule = rules.filter(effective_from__lte=day).order_by("-effective_from").first()
    if rule is None:  # a year before the first rule row (old hires): use the earliest known rule
        rule = rules.order_by("effective_from").first()
    if rule is None:
        raise LookupError("Ээлжийн амралтын хуулийн тохиргоо алга")
    return rule


@dataclass(frozen=True)
class Entitlement:
    days: Decimal
    breakdown: str


def _is_minor(employee: Employee, year_start: date) -> bool:
    b = employee.birth_date
    age = year_start.year - b.year - ((year_start.month, year_start.day) < (b.month, b.day))
    return age < 18


def entitled(employee: Employee, year_start: date) -> Entitlement:
    rule = rule_for(year_start)
    months = service_months(employee, year_start)
    extra = 0
    for b in sorted(rule.brackets, key=lambda b: b["from_month"]):
        if months >= b["from_month"]:
            extra = b["extra_days"]
    insurance = getattr(employee, "salary_insurance", None)
    disabled = insurance is not None and insurance.has_disability
    if disabled or _is_minor(employee, year_start):
        base, label = rule.base_days_minor_or_disabled, " (хөгжлийн бэрхшээлтэй)" if disabled else " (18-аас доош)"
    else:
        base, label = rule.base_days, ""
    service = f"{months // 12} жил {months % 12} сар ажилласан"
    text = f"{base.normalize():f}{label}" + (f" + {extra}" if extra else "")
    return Entitlement(base + extra, f"{text} ({service})")


def eligible_from(employee: Employee) -> date:
    start = employment_start(employee)
    return add_months(start, rule_for(start).eligibility_months)
