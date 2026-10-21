from datetime import date, timedelta

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from macs.models import Entitlement, LeaveAssign, LeaveTypeRow

from leave.models import GrantKind
from leave.services import entitlement, ledger, writes

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


def _current_year(employee: Employee) -> tuple[date, date]:
    start = entitlement.year_start_for(employee, date(2026, 10, 14))
    return start, entitlement.next_year_start(employee, start) - timedelta(days=1)


def test_employee_page_view_writes_no_grants(employee: Employee, annual: LeaveTypeRow, grants_on: None) -> None:
    _hr().get(reverse("employees:detail", args=[employee.pk]))
    assert not Entitlement.objects.filter(employee_id=employee.pk).exists()


def test_employee_page_shows_balance_with_breakdown(employee: Employee, annual: LeaveTypeRow, grants_on: None) -> None:
    ledger.ensure_grants(employee, date(2026, 10, 14))
    body = _hr().get(reverse("employees:detail", args=[employee.pk])).content.decode()
    assert "Ээлжийн амралт" in body and "2026-03-01" in body and "15 (2 жил 0 сар ажилласан)" in body


def test_adjust_and_carry(employee: Employee, annual: LeaveTypeRow, grants_on: None) -> None:
    c = _hr()
    writes.add_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15, "", GrantKind.AUTO, None)
    ledger.ensure_grants(employee, date(2026, 10, 14))
    r = c.post(
        reverse("leave:adjust", args=[employee.pk, "2026-03-01", "2027-02-28"]), {"days": "-2", "reason": "Өмнө авсан"}
    )
    assert r.status_code == 204
    r = c.post(
        reverse("leave:carry", args=[employee.pk, "2025-03-01", "2026-02-28"]),
        {"days": "3", "reason": "Ажлын шаардлага"},
    )
    assert r.status_code == 204
    body = c.get(reverse("employees:detail", args=[employee.pk])).content.decode()
    assert "Өмнө авсан" in body and "Шилжүүлсэн" in body


def test_carry_more_than_balance_shows_error(employee: Employee, annual: LeaveTypeRow, grants_on: None) -> None:
    c = _hr()
    writes.add_grant(employee, annual, date(2025, 3, 1), date(2026, 2, 28), 15, "", GrantKind.AUTO, None)
    ledger.ensure_grants(employee, date(2026, 10, 14))
    r = c.post(reverse("leave:carry", args=[employee.pk, "2025-03-01", "2026-02-28"]), {"days": "99", "reason": "x"})
    assert r.status_code == 200 and "Үлдэгдлээс их" in r.content.decode()


def test_section_groups_by_period(employee: Employee, annual: LeaveTypeRow) -> None:
    start, end = _current_year(employee)
    writes.add_grant(employee, annual, start, end, 15, "", GrantKind.AUTO, None)
    body = _hr().get(reverse("employees:detail", args=[employee.pk])).content.decode()
    assert body.count(f"{start} – {end}") == 1
    assert ">15</td>" in body


def test_section_old_system_tag(employee: Employee, annual: LeaveTypeRow) -> None:
    start, end = _current_year(employee)
    Entitlement.objects.create(employee=employee, leave_type=annual, date1=start, date2=end, ent_days=10, comment="")
    LeaveAssign.objects.create(
        employee=employee, leave_type=annual, date1=start + timedelta(days=30), date2=start + timedelta(days=31),
        status=None, adays=None, comment="",
    )  # fmt: skip
    body = _hr().get(reverse("employees:detail", args=[employee.pk])).content.decode()
    assert "Хуучин системээс" in body
    assert '">8</span></td>' in body


def test_section_says_when_not_configured(employee: Employee) -> None:
    body = _hr().get(reverse("employees:detail", args=[employee.pk])).content.decode()
    assert "Ээлжийн амралтын төрлийг сонгоогүй байна" in body


def test_user_without_leave_permission_sees_no_section(employee: Employee) -> None:
    u = User.objects.create_user("viewer", password="x-long-pass-123")  # noqa: S106
    u.user_permissions.add(*Permission.objects.filter(codename="view_employees"))
    c = Client()
    c.force_login(u)
    assert "Ээлжийн амралт" not in c.get(reverse("employees:detail", args=[employee.pk])).content.decode()
