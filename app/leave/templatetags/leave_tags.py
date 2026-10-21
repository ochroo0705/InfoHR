from datetime import date

from django import template
from employees.models import Employee

from leave.services import entitlement

register = template.Library()


@register.simple_tag
def leave_start_missing(employee: Employee) -> bool:
    """True when the employee has no start date, so no leave year can be calculated (QC 2a)."""
    return entitlement.employment_start(employee) is None


@register.simple_tag
def leave_started(employee: Employee, day: date) -> bool:
    return entitlement.has_started(employee, day)
