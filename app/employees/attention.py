"""The "needs attention" strip above the employee list."""

from dataclasses import dataclass
from datetime import date, timedelta

from accounts.models import User
from django.db.models import Q
from django.urls import reverse
from lists.models import DEATH, MeaningfulEntry
from macs.models import ContactRow

from employees import access
from employees.listing import Row
from employees.models import AttentionDismissal, Employee, Event, EventType, HrOrder, OrderState, ext_of
from employees.services import events, setup

PROBATION_DAYS = 14
CONTRACT_DAYS = 30
SCHEDULED_DAYS = 14


OVERDUE, DUE, MISSING = 0, 1, 2  # urgency: shown in this order, dated ones by date


@dataclass
class Attention:
    employee: Employee | None
    text: str
    kind: str
    urgency: int = MISSING
    due: date | None = None
    url: str = ""  # where a system item links to; employee is None for those

    @property
    def key(self) -> str:
        """Identity for "Мэдлээ": the text carries the date and the overdue wording."""
        return f"{self.kind}:{self.employee.pk if self.employee else 0}:{self.text}"[:300]


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


def _death_meaning_missing(user: User) -> list[Attention]:
    """QC 3c: "died" is only recorded once the Lists meaning for death is set; list managers are told."""
    if not user.has_perm("lists.manage_lists") or MeaningfulEntry.get(DEATH) is not None:
        return []
    return [
        Attention(
            None,
            "Жагсаалт: «Нас барсан» шалтгаан тохируулаагүй",
            "lists_death",
            MISSING,
            url=reverse("lists:meaning"),
        )
    ]


def _leave_not_configured(user: User) -> list[Attention]:
    """Leave is visible but no annual leave type is chosen yet: whoever can change the settings is told."""
    from leave import access as leave_access  # local import: leave depends on employees, not the reverse
    from leave.services import ledger as leave_ledger

    if not (leave_access.can_view(user) and leave_access.can_manage_settings(user)):
        return []
    if leave_ledger.annual_configured():
        return []
    return [
        Attention(
            None,
            "Ээлжийн амралтын төрлийг сонгоогүй байна",
            "leave_not_configured",
            MISSING,
            url=reverse("leave:settings"),
        )
    ]


def items(user: User, rows: list[Row], today: date) -> list[Attention]:
    can_manage = access.can_manage(user)
    can_salary = access.can_view_salary(user)
    system_items = _death_meaning_missing(user) + _leave_not_configured(user)
    from leave import access as leave_access  # local import: leave depends on employees, not the reverse
    from leave.services import entitlement as leave_entitlement
    from leave.services import ledger as leave_ledger
    from leave.services.fmt import fmt_days

    can_leave = leave_access.can_view(user) and leave_ledger.annual_configured()
    if not (can_manage or can_salary or can_leave):
        return system_items
    rows = [r for r in rows if r.state != "left"]
    # Emergency contacts are production rows (contacting); an employee with none is listed.
    with_contact = set(
        ContactRow.objects.filter(employee_id__in=[r.employee.pk for r in rows]).values_list("employee_id", flat=True)
    )
    with_account: set[int] = set()
    if can_salary:
        with_account = set(  # the bank account is a production column (Employee.account_no)
            Employee.objects.filter(pk__in=[r.employee.pk for r in rows])
            .exclude(account_no__isnull=True)
            .exclude(account_no="")
            .values_list("pk", flat=True)
        )
    out: list[Attention] = []
    if can_manage:
        for o in HrOrder.objects.filter(employee_id__in=[r.employee.pk for r in rows], state=OrderState.PENDING):
            by_pk = {r.employee.pk: r.employee for r in rows}
            out.append(
                Attention(
                    by_pk[o.employee_id],
                    f"{o.get_order_type_display()} тушаалын дугаар оруулаагүй",
                    "order_number",
                    DUE,
                )
            )
    for r in rows:
        e = r.employee
        ext = ext_of(e)
        pe = ext.probation_end if ext is not None else None
        emptype = r.job.emptype if r.job else None
        if can_manage and emptype == 9 and pe is not None and pe < today:
            out.append(
                Attention(
                    e,
                    f"Туршилтын хугацаа {_fmt(pe)}-нд дууссан — төрөл өөрчлөх тушаал гаргана уу",
                    "probation_ended",
                    OVERDUE,
                    pe,
                )
            )
        if pe is not None and today <= pe <= today + timedelta(days=PROBATION_DAYS):
            out.append(Attention(e, f"Туршилтын хугацаа {_fmt(pe)}-нд дуусна", "probation", DUE, pe))
        ce = r.job.contract_end if r.job else None
        if ce is not None:
            if today <= ce <= today + timedelta(days=CONTRACT_DAYS):
                out.append(Attention(e, f"Гэрээ {_fmt(ce)}-нд дуусна", "contract", DUE, ce))
            elif ce < today and emptype == 5 and can_manage:
                out.append(
                    Attention(
                        e,
                        f"Гэрээ {_fmt(ce)}-нд дууссан — төрөл өөрчлөх тушаал гаргана уу",
                        "contract_ended",
                        OVERDUE,
                        ce,
                    )
                )
            elif ce < today and r.state == "active":
                out.append(Attention(e, f"Гэрээ {_fmt(ce)}-нд дууссан", "contract", OVERDUE, ce))
        back = events.leave_until(e, today) if r.state == "long_leave" else None
        if back is not None and back < today:
            out.append(Attention(e, f"Чөлөөнөөс буцах огноо өнгөрсөн: {_fmt(back)}", "leave", OVERDUE, back))
        elif back is not None and back <= today + timedelta(days=SCHEDULED_DAYS):
            out.append(Attention(e, f"Чөлөөнөөс буцах: {_fmt(back)}", "leave", DUE, back))
        if can_leave and leave_entitlement.has_started(e, today):
            # Read-only: periods() never writes grants, so a list GET stays free of side effects.
            found, _ = leave_ledger.periods(e, today)
            current = next((p for p in found if p.start <= today <= p.end), None)
            if current is not None and current.left < 0:
                out.append(
                    Attention(
                        e, f"Ээлжийн амралтын үлдэгдэл хасах: {fmt_days(current.left)} хоног", "leave_balance", OVERDUE
                    )
                )
            if any(p.doubled for p in found):
                out.append(Attention(e, "Ээлжийн амралт: давхардсан эрх", "leave_doubled", DUE))
        if can_manage and ext is not None and ext.setup_required and not setup.complete_for(e, user):
            out.append(Attention(e, "Бүрдүүлэлт дутуу", "setup"))
        if access.can_view_personal(user, e) and e.pk not in with_contact:
            out.append(Attention(e, "Яаралтай үед холбогдох хүн бүртгээгүй", "emergency"))
        if can_salary and e.pk not in with_account:
            out.append(Attention(e, "Банкны мэдээлэл бүртгээгүй", "bank"))
    out.extend(_scheduled(rows, today, can_salary))
    out.extend(system_items)
    # Most urgent first: overdue, then due soonest, then missing data; ties by name.
    out.sort(
        key=lambda a: (
            a.urgency,
            a.due or date.max,
            a.employee.full_name if a.employee else "",
            a.employee.pk if a.employee else 0,
        )
    )
    return out


# Group headings per (kind, urgency); a kind not listed falls back to its first item's text.
GROUP_LABELS: dict[tuple[str, int], str] = {
    ("termination", DUE): "Ажлаас гарах",
    ("scheduled", DUE): "Төлөвлөсөн өөрчлөлт",
    ("probation", DUE): "Туршилтын хугацаа дуусах",
    ("contract", DUE): "Гэрээ дуусах",
    ("contract", OVERDUE): "Гэрээ дууссан",
    ("order_number", DUE): "Тушаалын дугаар оруулаагүй",
    ("probation_ended", OVERDUE): "Туршилтын хугацаа дууссан",
    ("contract_ended", OVERDUE): "Гэрээ дууссан (төрөл өөрчлөх)",
    ("leave", DUE): "Чөлөөнөөс буцах",
    ("leave", OVERDUE): "Чөлөөнөөс буцах огноо өнгөрсөн",
    ("leave_balance", OVERDUE): "Ээлжийн амралтын үлдэгдэл хасах",
    ("leave_doubled", DUE): "Ээлжийн амралт: давхардсан эрх",
    ("setup", MISSING): "Бүрдүүлэлт дутуу",
    ("emergency", MISSING): "Яаралтай үед холбогдох хүн дутуу",
    ("bank", MISSING): "Банкны мэдээлэл дутуу",
    ("lists_death", MISSING): "Жагсаалтын утга дутуу",
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
    if item.employee is None:  # a system reminder stays until the setting is fixed; a dismissal needs an employee
        return
    AttentionDismissal.objects.get_or_create(user=user, key=item.key, defaults={"employee": item.employee})


def restore(user: User, item: Attention) -> None:
    AttentionDismissal.objects.filter(user=user, key=item.key).delete()
