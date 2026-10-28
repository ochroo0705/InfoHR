"""An order type is decided from the proposed change before anything is written (Task 2 of the signed-order plan).
Each case predicts the order type with `orders.order_type_for` and then records the same change for real: the
prediction must match the order `events.record` creates (or no order at all)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from macs.models import FiredReason

from employees.models import Employee, EmployeeExt, Event, EventType, HrOrder, JobRecord, LeaveKind, OrderType, Position
from employees.services import events, history, macs_writes, orders
from employees.tests.conftest import hire_values, named
from employees.tests.test_events import rec

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)
LATER = date(2026, 4, 1)


@pytest.fixture
def lead(db: None) -> Position:
    return Position.objects.create(name="Ахлах нягтлан")


def _predict(
    employee: Employee,
    event_type: str,
    effective: date,
    changes: dict[str, Any],
    *,
    salary: Decimal | None = None,
    reason: str = "",
    fired_reason: FiredReason | None = None,
    pension: bool = False,
) -> int | None:
    new = events._validate(
        employee, EventType(event_type), effective, dict(changes), salary, reason, fired_reason, pension
    )
    current = history.job_on(employee, effective)
    assert current is not None
    return orders.order_type_for(event_type, pension, current, new, employee, effective)


def _check(
    employee: Employee,
    actor: User,
    event_type: str,
    effective: date,
    expected: int | None,
    changes: dict[str, Any] | None = None,
    **kw: Any,
) -> None:
    """Predict first (nothing written yet), then record the same change and compare with the real order."""
    predicted = _predict(employee, event_type, effective, changes or {}, **kw)
    event: Event = rec(employee, actor, event_type, effective, changes=changes or {}, **kw)
    order = HrOrder.objects.filter(event=event).first()
    recorded = order.order_type if order is not None else None
    assert predicted == recorded == expected


def test_department_change(hired: Employee, actor: User) -> None:
    dep = macs_writes.save_department("Бусад хэлтэс")
    _check(hired, actor, EventType.TRANSFER, DAY, OrderType.DEPARTMENT, changes={"department": dep})


def test_position_change(hired: Employee, actor: User, lead: Position) -> None:
    _check(hired, actor, EventType.PROMOTION, DAY, OrderType.POSITION, changes={"position": lead})


def test_employee_type_change(hired: Employee, actor: User) -> None:
    _check(hired, actor, EventType.CONTRACT, DAY, OrderType.TYPE_CHANGED, changes={"emptype": 5})


def test_termination(hired: Employee, actor: User) -> None:
    fr = named(FiredReason, "Өөрийн хүсэлтээр")
    _check(hired, actor, EventType.TERMINATION, DAY, OrderType.FIRED, fired_reason=fr)


def test_pension_exit(hired: Employee, actor: User) -> None:
    fr = named(FiredReason, "Өөрийн хүсэлтээр")
    _check(hired, actor, EventType.TERMINATION, DAY, OrderType.PENSION, fired_reason=fr, pension=True)


def test_rehire(hired: Employee, actor: User) -> None:
    fr = named(FiredReason, "Өөрийн хүсэлтээр")
    rec(hired, actor, EventType.TERMINATION, DAY, fired_reason=fr)
    _check(hired, actor, EventType.REHIRE, LATER, OrderType.HIRED)


def test_salary_only_needs_no_order(hired: Employee, actor: User) -> None:
    _check(hired, actor, EventType.SALARY_CHANGE, DAY, None, salary=Decimal("3000000"))


def test_leave_start_needs_no_order(hired: Employee, actor: User) -> None:
    _check(hired, actor, EventType.LEAVE_START, DAY, None, reason=LeaveKind.UNPAID.value)


def test_manager_only_needs_no_order(hired: Employee, actor: User, job_values: dict[str, Any]) -> None:
    boss = history.hire(hire_values("УБ11223344"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    _check(hired, actor, EventType.TRANSFER, DAY, None, changes={"manager": boss})


def test_contract_change_without_type_change_needs_no_order(hired: Employee, actor: User) -> None:
    changes = {"contract_type": "fixed_term", "contract_start": DAY, "contract_end": date(2027, 3, 1)}
    _check(hired, actor, EventType.CONTRACT, DAY, None, changes=changes)


def test_change_inside_left_period_uses_proposed_event(hired: Employee, actor: User) -> None:
    """A non-termination change inside a LEFT period: the old state is the pension exit (6), the new one is the
    job's new event (not pension), so the employee type goes 6 -> 3 and the change needs a TYPE_CHANGED order.
    The preview must read the proposed event, not the event the copied job row still points at.
    Only the record is checked here: a contract change inside a LEFT period is refused when signed (apply_waiting)."""
    fr = named(FiredReason, "Өөрийн хүсэлтээр")
    rec(hired, actor, EventType.TERMINATION, DAY, fired_reason=fr, pension=True)
    predicted = _predict(hired, EventType.CONTRACT, LATER, {"contract_no": "C-2"})
    event = events.record(
        hired,
        type=EventType.CONTRACT,
        effective=LATER,
        changes={"contract_no": "C-2"},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert predicted == HrOrder.objects.get(event=event).order_type == OrderType.TYPE_CHANGED


def test_preview_writes_nothing(hired: Employee, actor: User, lead: Position) -> None:
    counts = (
        JobRecord.objects.count(),
        Event.objects.count(),
        HrOrder.objects.count(),
        EmployeeExt.objects.count(),
    )
    current = history.job_on(hired, DAY)
    assert current is not None
    position_before = current.position_id
    new = events._validate(hired, EventType.PROMOTION, DAY, {"position": lead}, None, "", None, False)
    assert orders.order_type_for(EventType.PROMOTION, False, current, new, hired, DAY) == OrderType.POSITION
    assert current.position_id == position_before
    after = (
        JobRecord.objects.count(),
        Event.objects.count(),
        HrOrder.objects.count(),
        EmployeeExt.objects.count(),
    )
    assert after == counts
