"""Where a signed-in user lands after login: the one rule behind the `home` redirect and the SPA's /meta."""

from django.urls import reverse
from employees.models import EmployeeExt

from accounts.models import User


def landing_url(user: User) -> str:
    """An Auditor (system log right, no employee right) goes to the system log. A user without the employee-list
    right who has an employee record of their own goes to My page; everyone else goes to Today."""
    has_employees = user.has_perm("macs.view_employees")
    if user.has_perm("accounts.view_audit") and not has_employees:
        return reverse("logs:system")
    if not has_employees and EmployeeExt.objects.filter(user_id=user.pk).exists():
        return reverse("me")
    return reverse("employees:today")
