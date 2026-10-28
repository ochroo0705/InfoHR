"""The "needs attention" strip above the employee list."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from accounts.models import User
from django.db.models import Q
from django.urls import reverse
from lists.models import DEATH, MeaningfulEntry
from macs.models import ContactRow

from employees import access
from employees.listing import Row
from employees.models import (
    AttentionDismissal,
    Employee,
    Event,
    EventQuerySet,
    EventType,
    HrOrder,
    OrderState,
    ext_of,
)
from employees.services import events, setup

PROBATION_DAYS = 14
CONTRACT_DAYS = 30
SCHEDULED_DAYS = 14


OVERDUE, DUE, MISSING = 0, 1, 2  # urgency: shown in this order, dated ones by date


# Where a missing-data item is fixed: the salary tab holds the bank, the personal tab's first group the contacts.
ANCHORS = {"bank": "#salary", "emergency": "#personal-basic"}


@dataclass
class Attention:
    employee: Employee | None
    text: str
    kind: str
    urgency: int = MISSING
    due: date | None = None
    url: str = ""  # where a system item links to; employee is None for those

    @property
    def anchor(self) -> str:
        """The employee-page tab (#hash) where this item is fixed; "" opens the default tab."""
        return ANCHORS.get(self.kind, "")

    @property
    def key(self) -> str:
        """Identity for "Мэдлээ": the text carries the date and the overdue wording."""
        return f"{self.kind}:{self.employee.pk if self.employee else 0}:{self.text}"[:300]


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def sees_hr_dates(user: User) -> bool:
    """Whether this user sees the dated items (contract, probation, return, scheduled, waiting).

    Needs the manage, salary or leave right; the leave right counts only once annual leave is configured.
    """
    from leave import access as leave_access  # local import: leave depends on employees, not the reverse
    from leave.services import ledger as leave_ledger

    can_leave = leave_access.can_view(user) and leave_ledger.annual_configured()
    return access.can_manage(user) or access.can_view_salary(user) or can_leave


def probation_end(row: Row) -> date | None:
    ext = ext_of(row.employee)
    return ext.probation_end if ext is not None else None


def contract_end(row: Row) -> date | None:
    return row.job.contract_end if row.job else None


def planned_return(row: Row, today: date) -> date | None:
    """Planned return of a row on long leave today; None for any other row."""
    if row.state != "long_leave":
        return None
    return events.leave_until(row.employee, today)


def dated_events(
    employee_ids: Iterable[int], can_salary: bool, *, start: date | None = None, waiting: bool = False
) -> EventQuerySet:
    """Not cancelled events of these employees. Applied ones on or after `start` (None: no lower bound);
    `waiting=True` gives the changes still waiting for their signed order, and ignores `start`.
    Salary changes only with the salary right."""
    qs = Event.objects.filter(employee_id__in=list(employee_ids), cancelled_at__isnull=True)
    if waiting:
        qs = qs.filter(applied_at__isnull=True)
    else:
        qs = qs.applied()
        if start is not None:
            qs = qs.filter(effective__gte=start)
    if not can_salary:
        qs = qs.exclude(type=EventType.SALARY_CHANGE)
    return qs


def _scheduled(rows: list[Row], today: date, can_salary: bool) -> list[Attention]:
    """Future-dated, not cancelled events: any termination, others within SCHEDULED_DAYS."""
    if not rows:
        return []
    by_pk = {r.employee.pk: r.employee for r in rows}
    horizon = today + timedelta(days=SCHEDULED_DAYS)
    upcoming = dated_events(list(by_pk), can_salary, start=today + timedelta(days=1)).filter(
        Q(type=EventType.TERMINATION) | Q(effective__lte=horizon)
    )
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


def _awaiting(rows: list[Row], today: date, can_salary: bool) -> list[Attention]:
    """Changes waiting for their signed order: one line each, overdue once their date has come."""
    if not rows:
        return []
    by_pk = {r.employee.pk: r.employee for r in rows}
    waiting = dated_events(list(by_pk), can_salary, waiting=True)
    out: list[Attention] = []
    for ev in waiting:
        due = ev.effective <= today
        text = f"{ev.get_type_display()} {_fmt(ev.effective)} — гарын үсэг хүлээж байна"
        if due:
            text += ", хугацаа нь болсон"
        out.append(Attention(by_pk[ev.employee_id], text, "awaiting", OVERDUE if due else DUE, ev.effective))
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
    # Waiting changes use every visible employee, left ones too: a waiting rehire belongs to a left employee.
    awaiting = _awaiting(rows, today, can_salary)
    if not sees_hr_dates(user):
        return _sorted(awaiting + system_items)
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
        pe = probation_end(r)
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
        ce = contract_end(r)
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
        back = planned_return(r, today)
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
    out.extend(awaiting)
    out.extend(system_items)
    return _sorted(out)


def _sorted(out: list[Attention]) -> list[Attention]:
    """Most urgent first: overdue, then due soonest, then missing data; ties by name."""
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
    ("awaiting", DUE): "Гарын үсэг хүлээж буй өөрчлөлт",
    ("awaiting", OVERDUE): "Гарын үсэг хүлээж буй өөрчлөлт — хугацаа нь болсон",
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
