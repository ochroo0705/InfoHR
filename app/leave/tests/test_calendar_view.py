from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from macs.models import LeaveTypeRow

from leave.services import records, writes
from leave.services.records import Draft

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]


def test_calendar_marks_leave_and_holiday(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    writes.set_holiday_dates(2026, {date(2026, 11, 26): "Тусгаар тогтнолын өдөр"})
    records.record(Draft(employee, annual, date(2026, 11, 2), date(2026, 11, 4)), actor, date(2026, 10, 14))
    u = User.objects.create_user("acc", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name="Accountant"))
    c = Client()
    c.force_login(u)
    body = c.get(reverse("leave:calendar"), {"month": "2026-11"}).content.decode()
    assert employee.full_name in body
    assert body.count(f'data-leave="{annual.pk}"') == 3
    assert 'data-holiday="2026-11-26"' in body
    assert "2026-10" in body and "2026-12" in body  # prev / next links


def test_bad_month_falls_back_to_current(employee: Employee, actor: User) -> None:
    c = Client()
    c.force_login(actor)
    assert c.get(reverse("leave:calendar"), {"month": "garbage"}).status_code == 200


def test_month_arrows_replace_history_instead_of_adding() -> None:
    u = User.objects.create_user("cal_nav", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name="HR"))
    c = Client()
    c.force_login(u)
    page = c.get("/leave/calendar/?month=2026-10").content.decode()
    assert 'hx-replace-url="true"' in page and 'hx-get="?month=2026-09"' in page


def test_this_month_button_only_away_from_current_month(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("leave.views.today", lambda: date(2026, 10, 15))
    u = User.objects.create_user("cal_now", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name="HR"))
    c = Client()
    c.force_login(u)
    assert "Энэ сар" not in c.get("/leave/calendar/?month=2026-10").content.decode()
    away = c.get("/leave/calendar/?month=2027-03").content.decode()
    assert "Энэ сар" in away and 'hx-get="?month=2026-10"' in away
