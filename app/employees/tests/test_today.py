from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from leave.models import LeaveSettings
from leave.services import records
from leave.services import writes as leave_writes
from leave.services.records import Draft
from macs.models import LeaveAssign, LeaveTypeRow, LegalHoliday

from employees import today
from employees.listing import Row, employee_rows
from employees.models import Employee
from employees.services import history

from .conftest import hire_values, link_login
from .test_views import login_as

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def _user(role: str, name: str = "t1") -> User:
    u = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=role))
    return u


def _rows() -> list[Row]:
    return employee_rows(Employee.objects.all(), TODAY)


def test_home_opens_the_today_page(client: Client) -> None:
    login_as(client, "HR")
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"] == reverse("employees:today")


def test_today_page_needs_login(client: Client) -> None:
    assert client.get(reverse("employees:today")).status_code == 302


def test_today_page_shows_tiles_and_empty_states(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(reverse("employees:today")).content.decode()
    assert 'data-tile="headcount">1<' in body
    assert 'data-tile="away">0<' in body
    assert 'data-tile="orders"' in body  # HR handles orders
    assert "Өнөөдөр чөлөөтэй хүн алга." in body
    assert 'class="card-soft' in body


def test_orders_tile_hidden_without_the_manage_right(hired: Employee) -> None:
    assert today.pending_orders(_user("Accountant", "acc"), _rows()) is None


def test_pending_orders_counts_unnumbered_orders(hired: Employee) -> None:
    assert today.pending_orders(_user("HR", "hr1"), _rows()) == hired.hr_orders.filter(state="pending").count()
    hired.hr_orders.update(state="registered")
    assert today.pending_orders(_user("HR", "hr2"), _rows()) == 0


def test_headcount_skips_people_who_left(hired: Employee) -> None:
    assert today.headcount(_rows()) == 1
    assert today.headcount([]) == 0


@pytest.fixture
def annual(db: None) -> LeaveTypeRow:
    return leave_writes.save_leave_type(
        "Ээлжийн амралт", {"is_paid": True, "uses_annual_balance": True, "is_active": True, "order": 1}
    )


def test_away_lists_people_on_leave_today(hired: Employee, annual: LeaveTypeRow) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})
    actor = User.objects.create_superuser("leave_actor", password="x-long-pass-123")  # noqa: S106
    records.record(Draft(hired, annual, date(2026, 10, 13), date(2026, 10, 16)), actor, date(2026, 10, 1))
    found = today.away_on(_user("HR", "hr3"), _rows(), TODAY)
    assert [(a.row.employee.pk, a.label, a.until) for a in found] == [(hired.pk, annual.name, date(2026, 10, 16))]
    assert today.away_on(_user("HR", "hr4"), _rows(), date(2026, 10, 17)) == []


def test_away_is_empty_without_the_leave_right(hired: Employee) -> None:
    assert today.away_on(User.objects.create_user("nobody", password="x-long-pass-123"), _rows(), TODAY) == []  # noqa: S106


def test_birthday_and_anniversary_inside_the_window(hired: Employee) -> None:
    hired.birth_date = date(1990, 10, 20)
    hired.first_hire_date = date(2023, 10, 31)
    hired.save()
    found = today.upcoming(_user("HR", "hr5"), _rows(), TODAY)
    assert [(u.kind, u.on, u.years) for u in found] == [
        ("birthday", date(2026, 10, 20), None),
        ("anniversary", date(2026, 10, 31), 3),
    ]


def test_dates_outside_the_window_and_first_year_are_left_out(hired: Employee) -> None:
    hired.birth_date = date(1990, 12, 25)  # 72 days away
    hired.first_hire_date = date(2026, 10, 20)  # 0 years: that is the hire date itself
    hired.save()
    assert today.upcoming(_user("HR", "hr6"), _rows(), TODAY) == []


def test_birthday_wraps_into_next_year(hired: Employee) -> None:
    hired.birth_date = date(1990, 1, 3)
    hired.save()
    found = today.upcoming(_user("HR", "hr7"), _rows(), date(2026, 12, 20))
    assert [u.on for u in found if u.kind == "birthday"] == [date(2027, 1, 3)]


def test_leap_day_birthday_falls_on_28_feb(hired: Employee) -> None:
    hired.birth_date = date(1992, 2, 29)
    hired.save()
    found = today.upcoming(_user("HR", "hr8"), _rows(), date(2027, 2, 10))
    assert [u.on for u in found if u.kind == "birthday"] == [date(2027, 2, 28)]


def test_birthday_needs_the_personal_right(hired: Employee) -> None:
    hired.birth_date = date(1990, 10, 20)
    hired.save()
    kinds = [u.kind for u in today.upcoming(_user("Accountant", "acc2"), _rows(), TODAY)]
    assert "birthday" not in kinds


def test_employee_sees_only_their_own_row(client: Client, hired: Employee) -> None:
    user = login_as(client, "Employee", "emp_self")
    link_login(hired, user)
    body = client.get(reverse("employees:today")).content.decode()
    assert 'data-tile="headcount">1<' in body
    assert 'data-tile="orders"' not in body


@pytest.fixture
def leave_actor(db: None) -> User:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})
    return User.objects.create_superuser("leave_actor2", password="x-long-pass-123")  # noqa: S106


def _record(employee: Employee, annual: LeaveTypeRow, start: date, end: date, actor: User) -> None:
    records.record(Draft(employee, annual, start, end), actor, date(2026, 10, 1))


def _old_leave(employee: Employee, leave_type: LeaveTypeRow, start: date, end: date) -> LeaveAssign:
    """A row as the old program wrote it (status NULL = recorded). The validator refuses these shapes:
    a weekend-only leave has no working day, and a leave this long overdraws the annual balance."""
    return LeaveAssign.objects.create(employee=employee, leave_type=leave_type, date1=start, date2=end, status=None)


def _second_employee(actor: User, job_values: dict[str, object]) -> Employee:
    values = hire_values("УБ99112234") | {"given_name": "Бат"}
    return history.hire(values, {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor)


def _strip(rows: list[Row] | None = None, day: date = TODAY) -> today.AwayStrip:
    return today.away_strip(_user("HR", "strip"), _rows() if rows is None else rows, day)


# The away counting rules of the old per-person timeline, kept on the strip that replaced it.


def test_strip_window_is_14_days_from_today_with_weekends_off(hired: Employee) -> None:
    s = _strip()
    assert len(s.days) == today.WINDOW_DAYS
    assert s.days[0].day == TODAY and s.days[0].is_today
    assert s.days[13].day == date(2026, 10, 27)
    assert [d.day for d in s.days if d.off] == [date(2026, 10, n) for n in (17, 18, 24, 25)]


def test_strip_counts_zero_on_working_days_and_none_off(hired: Employee) -> None:
    assert _strip().counts == [0, 0, 0, None, None, 0, 0, 0, 0, 0, None, None, 0, 0]


def test_strip_counts_a_leave_cut_on_the_left_from_today(
    hired: Employee, annual: LeaveTypeRow, leave_actor: User
) -> None:
    _record(hired, annual, date(2026, 10, 13), date(2026, 10, 16), leave_actor)
    assert _strip().counts[:4] == [1, 1, 1, None]


def test_strip_weekend_only_leave_gets_no_count(hired: Employee, annual: LeaveTypeRow) -> None:
    _old_leave(hired, annual, date(2026, 10, 17), date(2026, 10, 18))
    assert _strip().counts == [0, 0, 0, None, None, 0, 0, 0, 0, 0, None, None, 0, 0]


def test_strip_one_person_with_overlapping_leaves_is_counted_once(hired: Employee, annual: LeaveTypeRow) -> None:
    _old_leave(hired, annual, date(2026, 10, 14), date(2026, 10, 16))
    _old_leave(hired, annual, date(2026, 10, 15), date(2026, 10, 16))
    s = _strip()
    assert s.counts[:3] == [1, 1, 1]
    assert s.today_split == [(annual.name, 1)]


def test_strip_leave_over_the_whole_window_counts_every_working_day(hired: Employee, annual: LeaveTypeRow) -> None:
    _old_leave(hired, annual, date(2026, 10, 1), date(2026, 11, 30))
    assert _strip().counts == [1, 1, 1, None, None, 1, 1, 1, 1, 1, None, None, 1, 1]


def test_strip_marks_public_holidays_off_with_their_name(
    hired: Employee, annual: LeaveTypeRow, leave_actor: User
) -> None:
    LegalHoliday.objects.create(
        name="Тестийн баяр", start_date=date(2026, 10, 19), end_date=date(2026, 10, 19), hdays=1
    )
    _record(hired, annual, date(2026, 10, 16), date(2026, 10, 20), leave_actor)  # Fri .. Tue across Mon 19
    s = _strip()
    assert s.days[5].off is True and s.days[5].holiday == "Тестийн баяр"
    assert s.days[0].holiday == ""
    assert s.counts[5] is None
    assert s.counts[2] == 1 and s.counts[6] == 1


def test_strip_skips_people_who_left(hired: Employee, annual: LeaveTypeRow, leave_actor: User) -> None:
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 16), leave_actor)
    s = _strip([replace(r, state="left") for r in _rows()])
    assert s.counts[:3] == [0, 0, 0]
    assert s.today_split == []


def test_strip_query_count_does_not_grow_with_people(
    hired: Employee,
    annual: LeaveTypeRow,
    leave_actor: User,
    actor: User,
    job_values: dict[str, object],
) -> None:
    hr = _user("HR", "strip_q")
    today.away_strip(hr, _rows(), TODAY)  # warm the user's permission cache

    def strip_queries() -> int:
        rows = _rows()  # built outside the capture: employee_rows is the page's own query, not the strip's
        with CaptureQueriesContext(connection) as ctx:
            today.away_strip(hr, rows, TODAY)
        return len(ctx.captured_queries)

    records.record(Draft(hired, annual, date(2026, 10, 14), date(2026, 10, 15)), leave_actor, date(2026, 10, 1))
    one = strip_queries()
    second = _second_employee(actor, job_values)
    records.record(Draft(second, annual, date(2026, 10, 14), date(2026, 10, 16)), leave_actor, date(2026, 10, 1))
    assert strip_queries() == one


@pytest.fixture
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> date:
    """The Today page reads timezone.localdate(); freeze it so the fixed leave dates sit in the window."""
    monkeypatch.setattr(timezone, "localdate", lambda *a, **k: TODAY)
    return TODAY
