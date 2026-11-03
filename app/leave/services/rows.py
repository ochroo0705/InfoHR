"""Read layer: production leave rows merged with their Info HR extension rows into one shape.

Production rows are the source of truth. An ext row only adds to a production row it points to;
ext rows whose production row is gone never appear here. Rows written by the old program have
no ext row and are marked `from_old_system`. Missing employee or leave type rows (no constraint
on the production side, D-017) are skipped with a log warning.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from django.db.models import Exists, OuterRef, QuerySet
from macs.models import Employee, Entitlement, LeaveAssign, LeaveTypeRow

from leave.models import GrantKind, LeaveExt, LeaveGrantExt, LeaveRequest, LeaveTypeExt, RequestStatus
from leave.services import calendar
from leave.services.writes import AssignSnapshot, snapshot

logger = logging.getLogger(__name__)


class State(StrEnum):
    RECORDED = "Бүртгэсэн"
    CANCELLED = "Цуцалсан"
    MISTAKE = "Буруу бүртгэсэн"
    REJECTED = "Татгалзсан"


def leave_status(reqs: list[LeaveRequest]) -> dict[int, str]:
    """An approved request whose leave HR later cancelled («Цуцалсан») or marked a mistake («Буруу бүртгэсэн»)
    shows that state in the list. The request keeps its approved status: only the display reads the leave row."""
    approved = [r for r in reqs if r.status == RequestStatus.APPROVED and r.assign_id]
    if not approved:
        return {}
    ids = [r.assign_id for r in approved]
    assigns = LeaveAssign.objects.in_bulk(ids)
    exts = LeaveExt.objects.in_bulk(ids)
    shown: dict[int, str] = {}
    for r in approved:
        assign = assigns.get(r.assign_id)
        if assign is None or assign.status != LeaveAssign.CANCELLED:
            continue
        ext = exts.get(r.assign_id)
        state = State.MISTAKE if ext is not None and ext.mistake else State.CANCELLED
        shown[r.pk] = state.value
    return shown


@dataclass(frozen=True)
class LeaveRow:
    id: int
    employee_id: int
    leave_type: LeaveTypeRow
    type_ext: LeaveTypeExt
    start: date
    end: date
    days: int
    state: State
    comment: str
    from_old_system: bool
    override_reason: str
    cancel_reason: str
    snapshot: AssignSnapshot

    @property
    def counts(self) -> bool:
        return self.state is State.RECORDED

    def started(self, today: date) -> bool:
        return self.start <= today


@dataclass(frozen=True)
class GrantRow:
    id: int
    employee_id: int
    leave_type_id: int
    start: date
    end: date
    days: int
    kind: GrantKind
    comment: str
    breakdown: str
    from_old_system: bool


def _state(assign: LeaveAssign, ext: LeaveExt | None) -> State:
    if assign.status == LeaveAssign.REJECTED:
        return State.REJECTED
    if assign.status == LeaveAssign.CANCELLED:
        return State.MISTAKE if ext is not None and ext.mistake else State.CANCELLED
    if assign.status not in (None, LeaveAssign.APPROVED):
        logger.warning("Leave %s has unknown status %s: shown as recorded", assign.pk, assign.status)
    return State.RECORDED


def _grant_kind(grant_pk: int, ext: LeaveGrantExt | None) -> GrantKind:
    if ext is None:
        return GrantKind.MANUAL
    try:
        return GrantKind(ext.kind)
    except ValueError:
        logger.warning("Grant %s has unknown kind %r: shown as manual", grant_pk, ext.kind)
        return GrantKind.MANUAL


def _build(assigns: list[LeaveAssign]) -> list[LeaveRow]:
    """Merge the production rows with their ext rows, one query per table.

    Foreign keys have no database constraint, so a dangling id is checked here rather than
    relying on a join: a missing employee or leave type skips the row with a warning.
    """
    if not assigns:
        return []
    type_ids = {a.leave_type_id for a in assigns}
    employee_ids = {a.employee_id for a in assigns}
    types = LeaveTypeRow.objects.in_bulk(list(type_ids))
    existing_employees = set(Employee.objects.filter(pk__in=employee_ids).values_list("pk", flat=True))
    type_exts = LeaveTypeExt.objects.in_bulk(list(types))
    exts = LeaveExt.objects.in_bulk([a.pk for a in assigns])
    uncounted = [a for a in assigns if a.adays is None]  # old-program rows with no day count: counted here, once
    holidays = (
        calendar.holidays_between(min(a.date1 for a in uncounted), max(a.date2 for a in uncounted))
        if uncounted
        else set()
    )

    merged: list[LeaveRow] = []
    for a in assigns:
        leave_type = types.get(a.leave_type_id)
        if leave_type is None or a.employee_id not in existing_employees:
            logger.warning(
                "Leave %s skipped: employee %s or leave type %s is missing",
                a.pk,
                a.employee_id,
                a.leave_type_id,
            )
            continue
        ext = exts.get(a.pk)
        merged.append(
            LeaveRow(
                id=a.pk,
                employee_id=a.employee_id,
                leave_type=leave_type,
                type_ext=type_exts.get(leave_type.pk) or LeaveTypeExt(leave_type=leave_type),
                start=a.date1,
                end=a.date2,
                days=a.adays if a.adays is not None else calendar.working_days(a.date1, a.date2, holidays),
                state=_state(a, ext),
                comment=a.comment or "",
                from_old_system=ext is None,
                override_reason=ext.override_reason if ext else "",
                cancel_reason=ext.cancel_reason if ext else "",
                snapshot=snapshot(a),
            )
        )
    return merged


def leaves(
    *,
    employee_ids: Iterable[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[LeaveRow]:
    """Leave rows, newest first. `start`/`end` keep rows that overlap [start, end]."""
    qs = LeaveAssign.objects.all()
    if employee_ids is not None:
        qs = qs.filter(employee_id__in=list(employee_ids))
    if start is not None:
        qs = qs.filter(date2__gte=start)
    if end is not None:
        qs = qs.filter(date1__lte=end)
    return _build(list(qs.order_by("-date1", "-id")))


def _with_state(qs: QuerySet[LeaveAssign], name: str) -> QuerySet[LeaveAssign]:
    """The database form of `_state(...).name == name`; a name that is no state matches nothing."""
    mistake = Exists(LeaveExt.objects.filter(pk=OuterRef("pk"), mistake=True))
    if name == State.RECORDED.name:
        return qs.exclude(status__in=[LeaveAssign.REJECTED, LeaveAssign.CANCELLED])
    if name == State.REJECTED.name:
        return qs.filter(status=LeaveAssign.REJECTED)
    if name == State.CANCELLED.name:
        return qs.filter(status=LeaveAssign.CANCELLED).exclude(mistake)
    if name == State.MISTAKE.name:
        return qs.filter(status=LeaveAssign.CANCELLED).filter(mistake)
    return qs.none()


def leaves_page(
    employees: QuerySet[Employee],
    *,
    offset: int,
    size: int,
    start: date | None = None,
    end: date | None = None,
    type_id: int | None = None,
    state: str | None = None,
) -> tuple[list[LeaveRow], bool]:
    """One batch of `leaves` (newest first) and whether more follow, filtered and cut by the database.

    `state` is a `State` name or None for every state; `employees` are the people whose leave is wanted."""
    qs = LeaveAssign.objects.filter(employee_id__in=employees.values("pk"))
    if start is not None:
        qs = qs.filter(date2__gte=start)
    if end is not None:
        qs = qs.filter(date1__lte=end)
    if type_id is not None:
        qs = qs.filter(leave_type_id=type_id)
    if state is not None:
        qs = _with_state(qs, state)
    found = list(qs.order_by("-date1", "-id")[offset : offset + size + 1])
    return _build(found[:size]), len(found) > size


def leave(pk: int) -> LeaveRow:
    """One leave row. Raises LeaveAssign.DoesNotExist when the production row is gone or unusable."""
    rows = _build([LeaveAssign.objects.get(pk=pk)])
    if not rows:
        raise LeaveAssign.DoesNotExist(f"Leave {pk} has no usable employee or leave type")
    return rows[0]


def grants(employee_id: int, *, annual_only: bool = True) -> list[GrantRow]:
    """Grants of one employee, newest first. `annual_only` keeps only types that use the annual balance."""
    return grants_many([employee_id], annual_only=annual_only).get(employee_id, [])


def grants_many(employee_ids: Iterable[int], *, annual_only: bool = True) -> dict[int, list[GrantRow]]:
    """Grants of several employees in one pass (four queries in all), newest first within each employee."""
    found = list(Entitlement.objects.filter(employee_id__in=list(employee_ids)).order_by("-date1", "-id"))
    types = LeaveTypeRow.objects.in_bulk({g.leave_type_id for g in found})
    type_exts = LeaveTypeExt.objects.in_bulk(list(types))
    exts = LeaveGrantExt.objects.in_bulk([g.pk for g in found])

    result: dict[int, list[GrantRow]] = {}
    for g in found:
        if g.leave_type_id not in types:
            logger.warning("Grant %s skipped: leave type %s is missing", g.pk, g.leave_type_id)
            continue
        type_ext = type_exts.get(g.leave_type_id)
        if annual_only and (type_ext is None or not type_ext.uses_annual_balance):
            continue
        ext = exts.get(g.pk)
        result.setdefault(g.employee_id, []).append(
            GrantRow(
                id=g.pk,
                employee_id=g.employee_id,
                leave_type_id=g.leave_type_id,
                start=g.date1,
                end=g.date2,
                days=g.ent_days,
                kind=_grant_kind(g.pk, ext),
                comment=g.comment or "",
                breakdown=ext.breakdown if ext else "",
                from_old_system=ext is None,
            )
        )
    return result
