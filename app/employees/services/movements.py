"""Job changes in a date window (hires, transfers, leavers, ...). Reports read job history only through here.

A change is one job row. Its order number comes from the change's HR order. A person with no hire row in Info HR
(old-program employees, "legacy") shows a hire on their first hire date. That stays true after HR records their first
event, which adds an opening row but no hire row.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date

from django.db.models import QuerySet
from macs.models import Department, FiredReason, Position

from employees.models import ChangeType, Employee, HrOrder, JobRecord, OrderState


@dataclass(frozen=True)
class Change:
    """One job change. `from_*` is the same employee's job row before it (None for the first row and legacy)."""

    employee: Employee
    day: date  # the change's effective date
    kind: str  # a ChangeType value
    kind_label: str
    department: Department | None
    position: Position | None
    from_department: Department | None
    from_position: Position | None
    fired_reason: FiredReason | None  # the change's event reason; None when there is no event
    order_number: str  # "" when there is no order or the order is cancelled
    legacy: bool  # True: the employee has no Info HR job history


def changes(people: QuerySet[Employee], start: date, end: date, kinds: Collection[str] | None = None) -> list[Change]:
    """The changes of `people` dated from `start` to `end` (both included), oldest first. Not capped at today and
    not filtered by visibility: callers do both. At most four queries, however many people."""
    jobs = list(
        JobRecord.objects.filter(employee__in=people)
        .select_related("employee", "department", "position", "event__fired_reason")
        .order_by("employee_id", "period")
    )
    first_hire: dict[int, int] = {}  # employee_id -> pk of the employee's first hire row
    for job in jobs:
        if job.change_type == ChangeType.HIRE:
            first_hire.setdefault(job.employee_id, job.pk)
    first_hire_pks = set(first_hire.values())

    # Walk every row so the row before a change is known even when it lies before `start`.
    rows: list[tuple[JobRecord, JobRecord | None, date]] = []
    previous: dict[int, JobRecord] = {}
    for job in jobs:
        before = previous.get(job.employee_id)
        previous[job.employee_id] = job
        day = job.period.lower
        if day is None or not start <= day <= end:
            continue
        if kinds is not None and job.change_type not in kinds:
            continue
        rows.append((job, before, day))

    event_orders = {
        order.event_id: order
        for order in HrOrder.objects.filter(event_id__in=[job.event_id for job, _, _ in rows if job.event_id])
    }
    hire_orders = {
        order.employee_id: order
        for order in HrOrder.objects.filter(
            employee_id__in=[job.employee_id for job, _, _ in rows if job.pk in first_hire_pks], is_hire=True
        )
    }

    result: list[Change] = []
    for job, before, day in rows:
        if job.event_id is not None:
            order = event_orders.get(job.event_id)
        elif job.pk in first_hire_pks:
            order = hire_orders.get(job.employee_id)
        else:
            order = None
        result.append(
            Change(
                employee=job.employee,
                day=day,
                kind=job.change_type,
                kind_label=ChangeType(job.change_type).label,
                department=job.department,
                position=job.position,
                from_department=before.department if before else None,
                from_position=before.position if before else None,
                fired_reason=job.event.fired_reason if job.event else None,
                order_number=_order_number(order),
                legacy=False,
            )
        )

    if kinds is None or ChangeType.HIRE in kinds:
        legacy_people = (
            people.exclude(job_records__change_type=ChangeType.HIRE)
            .filter(first_hire_date__gte=start, first_hire_date__lte=end)
            .select_related("department", "position")
        )
        for emp in legacy_people:
            if emp.first_hire_date is None:
                continue
            result.append(
                Change(
                    employee=emp,
                    day=emp.first_hire_date,
                    kind=ChangeType.HIRE,
                    kind_label=ChangeType.HIRE.label,
                    department=emp.department,
                    position=emp.position,
                    from_department=None,
                    from_position=None,
                    fired_reason=None,
                    order_number="",
                    legacy=True,
                )
            )

    result.sort(key=lambda c: (c.day, c.employee.full_name))
    return result


def _order_number(order: HrOrder | None) -> str:
    """The order's number, or "" when there is no order or it was cancelled."""
    if order is None or order.state == OrderState.CANCELLED:
        return ""
    return order.number
