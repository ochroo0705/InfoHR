"""Test helpers for changes that wait for a signed order (signed-order plan, Task 4)."""

from typing import Any

from accounts.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from employees.models import Employee, Event, HrOrder, OrderState
from employees.services import events, orders


def sign_event(event: Event, by: User | None = None) -> Event:
    """Give the event's order a number, date and signed scan. Attaching the scan applies the waiting change
    (orders.attach_signed_file), so this only applies by itself for an event that has no order."""
    signer = by if by is not None else event.created_by
    assert signer is not None  # noqa: S101
    order = HrOrder.objects.filter(event=event).first()
    if order is not None and order.state == OrderState.PENDING:
        today = timezone.localdate()
        orders.register(order, number=orders.suggest_number(today), date=today, summary="", issued_by="", by=signer)
        order.refresh_from_db()
    if order is not None and order.state == OrderState.REGISTERED:
        scan = SimpleUploadedFile("order.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        orders.attach_signed_file(order, scan, by=signer)
    event.refresh_from_db()
    if order is None and event.applied_at is None:
        events.apply_waiting(event, by=signer)
    event.refresh_from_db()
    return event


def record_signed(employee: Employee, **record_kwargs: Any) -> Event:
    """Record a change through `events.record`, then sign its order when the change waits for one."""
    event = events.record(employee, **record_kwargs)
    if event.applied_at is None:
        return sign_event(event, by=record_kwargs.get("by"))
    return event
