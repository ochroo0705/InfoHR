"""The order pop-up's context (services/order_detail_page.py): the facts the template shows, the buttons it may show and
the links between orders. No HTTP here; the view itself is covered by test_order_views.py."""

from datetime import date, timedelta

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone

from employees.models import Employee, HrOrder, OrderState
from employees.services import events, macs_writes, orders
from employees.services.order_detail_page import build
from employees.tests.helpers import record_signed
from employees.tests.test_views import login_as

pytestmark = pytest.mark.django_db

CONTEXT_KEYS = {
    "can_sign",
    "signing",
    "change_status",
    "cancel_change",
    "employee",
    "order",
    "can_manage",
    "can_open_scan",
    "links",
    "entries",
    "department",
    "position",
    "change_rows",
    "editable",
}
PAST = date(2026, 3, 1)


def future() -> date:
    return timezone.localdate() + timedelta(days=30)


def hr_user(name: str) -> User:
    return login_as(Client(), "HR", name)


def registered_hire(emp: Employee, actor: User, number: str = "15") -> HrOrder:
    order = HrOrder.objects.get(employee=emp, is_hire=True)
    return orders.register(order, number=number, date=date(2026, 1, 5), summary="", issued_by="", by=actor)


def promotion(emp: Employee, actor: User, effective: date, number: str) -> HrOrder:
    position = macs_writes.save_position("Ахлах нягтлан")
    record_signed(
        emp,
        type="promotion",
        effective=effective,
        changes={"position": position},
        salary=None,
        reason="",
        note="",
        by=actor,
        order_number=number,
    )
    return HrOrder.objects.get(employee=emp, event__isnull=False)


def test_build_context_for_hire_order(hired: Employee, actor: User) -> None:
    user = hr_user("hr_ctx_hire")
    order = registered_hire(hired, actor)
    ctx = build(user, hired, order)
    assert set(ctx) == CONTEXT_KEYS
    assert ctx["employee"] is hired and ctx["order"] is order
    assert ctx["signing"] is None  # nothing signed on screen yet
    assert ctx["change_status"] == "effective"  # a hire has no change, so nothing waits
    assert ctx["cancel_change"] is False
    assert ctx["change_rows"] == []  # a hire shows the department and position instead
    assert ctx["can_manage"] is True and ctx["can_open_scan"] is False  # hire scans need view_salary (OQ-080)
    assert ctx["department"] and ctx["position"]


def test_build_context_change_order_rows_and_status(hired: Employee, actor: User) -> None:
    user = hr_user("hr_ctx_change")
    order = promotion(hired, actor, future(), "16")
    ctx = build(user, hired, order)
    assert ctx["change_status"] == "scheduled"
    assert ctx["change_rows"] and all(len(row) == 3 for row in ctx["change_rows"])  # (label, before, after)
    assert ctx["change_rows"][0][2] == "Ахлах нягтлан"  # the new position is the "after" side


def test_can_sign_false_without_salary_right_on_hire_order(hired: Employee, actor: User) -> None:
    order = registered_hire(hired, actor)
    permission = Permission.objects.get(codename="sign_orders", content_type__app_label="accounts")

    no_salary = hr_user("hr_sign_no_salary")  # HR may sign by default only with the switch; give it here
    no_salary.user_permissions.add(permission)
    no_salary = User.objects.get(pk=no_salary.pk)
    assert build(no_salary, hired, order)["can_sign"] is False  # a hire order shows a salary this user cannot see

    accountant = login_as(Client(), "Accountant", "acc_sign_salary")  # the Accountant holds view_salary
    accountant.user_permissions.add(permission)
    accountant = User.objects.get(pk=accountant.pk)
    assert build(accountant, hired, order)["can_sign"] is True


def test_cancel_change_only_for_open_event_with_can_cancel(hired: Employee, actor: User) -> None:
    user = hr_user("hr_cancel_change")
    scheduled = promotion(hired, actor, future(), "17")
    ctx = build(user, hired, scheduled)
    assert ctx["cancel_change"] is True and ctx["change_status"] == "scheduled"

    event = scheduled.event
    assert event is not None
    events.cancel(event, reason="x", by=actor, cancel_order_no="18")
    scheduled.refresh_from_db()
    cancelled = build(user, hired, scheduled)
    assert cancelled["change_status"] == "cancelled"
    assert cancelled["cancel_change"] is False  # a cancelled change cannot be cancelled again


def test_editable_only_for_manager_on_pending_or_registered(hired: Employee, actor: User) -> None:
    pending = HrOrder.objects.get(employee=hired, is_hire=True)  # the hire order starts pending
    manager = hr_user("hr_editable")
    assert build(manager, hired, pending)["editable"] is True

    registered = registered_hire(hired, actor)
    assert build(manager, hired, registered)["editable"] is True

    HrOrder.objects.filter(pk=registered.pk).update(state=OrderState.SIGNED)
    registered.refresh_from_db()
    assert build(manager, hired, registered)["editable"] is False  # a signed order is final

    accountant = login_as(Client(), "Accountant", "acc_editable")  # no manage_employees right
    assert build(accountant, hired, pending)["editable"] is False


def test_links_cancelled_by_and_cancels(hired: Employee, actor: User) -> None:
    user = hr_user("hr_links")
    hire = registered_hire(hired, actor, number="15")
    change = promotion(hired, actor, PAST, "16")
    HrOrder.objects.filter(pk=hire.pk).update(state=OrderState.CANCELLED, cancel_reason="тест", cancel_order_no="16")
    hire.refresh_from_db()
    assert build(user, hired, hire)["links"]["cancelled_by"].pk == change.pk
    assert [c.pk for c in build(user, hired, change)["links"]["cancels"]] == [hire.pk]
    assert build(user, hired, change)["links"]["cancelled_by"] is None
