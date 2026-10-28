"""The Word draft of an order whose change still waits for its signature shows the NEW values (the proposal)."""

from datetime import date, timedelta

import pytest
from accounts.models import User
from django.utils import timezone
from macs.models import FiredReason

from employees.models import Employee, HrOrder
from employees.services import events, macs_writes, order_docs

from .conftest import named
from .helpers import sign_event

pytestmark = pytest.mark.django_db

KEYS = ("department", "position", "employee_type", "old_department", "new_department", "old_position", "new_position")


def future() -> object:
    return timezone.localdate() + timedelta(days=30)


@pytest.mark.parametrize("pension", [False, True])
def test_waiting_termination_draft_shows_the_employee_type_it_gets_on_signing(
    hired: Employee, actor: User, pension: bool
) -> None:
    event = events.record(
        hired,
        type="termination",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
        pension=pension,
    )
    order = HrOrder.objects.get(event=event)
    waiting = order_docs.build_context(order, actor)
    sign_event(event, by=actor)
    order.refresh_from_db()
    signed = order_docs.build_context(order, actor)
    assert waiting["employee_type"] == signed["employee_type"]
    assert waiting["new_employee_type"] == signed["new_employee_type"]
    assert waiting["employee_type"] != order_docs._emptype_label(1)  # not the still-active type


def test_waiting_transfer_draft_shows_the_new_department(hired: Employee, actor: User) -> None:
    marketing = macs_writes.save_department("Маркетинг")
    event = events.record(
        hired,
        type="transfer",
        effective=future(),  # type: ignore[arg-type]
        changes={"department": marketing},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert event.applied_at is None
    order = HrOrder.objects.get(event=event)
    ctx = order_docs.build_context(order, actor)
    assert ctx["old_department"] == "Санхүү"
    assert ctx["new_department"] == "Маркетинг" and ctx["department"] == "Маркетинг"
    assert ctx["old_department"] != ctx["new_department"]
    assert ctx["old_position"] == ctx["new_position"] == "Нягтлан"


def test_draft_after_signing_equals_the_applied_context(hired: Employee, actor: User) -> None:
    marketing = macs_writes.save_department("Маркетинг")
    event = events.record(
        hired,
        type="transfer",
        effective=future(),  # type: ignore[arg-type]
        changes={"department": marketing},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    order = HrOrder.objects.get(event=event)
    waiting = order_docs.build_context(order, actor)
    sign_event(event, by=actor)
    order.refresh_from_db()
    signed = order_docs.build_context(order, actor)
    assert {k: waiting[k] for k in KEYS} == {k: signed[k] for k in KEYS}
    assert signed["old_department"] == "Санхүү" and signed["new_department"] == "Маркетинг"
