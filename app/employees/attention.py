"""The "needs attention" strip above the employee list."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from accounts.models import User
from django.db.models import Q

from employees import access
from employees.listing import Row
from employees.models import AttentionDismissal, Employee, Event, EventType, SalaryInsurance
from employees.services import events, setup

PROBATION_DAYS = 14
CONTRACT_DAYS = 30
SCHEDULED_DAYS = 14


OVERDUE, DUE, MISSING = 0, 1, 2  # urgency: shown in this order, dated ones by date


@dataclass
class Attention:
    employee: Employee
    text: str
    kind: str
    urgency: int = MISSING
    due: date | None = None

    @property
    def key(self) -> str:
        """Identity for "Мэдлээ": the text carries the date and the overdue wording."""
        return f"{self.kind}:{self.employee.pk}:{self.text}"[:300]


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _scheduled(rows: list[Row], today: date, can_salary: bool) -> list[Attention]:
    """Future-dated, not cancelled events: any termination, others within SCHEDULED_DAYS."""
    if not rows:
        return []
    by_pk = {r.employee.pk: r.employee for r in rows}
    horizon = today + timedelta(days=SCHEDULED_DAYS)
    upcoming = Event.objects.filter(employee_id__in=list(by_pk), cancelled_at__isnull=True, effective__gt=today).filter(
        Q(type=EventType.TERMINATION) | Q(effective__lte=horizon)
    )
    if not can_salary:
        upcoming = upcoming.exclude(type=EventType.SALARY_CHANGE)
    out: list[Attention] = []
    for ev in upcoming:
        e = by_pk[ev.employee_id]
        if ev.type == EventType.TERMINATION:
            out.append(Attention(e, f"Гарах: {_fmt(ev.effective)}", "termination", DUE, ev.effective))
        else:
            out.append(
                Attention(
                    e, f"Төлөвлөсөн: {ev.get_type_display()} {_fmt(ev.effective)}", "scheduled", DUE, ev.effective
                )
            )
    return out


def items(user: User, rows: list[Row], today: date) -> list[Attention]:
    can_manage = access.can_manage(user)
    can_salary = access.can_view_salary(user)
    from leave import access as leave_access  # local import: leave depends on employees, not the reverse
    from leave.services import entitlement as leave_entitlement
    from leave.services import ledger as leave_ledger
    from leave.services.fmt import fmt_days

    can_leave = leave_access.can_view(user)
    if not (can_manage or can_salary or can_leave):
        return []
    rows = [r for r in rows if r.state != "left"]
    with_account: set[int] = set()
    if can_salary:
        with_account = set(
            SalaryInsurance.objects.filter(employee__in=[r.employee for r in rows])
            .exclude(account_no="")
            .values_list("employee_id", flat=True)
        )
    out: list[Attention] = []
    for r in rows:
        e = r.employee
        pe = e.probation_end
        if pe is not None and today <= pe <= today + timedelta(days=PROBATION_DAYS):
            out.append(Attention(e, f"Туршилтын хугацаа {_fmt(pe)}-нд дуусна", "probation", DUE, pe))
        ce = r.job.contract_end if r.job else None
        if ce is not None:
            if today <= ce <= today + timedelta(days=CONTRACT_DAYS):
                out.append(Attention(e, f"Гэрээ {_fmt(ce)}-нд дуусна", "contract", DUE, ce))
            elif ce < today and r.state == "active":
                out.append(Attention(e, f"Гэрээ {_fmt(ce)}-нд дууссан", "contract", OVERDUE, ce))
        back = events.leave_until(e, today) if r.state == "long_leave" else None
        if back is not None and back < today:
            out.append(Attention(e, f"Чөлөөнөөс буцах огноо өнгөрсөн: {_fmt(back)}", "leave", OVERDUE, back))
        elif back is not None and back <= today + timedelta(days=SCHEDULED_DAYS):
            out.append(Attention(e, f"Чөлөөнөөс буцах: {_fmt(back)}", "leave", DUE, back))
        if can_leave and leave_entitlement.employment_start(e) <= today:
            try:  # read-only: a list GET must not write grants; the current year's auto grant is previewed
                year = leave_entitlement.year_start_for(e, today)
                left = leave_ledger.balance(e, year) + leave_ledger.pending_grant(e, year)
            except (LookupError, ValueError):
                left = Decimal(0)
            if left < 0:
                out.append(
                    Attention(e, f"Ээлжийн амралтын үлдэгдэл хасах: {fmt_days(left)} хоног", "leave_balance", OVERDUE)
                )
        if can_manage and e.setup_required and not setup.complete_for(e, user):
            out.append(Attention(e, "Бүрдүүлэлт дутуу", "setup"))
        if access.can_view_personal(user, e) and not (e.emergency_name and e.emergency_phone):
            out.append(Attention(e, "Яаралтай үед холбогдох хүн бүртгээгүй", "emergency"))
        if can_salary and e.pk not in with_account:
            out.append(Attention(e, "Банкны мэдээлэл бүртгээгүй", "bank"))
    out.extend(_scheduled(rows, today, can_salary))
    # Most urgent first: overdue, then due soonest, then missing data; ties by name.
    out.sort(key=lambda a: (a.urgency, a.due or date.max, a.employee.full_name, a.employee.pk))
    return out


# Group headings per (kind, urgency); a kind not listed falls back to its first item's text.
GROUP_LABELS: dict[tuple[str, int], str] = {
    ("termination", DUE): "Ажлаас гарах",
    ("scheduled", DUE): "Төлөвлөсөн өөрчлөлт",
    ("probation", DUE): "Туршилтын хугацаа дуусах",
    ("contract", DUE): "Гэрээ дуусах",
    ("contract", OVERDUE): "Гэрээ дууссан",
    ("leave", DUE): "Чөлөөнөөс буцах",
    ("leave", OVERDUE): "Чөлөөнөөс буцах огноо өнгөрсөн",
    ("leave_balance", OVERDUE): "Ээлжийн амралтын үлдэгдэл хасах",
    ("setup", MISSING): "Бүрдүүлэлт дутуу",
    ("emergency", MISSING): "Яаралтай үед холбогдох хүн дутуу",
    ("bank", MISSING): "Банкны мэдээлэл дутуу",
}


@dataclass
class Group:
    kind: str
    urgency: int
    label: str
    items: list[Attention]

    @property
    def dated(self) -> bool:
        """Dated items (and those with their own detail text) show one line each; the rest show as name chips."""
        return any(a.due is not None for a in self.items) or self.kind == "leave_balance"


def group(found: list[Attention]) -> list[Group]:
    """Items grouped by problem, in the order of their most urgent item (`found` is already sorted)."""
    groups: dict[tuple[str, int], Group] = {}
    for a in found:
        key = (a.kind, a.urgency)
        if key not in groups:
            groups[key] = Group(a.kind, a.urgency, GROUP_LABELS.get(key, a.text), [])
        groups[key].items.append(a)
    return sorted(groups.values(), key=lambda g: g.urgency)


def split(user: User, found: list[Attention]) -> tuple[list[Attention], list[Attention]]:
    """(shown, hidden by this user's "Мэдлээ"). Keys of items that are gone simply never match."""
    hidden_keys = set(AttentionDismissal.objects.filter(user=user).values_list("key", flat=True))
    return [a for a in found if a.key not in hidden_keys], [a for a in found if a.key in hidden_keys]


def dismiss(user: User, item: Attention) -> None:
    AttentionDismissal.objects.get_or_create(user=user, key=item.key, defaults={"employee": item.employee})


def restore(user: User, item: Attention) -> None:
    AttentionDismissal.objects.filter(user=user, key=item.key).delete()
