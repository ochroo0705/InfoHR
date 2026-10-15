import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

from leave.models import Holiday
from leave.services import calendar

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
    c = _client("HR")
    url = reverse("leave:holidays") + "?year=2027"
    c.post(url, {"action": "prefill"})
    assert Holiday.objects.filter(date__year=2027).count() == len(calendar.FIXED_HOLIDAYS)
    c.post(url, {"action": "add", "date": "2027-02-06", "name": "Цагаан сар"})
    h = Holiday.objects.get(date="2027-02-06")
    assert "Цагаан сар" in c.get(url).content.decode()
    c.post(url, {"action": "delete", "id": h.pk})
    assert not Holiday.objects.filter(pk=h.pk).exists()


def test_add_rejects_bad_date() -> None:
    r = _client("HR").post(reverse("leave:holidays") + "?year=2027", {"action": "add", "date": "x", "name": "a"})
    assert r.status_code == 200 and "Огноо буруу" in r.content.decode()


def test_holiday_add_and_delete_recount_leaves() -> None:
    from datetime import date
    from decimal import Decimal

    from leave.models import Leave, LeaveType
    from leave.services import records
    from leave.tests.conftest import make_employee

    c = _client("HR")
    actor = User.objects.get(username="u_HR")
    e = make_employee(actor, hired=date(2024, 3, 1))
    draft = records.Draft(e, LeaveType.objects.get(code="annual"), date(2026, 11, 2), date(2026, 11, 6))
    leave = records.record(draft, actor, date(2026, 10, 14))
    url = reverse("leave:holidays") + "?year=2026"
    c.post(url, {"action": "add", "date": "2026-11-03", "name": "x"})
    assert Leave.objects.get(pk=leave.pk).working_days == Decimal(4)
    c.post(url, {"action": "delete", "id": Holiday.objects.get(date="2026-11-03").pk})
    assert Leave.objects.get(pk=leave.pk).working_days == Decimal(5)


def test_add_form_posts_with_htmx_and_error_stays_in_place() -> None:
    c = _client("HR")
    url = reverse("leave:holidays") + "?year=2027"
    assert 'hx-select="main"' in c.get(url).content.decode()
    r = c.post(url, {"action": "add", "date": "x", "name": "a"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and "Огноо буруу" in r.content.decode()
