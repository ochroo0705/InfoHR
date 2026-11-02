from datetime import date
from typing import Any

from django import template
from django.utils import timezone
from employees.models import Employee

from leave import access
from leave.services import entitlement
from leave.services.approvers import may_decide, requests_active, waiting_for_cached

register = template.Library()


@register.simple_tag(takes_context=True)
def requests_nav(context: Any) -> dict[str, Any]:
    """The «Хүсэлт» nav link: shown when approval is on and the user has requests to decide or may see them.

    The queue is worked out only for a user who could decide something, and once per request (kept on the request),
    so the base template can ask several times.
    """
    request = context["request"]
    cached: dict[str, Any] | None = getattr(request, "_leave_requests_nav", None)
    if cached is not None:
        return cached
    nav: dict[str, Any] = {"show": False, "count": 0}
    user = request.user
    if user.is_authenticated and requests_active(user):
        day = timezone.localdate()
        count = len(waiting_for_cached(user, day)) if may_decide(user, day) else 0
        nav = {"show": count > 0 or access.can_view(user), "count": count}
    request._leave_requests_nav = nav
    return nav


@register.simple_tag
def leave_start_missing(employee: Employee) -> bool:
    """True when the employee has no start date, so no leave year can be calculated (QC 2a)."""
    return entitlement.employment_start(employee) is None


@register.simple_tag
def leave_started(employee: Employee, day: date) -> bool:
    return entitlement.has_started(employee, day)
