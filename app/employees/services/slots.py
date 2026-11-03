"""Position slots (орон тоо): a hire or rehire needs a free slot for its position, branch, kind and year.

A slot is a row of the budget table `nazg` (macs.NazgRow). Used slots are people counted the way report A9 counts
«гүйцэтгэл» (same kind rule, employees.slot_kind), except that people who start later in the same year count
too, so two future hires cannot both take the last slot. Report A9 counts the people working on one day inside a
user's data scope; this module counts every person whatever the user may see, so it uses its own query.
"""

from collections import defaultdict
from datetime import date
from typing import Any, NamedTuple, cast

from accounts.audit import Category, record_safe
from accounts.models import User
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.db.utils import ProgrammingError
from macs.models import Branch, Employee, NazgRow, Position
from psycopg.types.range import DateRange

from employees.listing import LEGACY_NOT_WORKING
from employees.models import CompanySettings, Event, EventType, JobRecord, JobStatus
from employees.services import macs_writes
from employees.slot_kind import CONTRACT, MAIN, TEMPORARY
from employees.slot_kind import kind_for as kind_for  # the shared rule, re-exported for callers of this module

AUDIT_ACTION_OVERRIDE = "position_slot_overridden"
AUDIT_ACTION_ADDED = "position_slot_added"
AUDIT_ACTION_CHANGED = "position_slot_changed"
AUDIT_ACTION_DELETED = "position_slot_deleted"
KIND_LABELS: dict[str, str] = {MAIN: "Үндсэн", TEMPORARY: "Түр"}


class SlotResult(NamedTuple):
    kind: str
    year: int
    posts: int
    used: int
    free: int


class SlotBlocked(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _rows(position: Position, branch: Branch | None, kind: str, year: int) -> QuerySet[NazgRow]:
    rows = NazgRow.objects.filter(position=position, kind=kind, year=year)
    return rows.filter(branch=branch) if branch is not None else rows.filter(branch__isnull=True)


def _waiting_rehires(year: int, exclude_employee: Employee | None = None) -> list[dict[str, Any]]:
    """The slot keys (`slot_position`, `slot_branch`, `slot_contract`, stored by events.record from what the gate used)
    of rehires recorded but not yet in force (no signed order) that start by the end of `year`: they will take a post,
    so they hold it now. An applied rehire is a job record, a cancelled one holds nothing."""
    waiting = Event.objects.filter(
        type=EventType.REHIRE,
        applied_at__isnull=True,
        cancelled_at__isnull=True,
        effective__lt=date(year + 1, 1, 1),
    )
    if exclude_employee is not None:
        waiting = waiting.exclude(employee=exclude_employee)
    return [e.proposed for e in waiting if e.proposed and e.proposed.get("slot_position") is not None]


def _used(position: Position, branch: Branch | None, kind: str, on: date, exclude_employee: Employee | None) -> int:
    """People of this position, branch and kind who work on `on` or start later in its year, each counted once."""
    contract = Q(contract_flag=CONTRACT)
    people = Employee.objects.filter(contract if kind == TEMPORARY else ~contract)
    people = people.filter(branch=branch) if branch is not None else people.filter(branch__isnull=True)
    if exclude_employee is not None:
        people = people.exclude(pk=exclude_employee.pk)
    window = DateRange(on, date(on.year + 1, 1, 1), "[)")  # from `on` to the end of its year
    with_job = JobRecord.objects.filter(position=position, period__overlap=window).exclude(status=JobStatus.LEFT)
    counted = people.filter(pk__in=with_job.values("employee")).count()
    # People with no HR job history are read from the MACS row, like the staff list does.
    legacy = people.filter(position=position).exclude(emptype__in=LEGACY_NOT_WORKING)
    legacy = legacy.exclude(pk__in=JobRecord.objects.values("employee"))
    held = sum(
        1
        for keys in _waiting_rehires(on.year, exclude_employee)
        if keys["slot_position"] == position.pk
        and keys.get("slot_branch") == (branch.pk if branch is not None else None)
        and kind_for(keys.get("slot_contract")) == kind
    )
    return counted + legacy.count() + held


def check(
    position: Position,
    branch: Branch | None,
    *,
    kind: str,
    on: date,
    exclude_employee: Employee | None = None,
) -> SlotResult:
    """The posts, the people using them and the free slots of this position, branch and kind in the year of `on`."""
    posts = sum(_rows(position, branch, kind, on.year).values_list("qty", flat=True))
    used = _used(position, branch, kind, on, exclude_employee)
    return SlotResult(kind=kind, year=on.year, posts=posts, used=used, free=posts - used)


def no_posts_message(position: Position, branch: Branch, year: int, kind: str) -> str:
    """No post of this kind is planned for this position, branch and year: say which kind, and point to where one is
    added. Shared with the vacancy budget line, so both screens give the same hint."""
    return (
        f"{position.name}, {branch.name}, {KIND_LABELS.get(kind, kind)}, {year} онд орон тоо төлөвлөөгүй байна. "
        "«Орон тооны төлөвлөгөө» хэсэгт нэмнэ үү."
    )


def _blocked_message(position: Position, branch: Branch | None, result: SlotResult) -> str:
    if branch is None:  # a post always belongs to a branch, so a person with none has no post: ask for one
        return (
            f"Орон тоо шалгахын тулд салбар сонгоно уу: {position.name}, {result.year} он. Салбаргүй орон тоо байхгүй."
        )
    if result.posts == 0:  # nothing planned is not «full»: the fix is to add a post, not to free one
        return no_posts_message(position, branch, result.year, result.kind)
    return (
        f"Орон тоо дүүрсэн байна: {position.name}, {branch.name}, "
        f"{KIND_LABELS.get(result.kind, result.kind)}, {result.year} он. "
        f"Орон тоо {result.posts}, ажиллаж буй {result.used}."
    )


def gate(
    *,
    position: Position | None,
    branch: Branch | None,
    contract_flag: str | None,
    on: date,
    override_reason: str,
    by: User,
    employee_label: str = "",
    exclude_employee: Employee | None = None,
) -> None:
    """Refuse the hire when the setting is on and no slot is free; an override right plus a reason lets it through
    and logs it. Call it inside the hire transaction: the matching budget rows are locked before counting (the lock
    lasts to the end of that transaction), so two simultaneous hires cannot both take the last slot."""
    if position is None or not CompanySettings.get().enforce_position_slots:
        return
    kind = kind_for(contract_flag)
    with transaction.atomic():
        list(_rows(position, branch, kind, on.year).select_for_update())
        result = check(position, branch, kind=kind, on=on, exclude_employee=exclude_employee)
    if result.free >= 1:
        return
    reason = override_reason.strip()
    if reason and by.has_perm("employees.override_position_slots"):
        message = f"{employee_label} · " if employee_label else ""
        record_safe(
            Category.HR,
            AUDIT_ACTION_OVERRIDE,
            actor=by,
            message=f"{message}{_blocked_message(position, branch, result)} — {reason}",
            target_type="Орон тоо",
            target_label=position.name,
        )
        return
    raise SlotBlocked(_blocked_message(position, branch, result))


def used_by_key(year: int, on: date) -> dict[tuple[int, int | None, str], int]:
    """`_used` for every position, branch and kind at once (two queries): the people who work on `on` or start later
    in its year, keyed by (position id, branch id, kind). The slot screen reads a whole year with this instead of one
    count per row; `check` stays the rule (a test holds the two equal)."""
    window = DateRange(on, date(on.year + 1, 1, 1), "[)")
    found: dict[tuple[int, int | None, str], int] = defaultdict(int)
    with_job = (
        JobRecord.objects.filter(period__overlap=window)
        .exclude(status=JobStatus.LEFT)
        .values("position_id", "employee__branch_id", "employee__contract_flag")
        .annotate(people=Count("employee", distinct=True))
    )
    for line in with_job:
        found[(line["position_id"], line["employee__branch_id"], kind_for(line["employee__contract_flag"]))] += line[
            "people"
        ]
    legacy = (
        Employee.objects.exclude(pk__in=JobRecord.objects.values("employee"))
        .exclude(emptype__in=LEGACY_NOT_WORKING)
        .filter(position__isnull=False)
        .values("position_id", "branch_id", "contract_flag")
        .annotate(people=Count("pk"))
    )
    for line in legacy:
        found[(line["position_id"], line["branch_id"], kind_for(line["contract_flag"]))] += line["people"]
    for keys in _waiting_rehires(year):  # a rehire waiting for its signed order already holds its post
        found[(keys["slot_position"], keys.get("slot_branch"), kind_for(keys.get("slot_contract")))] += 1
    return dict(found)


WRITE_DENIED_MESSAGE = (
    "Өгөгдлийн сангийн эрх дутуу: nazg хүснэгтэд нэмэх, засах, устгах эрх олгохыг системийн админд хэлнэ үү."
)


class SlotWriteDenied(Exception):
    """The database refused the write to `nazg` (the app's login lacks the grant): tell an admin, no crash."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SlotRowExists(Exception):
    """The kind + year + branch + position already has a row: the user edits it instead of adding a second."""

    def __init__(self, row: NazgRow) -> None:
        super().__init__("slot row exists")
        self.row = row


def _describe(position: Position, branch: Branch, kind: str, year: int) -> str:
    return f"{position.name}, {branch.name}, {KIND_LABELS.get(kind, kind)}, {year} он"


def save_row(
    *, position: Position, branch: Branch, kind: str, year: int, qty: int, by: User, row: NazgRow | None = None
) -> NazgRow:
    """Add a slot row, or change `row`, and log it (system log, HR). Raises SlotRowExists for a key already held."""
    old_qty = row.qty if row is not None else None
    try:
        with transaction.atomic():
            saved = macs_writes.save_slot_row(position=position, branch=branch, kind=kind, year=year, qty=qty, row=row)
    except macs_writes.SlotKeyTaken as taken:
        raise SlotRowExists(taken.row) from taken
    except ProgrammingError as exc:
        raise SlotWriteDenied(WRITE_DENIED_MESSAGE) from exc
    label = _describe(position, branch, kind, year)
    added = old_qty is None
    record_safe(
        Category.HR,
        AUDIT_ACTION_ADDED if added else AUDIT_ACTION_CHANGED,
        actor=by,
        message=f"{label}: орон тоо {qty}" if added else f"{label}: орон тоо {old_qty} → {qty}",
        target_type="Орон тоо",
        target_label=label,
    )
    return saved


def delete_row(row: NazgRow, *, by: User) -> None:
    """Remove a slot row and log it. Raises SlotWriteDenied when the database refuses the delete."""
    label = _describe(cast(Position, row.position), cast(Branch, row.branch), row.kind, row.year)
    message = f"{label}: орон тоо {row.qty}"
    try:
        with transaction.atomic():
            macs_writes.delete_slot_row(row)
    except ProgrammingError as exc:
        raise SlotWriteDenied(WRITE_DENIED_MESSAGE) from exc
    record_safe(
        Category.HR,
        AUDIT_ACTION_DELETED,
        actor=by,
        message=message,
        target_type="Орон тоо",
        target_label=label,
    )
