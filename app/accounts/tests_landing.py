"""The landing page rule (accounts/landing.py): auditor, staff with an own record, everyone else."""

from datetime import date

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from employees.models import EmployeeExt
from leave.tests.conftest import make_employee

from accounts.landing import landing_url
from accounts.models import User

pytestmark = pytest.mark.django_db
PASSWORD = "x-long-pass-123"  # noqa: S105


def _perm(app_label: str, codename: str) -> Permission:
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def test_auditor_lands_on_system_log() -> None:
    user = User.objects.create_user("landing-auditor", password=PASSWORD)
    user.user_permissions.add(_perm("accounts", "view_audit"))

    assert landing_url(user) == reverse("logs:system")


def test_staff_with_own_record_lands_on_me() -> None:
    user = User.objects.create_user("landing-staff", password=PASSWORD)
    employee = make_employee(user, hired=date(2024, 3, 1), register_no="УБ99112297")
    EmployeeExt.objects.update_or_create(employee=employee, defaults={"user": user})

    assert landing_url(user) == reverse("me")


def test_hr_lands_on_today() -> None:
    user = User.objects.create_user("landing-hr", password=PASSWORD)
    user.user_permissions.add(_perm("macs", "view_employees"))

    assert landing_url(user) == reverse("employees:today")


def test_plain_user_without_record_lands_on_today() -> None:
    user = User.objects.create_user("landing-plain", password=PASSWORD)

    assert landing_url(user) == reverse("employees:today")
