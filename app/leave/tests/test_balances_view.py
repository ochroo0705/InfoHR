from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from macs.models import LeaveTypeRow

from leave.services import ledger, records
from leave.services.records import Draft
from leave.tests.conftest import make_employee

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]


def _page(user: User) -> str:
    c = Client()
    c.force_login(user)
    return c.get(reverse("leave:balances")).content.decode()


def test_balances_show_days_and_valid_period(
    employee: Employee, annual: LeaveTypeRow, actor: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("leave.views.today", lambda: date(2026, 10, 15))
    ledger.manual_grant(employee, date(2026, 3, 1), date(2027, 2, 28), 20, "тест", actor)
    records.record(Draft(employee, annual, date(2026, 11, 2), date(2026, 11, 4)), actor, date(2026, 10, 14))
    body = _page(actor)
    assert employee.full_name in body
    assert "2026-03-01 – 2027-02-28" in body
    assert ">20<" in body and ">3<" in body and ">17<" in body  # entitled, taken, left


def test_employee_without_a_current_year_says_so(
    employee: Employee, annual: LeaveTypeRow, actor: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("leave.views.today", lambda: date(2026, 10, 15))
    body = _page(actor)
    assert employee.full_name in body
    assert "Одоогийн ажлын жилд эрх бүртгэгдээгүй" in body


def test_balances_need_leave_view_right(db: None) -> None:
    u = User.objects.create_user("nobody_bal", password="x-long-pass-123")  # noqa: S106
    c = Client()
    c.force_login(u)
    assert c.get(reverse("leave:balances")).status_code == 403


def test_hr_can_open_balances_and_list_links_to_it(actor: User) -> None:
    u = User.objects.create_user("hr_bal", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name="HR"))
    c = Client()
    c.force_login(u)
    assert c.get(reverse("leave:balances")).status_code == 200
    assert reverse("leave:balances") in c.get(reverse("leave:list")).content.decode()


def test_new_hire_is_marked_until_the_waiting_months_pass(
    employee: Employee, annual: LeaveTypeRow, actor: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("leave.views.today", lambda: date(2026, 10, 15))
    make_employee(actor, hired=date(2026, 8, 1), register_no="УБ99112244")
    body = _page(actor)
    assert body.count("data-waiting") == 1  # the long-serving fixture employee gets no mark
    assert "Эрх 2027-02-01-аас" in body


def test_leave_pages_share_one_switch_and_a_settings_menu(actor: User) -> None:
    c = Client()
    c.force_login(actor)
    pages = (("leave:list", "Бүртгэл"), ("leave:balances", "Үлдэгдэл"), ("leave:calendar", "Багийн хуанли"))
    for name, current in pages:
        body = c.get(reverse(name)).content.decode()
        assert body.count('aria-current="page"') == 1
        assert f'aria-current="page" class="px-3 py-2 bg-violet-600 text-white">{current}<' in body
        assert "Баярын өдрүүд" in body and "Тохиргоо ▾" in body  # admin sees the settings menu
