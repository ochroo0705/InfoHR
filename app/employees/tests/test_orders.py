from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from macs.models import Command, EmployeeHistory, FiredReason

from employees.models import Employee, Event, EventType, HrOrder, OrderState, OrderType, Position
from employees.services import events, orders
from employees.services.events import EventError
from employees.services.orders import OrderError
from employees.tests.conftest import named
from employees.tests.test_events import future, rec

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 1)


def ev(type: str, pension: bool = False) -> Event:
    return Event(type=type, pension=pension)


def st(dep: int = 1, pos: int = 1, emptype: int = 1) -> dict[str, Any]:
    return {"department_id": dep, "position_id": pos, "emptype": emptype}


@pytest.mark.parametrize(
    ("event", "old", "new", "expected"),
    [
        (ev(EventType.TERMINATION, pension=True), st(), st(emptype=3), OrderType.PENSION),
        (ev(EventType.CONTRACT, pension=True), st(), st(emptype=6), OrderType.PENSION),
        (ev(EventType.CONTRACT, pension=True), st(), st(), OrderType.PENSION),
        (ev(EventType.TRANSFER), st(), st(dep=2), OrderType.DEPARTMENT),
        (ev(EventType.PROMOTION), st(), st(dep=2, pos=2), OrderType.DEPARTMENT),
        (ev(EventType.PROMOTION), st(), st(pos=2), OrderType.POSITION),
        (ev(EventType.DEMOTION), st(), st(pos=2), OrderType.POSITION),
        (ev(EventType.CONTRACT), st(), st(emptype=5), OrderType.TYPE_CHANGED),
        (ev(EventType.CONTRACT), st(), st(), None),
        (ev(EventType.REHIRE), st(emptype=3), st(emptype=1), OrderType.HIRED),
        (ev(EventType.TERMINATION), st(), st(emptype=3), OrderType.FIRED),
        (ev(EventType.SALARY_CHANGE), st(), st(), None),
        (ev(EventType.LEAVE_START), st(), st(), None),
        (ev(EventType.LEAVE_RETURN), st(), st(), None),
    ],
)
def test_classify_priority(event: Event, old: dict[str, Any], new: dict[str, Any], expected: int | None) -> None:
    assert orders.classify(event, old, new) == expected


def test_salary_change_has_no_order(hired: Employee, actor: User) -> None:
    rec(hired, actor, "salary_change", DAY, salary=Decimal("3000000"))
    assert not HrOrder.objects.filter(event__isnull=False).exists()


def test_hire_creates_pending_order(hired: Employee) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    assert order.state == OrderState.PENDING and order.order_type == OrderType.HIRED
    assert order.history_id is not None and EmployeeHistory.objects.filter(pk=order.history_id).exists()
    assert order.command_id is None


def promo(hired: Employee, actor: User, lead: Position, **kw: Any) -> Event:
    return rec(hired, actor, "promotion", kw.pop("day", DAY), changes={"position": lead}, **kw)


@pytest.fixture
def lead(db: None) -> Position:
    return Position.objects.create(name="Ахлах нягтлан")


def event_order(hired: Employee, actor: User, lead: Position, **kw: Any) -> HrOrder:
    return promo(hired, actor, lead, **kw).order


def test_event_creates_pending_order(hired: Employee, actor: User, lead: Position) -> None:
    order = event_order(hired, actor, lead)
    assert order.state == OrderState.PENDING and order.order_type == OrderType.POSITION and order.number == ""


def test_register_sets_registered_and_writes_command(hired: Employee, actor: User, lead: Position) -> None:
    order = event_order(hired, actor, lead)
    order = orders.register(order, number=" А/54 ", date=DAY, summary="Албан тушаал", issued_by="Захирал", by=actor)
    assert order.state == OrderState.REGISTERED and order.number == "А/54" and order.number_key == "а/54"
    cmd = Command.objects.get(pk=order.command_id or 0)
    assert (cmd.number, cmd.order_type, cmd.date) == ("А/54", 3, DAY)
    hired.refresh_from_db()
    assert hired.command_id_value == cmd.pk and hired.move_type == 3
    # editing again updates the same production row
    order = orders.register(order, number="А/55", date=DAY, summary="Дахин", issued_by="Захирал", by=actor)
    assert Command.objects.filter(employee=hired).count() == 1
    assert Command.objects.get(pk=order.command_id or 0).number == "А/55"


def test_create_with_number_is_registered(hired: Employee, actor: User, lead: Position) -> None:
    order = event_order(hired, actor, lead, order_number="Б/1", order_date=DAY)
    assert order.state == OrderState.REGISTERED and order.command_id is not None


def two_orders(hired: Employee, actor: User, lead: Position) -> tuple[HrOrder, HrOrder]:
    first = event_order(hired, actor, lead)
    hire_order = HrOrder.objects.get(employee=hired, is_hire=True)
    return first, hire_order


def reg(order: HrOrder, actor: User, number: str, day: date = DAY) -> HrOrder:
    return orders.register(order, number=number, date=day, summary="", issued_by="", by=actor)


def test_number_unique_per_year_including_cancelled(hired: Employee, actor: User, lead: Position) -> None:
    first, hire_order = two_orders(hired, actor, lead)
    HrOrder.objects.filter(pk=first.pk).update(state=OrderState.CANCELLED, number="А/1", number_key="а/1", date=DAY)
    with pytest.raises(OrderError) as exc:
        reg(hire_order, actor, "А/1", date(2026, 6, 1))
    assert exc.value.errors["number"] == "Энэ дугаар 2026 онд аль хэдийн ашиглагдсан."


def test_number_normalised_for_uniqueness(hired: Employee, actor: User, lead: Position) -> None:
    first, hire_order = two_orders(hired, actor, lead)
    reg(first, actor, "А/54")
    with pytest.raises(OrderError):
        reg(hire_order, actor, "  а/54 ")


def test_same_number_next_year_ok(hired: Employee, actor: User, lead: Position) -> None:
    first, hire_order = two_orders(hired, actor, lead)
    reg(first, actor, "А/54", date(2026, 12, 31))
    assert reg(hire_order, actor, "А/54", date(2027, 1, 1)).state == OrderState.REGISTERED


def test_register_number_race_is_serialised(hired: Employee, actor: User, lead: Position) -> None:
    first, hire_order = two_orders(hired, actor, lead)
    with CaptureQueriesContext(connection) as ctx:
        reg(first, actor, "А/7")
    assert any("pg_advisory_xact_lock" in q["sql"] for q in ctx.captured_queries)
    with pytest.raises(OrderError):
        reg(hire_order, actor, "А/7")
    assert HrOrder.objects.filter(number_key="а/7").count() == 1


def test_signed_is_locked(hired: Employee, actor: User, lead: Position) -> None:
    order = reg(event_order(hired, actor, lead), actor, "А/9")
    upload = SimpleUploadedFile("a.pdf", b"%PDF-1.4 x", content_type="application/pdf")
    order = orders.attach_signed_file(order, upload, by=actor)
    assert order.state == OrderState.SIGNED and order.file
    with pytest.raises(OrderError):
        reg(order, actor, "А/10")
    with pytest.raises(OrderError):
        orders.attach_signed_file(order, SimpleUploadedFile("b.pdf", b"%PDF"), by=actor)


def test_attach_needs_registered(hired: Employee, actor: User, lead: Position) -> None:
    order = event_order(hired, actor, lead)
    with pytest.raises(OrderError):
        orders.attach_signed_file(order, SimpleUploadedFile("a.pdf", b"%PDF"), by=actor)


def test_cancel_event_cancels_order_keeps_number(hired: Employee, actor: User, lead: Position) -> None:
    event = promo(hired, actor, lead, day=future())
    order = reg(event.order, actor, "А/20", future())
    command_id = order.command_id
    events.cancel(event, reason="Буруу", by=actor)
    order.refresh_from_db()
    assert order.state == OrderState.CANCELLED and order.number == "А/20" and order.cancel_reason == "Буруу"
    assert Command.objects.filter(pk=command_id or 0).exists()
    hired.refresh_from_db()
    assert hired.command_id_value != command_id
    with pytest.raises(OrderError):  # number stays taken
        reg(HrOrder.objects.get(employee=hired, is_hire=True), actor, "А/20", future())


def test_cancel_signed_requires_cancel_number(hired: Employee, actor: User, lead: Position) -> None:
    event = promo(hired, actor, lead, day=future())
    order = reg(event.order, actor, "А/21", future())
    orders.attach_signed_file(order, SimpleUploadedFile("a.pdf", b"%PDF"), by=actor)
    with pytest.raises(EventError) as exc:
        events.cancel(event, reason="Буруу", by=actor)
    assert exc.value.errors["cancel_order_no"] == "Гарын үсэгтэй тушаалыг цуцлахад цуцалсан тушаалын дугаар заавал."
    event.refresh_from_db()
    assert event.cancelled_at is None
    events.cancel(event, reason="Буруу", by=actor, cancel_order_no="А/30")
    order.refresh_from_db()
    assert order.state == OrderState.CANCELLED and order.cancel_order_no == "А/30"


def test_legacy_number_clash_is_warning(hired: Employee, actor: User, lead: Position) -> None:
    Command.objects.create(employee_id=hired.pk, number="А/99", date=DAY, order_type=1)
    order = reg(event_order(hired, actor, lead), actor, "а/99")
    assert order.state == OrderState.REGISTERED
    assert getattr(order, "warning", "") == "Хуучин програмд 2026 онд ийм дугаартай тушаал байна."
    assert orders.legacy_clash_warning("А/99", DAY, exclude_command_id=order.command_id) != ""  # the old row
    assert orders.legacy_clash_warning("А/98", DAY) == ""
    assert orders.legacy_clash_warning("А/99", date(2027, 1, 1)) == ""


def test_termination_pension_and_fire(hired: Employee, actor: User) -> None:
    fr = named(FiredReason, "Өөрийн хүсэлтээр")
    event = rec(hired, actor, "termination", DAY, fired_reason=fr)
    assert event.order.order_type == OrderType.FIRED


def test_register_cancelled_refused(hired: Employee, actor: User, lead: Position) -> None:
    order = event_order(hired, actor, lead)
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.CANCELLED)
    with pytest.raises(OrderError):
        reg(order, actor, "А/60")


def test_date_required(hired: Employee, actor: User, lead: Position) -> None:
    order = event_order(hired, actor, lead)
    with pytest.raises(OrderError) as exc:
        orders.register(order, number="А/61", date=None, summary="", issued_by="", by=actor)  # type: ignore[arg-type]
    assert "date" in exc.value.errors
    order.refresh_from_db()
    assert order.state == OrderState.PENDING
    with pytest.raises(OrderError):
        orders.create_for_change(
            employee=hired,
            event=None,
            is_hire=True,
            order_type=1,
            number="А/62",
            date=None,
            summary="",
            issued_by="",
            by=actor,
        )


@pytest.mark.parametrize(
    ("kw", "field"),
    [
        ({"number": "12345678901"}, "number"),
        ({"summary": "x" * 51}, "summary"),
        ({"issued_by": "y" * 26}, "issued_by"),
    ],
)
def test_length_limits(hired: Employee, actor: User, lead: Position, kw: dict[str, str], field: str) -> None:
    order = event_order(hired, actor, lead)
    args = {"number": "А/63", "summary": "", "issued_by": "", **kw}
    with pytest.raises(OrderError) as exc:
        orders.register(order, date=DAY, by=actor, **args)
    assert field in exc.value.errors


def test_reregister_own_number_ok(hired: Employee, actor: User, lead: Position) -> None:
    order = reg(event_order(hired, actor, lead), actor, "А/64")
    assert reg(order, actor, "а/64").state == OrderState.REGISTERED


def test_cancel_pending_needs_no_cancel_number(hired: Employee, actor: User, lead: Position) -> None:
    event = promo(hired, actor, lead, day=future())
    events.cancel(event, reason="Буруу", by=actor)
    order = HrOrder.objects.get(event=event)
    assert order.state == OrderState.CANCELLED and order.cancel_order_no == ""
