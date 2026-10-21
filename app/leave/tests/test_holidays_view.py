from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from macs.models import Employee, LeaveAssign, LeaveTypeRow

from leave.services import calendar, writes

pytestmark = pytest.mark.django_db


def _client(group: str) -> Client:
    u = User.objects.create_user(f"u_{group}", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=group))
    c = Client()
    c.force_login(u)
    return c


def test_accountant_forbidden() -> None:
    assert _client("Accountant").get(reverse("leave:holidays")).status_code == 403


def test_prefill_add_delete() -> None:
    c = _client("Admin")
    url = reverse("leave:holidays") + "?year=2027"
    c.post(url, {"action": "prefill"})
    assert len(calendar.holiday_names(2027)) == len(calendar.FIXED_HOLIDAYS)
    c.post(url, {"action": "add", "date": "2027-02-06", "name": "Цагаан сар"})
    assert calendar.holiday_names(2027)[date(2027, 2, 6)] == "Цагаан сар"
    assert "Цагаан сар" in c.get(url).content.decode()
    c.post(url, {"action": "delete", "date": "2027-02-06"})
    assert date(2027, 2, 6) not in calendar.holiday_names(2027)


def test_add_rejects_bad_date() -> None:
    r = _client("Admin").post(reverse("leave:holidays") + "?year=2027", {"action": "add", "date": "x", "name": "a"})
    assert r.status_code == 200 and "Огноо буруу" in r.content.decode()


def test_add_rejects_date_from_another_year() -> None:
    r = _client("Admin").post(
        reverse("leave:holidays") + "?year=2027", {"action": "add", "date": "2028-01-01", "name": "a"}
    )
    assert r.status_code == 200 and "сонгосон жилийнх" in r.content.decode()
    assert calendar.holiday_names(2028) == {}


def test_add_form_posts_with_htmx_and_error_stays_in_place() -> None:
    c = _client("Admin")
    url = reverse("leave:holidays") + "?year=2027"
    assert 'hx-select="main"' in c.get(url).content.decode()
    r = c.post(url, {"action": "add", "date": "x", "name": "a"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and "Огноо буруу" in r.content.decode()


NOV_WEEK = (date(2026, 11, 2), date(2026, 11, 6))  # Mon-Fri, 5 working days


def _add_wed_holiday() -> None:
    c = _client("Admin")
    c.post(reverse("leave:holidays") + "?year=2026", {"action": "add", "date": "2026-11-04", "name": "Амралт"})


def test_recount_updates_info_hr_rows(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = writes.record_assign(employee, annual, *NOV_WEEK, 5, "", actor)
    _add_wed_holiday()
    a.refresh_from_db()
    assert a.adays == 4


def test_recount_skips_old_rows(employee: Employee, annual: LeaveTypeRow) -> None:
    old = LeaveAssign.objects.create(
        employee=employee,
        leave_type=annual,
        date1=NOV_WEEK[0],
        date2=NOV_WEEK[1],
        status=LeaveAssign.APPROVED,
        adays=5,
        comment="",
    )
    _add_wed_holiday()
    old.refresh_from_db()
    assert old.adays == 5


def test_recount_skips_cancelled(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    a = writes.record_assign(employee, annual, *NOV_WEEK, 5, "", actor)
    writes.cancel_assign(a, writes.snapshot(a), "тест", mistake=False, by=actor)
    _add_wed_holiday()
    a.refresh_from_db()
    assert a.adays == 5
