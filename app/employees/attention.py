"""The "needs attention" strip above the employee list."""

from dataclasses import dataclass
from datetime import date, timedelta

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
    if not (can_manage or can_salary):
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


def split(user: User, found: list[Attention]) -> tuple[list[Attention], list[Attention]]:
    """(shown, hidden by this user's "Мэдлээ"). Keys of items that are gone simply never match."""
    hidden_keys = set(AttentionDismissal.objects.filter(user=user).values_list("key", flat=True))
    return [a for a in found if a.key not in hidden_keys], [a for a in found if a.key in hidden_keys]


def dismiss(user: User, item: Attention) -> None:
    AttentionDismissal.objects.get_or_create(user=user, key=item.key, defaults={"employee": item.employee})


def restore(user: User, item: Attention) -> None:
    AttentionDismissal.objects.filter(user=user, key=item.key).delete()
