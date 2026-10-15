from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse
from employees.models import Employee

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("leave.views.today", lambda: date(2026, 10, 14))
    monkeypatch.setattr("employees.views.leave_today", lambda: date(2026, 10, 14))
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: date(2026, 10, 14))


def _hr() -> Client:
    u = User.objects.create_user("u_hr", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name="HR"))
    c = Client()
    c.force_login(u)
    return c


def test_employee_page_shows_balance_with_breakdown(employee: Employee) -> None:
    body = _hr().get(reverse("employees:detail", args=[employee.pk])).content.decode()
    assert "Ээлжийн амралт" in body and "2026-03-01" in body and "15 (2 жил 0 сар ажилласан)" in body


def test_adjust_and_carry(employee: Employee) -> None:
    c = _hr()
    c.get(reverse("employees:detail", args=[employee.pk]))
    r = c.post(reverse("leave:adjust", args=[employee.pk, "2026-03-01"]), {"days": "-2", "reason": "Өмнө авсан"})
    assert r.status_code == 204
    r = c.post(reverse("leave:carry", args=[employee.pk, "2025-03-01"]), {"days": "3", "reason": "Ажлын шаардлага"})
    assert r.status_code == 204
    body = c.get(reverse("employees:detail", args=[employee.pk])).content.decode()
    assert "Өмнө авсан" in body and "Шилжүүлсэн" in body


def test_carry_more_than_balance_shows_error(employee: Employee) -> None:
    c = _hr()
    c.get(reverse("employees:detail", args=[employee.pk]))
    r = c.post(reverse("leave:carry", args=[employee.pk, "2025-03-01"]), {"days": "99", "reason": "x"})
    assert r.status_code == 200 and "Үлдэгдлээс их" in r.content.decode()


def test_user_without_leave_permission_sees_no_section(employee: Employee) -> None:
    u = User.objects.create_user("viewer", password="x-long-pass-123")  # noqa: S106
    u.user_permissions.add(*Permission.objects.filter(codename="view_employees"))
    c = Client()
    c.force_login(u)
    assert "Ээлжийн амралт" not in c.get(reverse("employees:detail", args=[employee.pk])).content.decode()
