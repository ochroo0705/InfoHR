"""The order pop-up (opened from the register) as a request-free context: the facts of one order, its links to the other
orders of the same employee, its history and which buttons the user may see. The Django view and the API both build
their response from here, so the rules are decided once."""

from typing import Any

from accounts.models import User
from django.utils import timezone

from employees import access
from employees.models import Employee, HrOrder, OrderSigning, OrderState
from employees.services import order_docs, orders


def build(user: User, employee: Employee, order: HrOrder) -> dict[str, Any]:
    """Everything the order pop-up shows for `user`. The caller has already checked that the employee and the order
    are visible to the user (a foreign order is a 404 in the view)."""
    can_manage = access.can_manage(user)
    siblings = list(employee.hr_orders.order_by("-date", "-pk"))
    job = order_docs.build_context(order, user)  # department and position as the order document shows them
    event = order.event
    return {
        "can_sign": access.can_sign_orders(user, order)
        and order.state == OrderState.REGISTERED
        and not access.signing_needs_salary_right(user, order),
        "signing": OrderSigning.objects.filter(order=order).first(),
        "change_status": event.status(timezone.localdate()) if event else "effective",
        "cancel_change": event is not None
        and event.cancelled_at is None
        and event.status(timezone.localdate()) in ("scheduled", "awaiting_signature")
        and access.can_cancel(user, event),
        "employee": employee,
        "order": order,
        "can_manage": can_manage,
        "can_open_scan": access.can_open_order_scan(user, order),
        "links": orders.cancellation_links(siblings)[order.pk],
        "entries": order.activity.select_related("by").order_by("-at", "-id"),
        "department": job["department"],
        "position": job["position"],
        # What the change changes, field by field ("before → after"); empty for a hire or a termination.
        "change_rows": order_docs.change_rows(order, user),
        "editable": can_manage and order.state in (OrderState.PENDING, OrderState.REGISTERED),
    }
