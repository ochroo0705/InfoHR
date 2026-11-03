import re
from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees.models import Employee, JobRecord, JobStatus
from macs.models import LeaveTypeRow
from psycopg.types.range import DateRange

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


def test_calendar_title_names_the_page_once(actor: User) -> None:
    c = Client()
    c.force_login(actor)
    body = c.get(reverse("leave:calendar"), {"month": "2026-11"}).content.decode()
    assert "<title>Чөлөөний хуанли · Info HR</title>" in body


def test_calendar_highlights_today(actor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("leave.views.today", lambda: date(2026, 11, 3))
    c = Client()
    c.force_login(actor)
    body = c.get(reverse("leave:calendar"), {"month": "2026-11"}).content.decode()
    assert 'data-today="2026-11-03"' in body
    assert body.count("data-today=") == 1


def test_calendar_legend_explains_every_mark(actor: User) -> None:
    c = Client()
    c.force_login(actor)
    body = c.get(reverse("leave:calendar"), {"month": "2026-11"}).content.decode()
    assert "data-calendar-legend" in body
    legend = body.split("data-calendar-legend", 1)[1].split("</div>", 1)[0]
    for text in ("Ээлжийн амралт", "Бусад чөлөө", "Ажлын бус өдөр", "Улаан тоо", "Өнөөдөр"):
        assert text in legend


def test_leave_running_past_the_window_is_drawn(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    # Long maternity-style leave: starts before November and ends after it.
    records.record(
        Draft(employee, annual, date(2026, 10, 1), date(2027, 2, 28), override_reason="Тест"), actor, date(2026, 9, 20)
    )
    u = User.objects.create_user("acc2", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name="Accountant"))
    c = Client()
    c.force_login(u)
    resp = c.get(reverse("leave:calendar"), {"month": "2026-11"})
    line = next(cells for e, cells in resp.context["lines"] if e.pk == employee.pk)
    working = [cell for cell in line if not cell.off]
    assert working and all(cell.leave is not None for cell in working)


def _month_cells(body: str, employee: Employee) -> list[str]:
    """The <td> tags of one person's row in the calendar, in day order (day 1 first)."""
    if employee.full_name not in body:  # a person with no job in the month has no row
        return []
    row = body.split(employee.full_name, 1)[1].split("</tr>", 1)[0]
    return re.findall(r"<td\b[^>]*>", row)


def _long_leave_days(body: str, employee: Employee) -> list[int]:
    return [n for n, td in enumerate(_month_cells(body, employee), start=1) if "data-long-leave" in td]


def test_long_leave_return_day_is_not_drawn(employee: Employee, actor: User) -> None:
    """The period is [start, end): the return day itself (10 Nov) is not a long-leave day, the day before is."""
    _on_long_leave(employee, date(2024, 3, 1), date(2026, 11, 10))
    days = _long_leave_days(_calendar(actor), employee)
    assert days == [2, 3, 4, 5, 6, 9]
    assert 9 in days and 10 not in days


def _on_long_leave(employee: Employee, start: date, end: date) -> None:
    """Make the employee's only job record a long-leave period [start, end) (what a leave_start event writes)."""
    JobRecord.objects.filter(employee=employee).update(status=JobStatus.LONG_LEAVE, period=DateRange(start, end, "[)"))


def _calendar(actor: User, month: str = "2026-11") -> str:
    c = Client()
    c.force_login(actor)
    return c.get(reverse("leave:calendar"), {"month": month}).content.decode()


def test_long_leave_draws_working_days_only(employee: Employee, actor: User) -> None:
    writes.set_holiday_dates(2026, {date(2026, 11, 26): "Тусгаар тогтнолын өдөр"})
    JobRecord.objects.filter(employee=employee).update(status=JobStatus.LONG_LEAVE)  # long leave from hire on
    body = _calendar(actor)
    working = [n for n in range(1, 31) if date(2026, 11, n).weekday() < 5 and n != 26]
    assert _long_leave_days(body, employee) == working and len(working) == 20
    cells = _month_cells(body, employee)
    assert "bg-sky-200" in cells[1] and 'title="Урт чөлөө"' in cells[1]  # 2 Nov, Monday
    assert "data-long-leave" not in cells[0]  # 1 Nov, Sunday: grey, no long-leave mark
    assert "bg-sky-200" not in cells[25] and "data-long-leave" not in cells[25]  # 26 Nov, public holiday


def test_counted_leave_wins_over_long_leave(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    writes.set_holiday_dates(2026, {date(2026, 11, 26): "Тусгаар тогтнолын өдөр"})
    JobRecord.objects.filter(employee=employee).update(status=JobStatus.LONG_LEAVE)
    records.record(Draft(employee, annual, date(2026, 11, 2), date(2026, 11, 4)), actor, date(2026, 10, 14))
    body = _calendar(actor)
    cells = _month_cells(body, employee)
    for i in (1, 2, 3):  # 2-4 Nov: annual leave, not long leave
        assert "bg-violet-200" in cells[i] and "data-long-leave" not in cells[i]
    assert "data-long-leave" in cells[4]  # 5 Nov, Thursday: long leave again


def test_long_leave_started_before_month_and_ending_after_is_drawn_all_month(employee: Employee, actor: User) -> None:
    writes.set_holiday_dates(2026, {date(2026, 11, 26): "Тусгаар тогтнолын өдөр"})
    _on_long_leave(employee, date(2024, 3, 1), date(2026, 12, 15))
    body = _calendar(actor)
    working = [n for n in range(1, 31) if date(2026, 11, n).weekday() < 5 and n != 26]
    assert _long_leave_days(body, employee) == working


def test_long_leave_ended_before_month_shows_nothing(employee: Employee, actor: User) -> None:
    _on_long_leave(employee, date(2024, 3, 1), date(2026, 10, 31))
    assert _long_leave_days(_calendar(actor), employee) == []


def test_calendar_legend_explains_long_leave(actor: User) -> None:
    body = _calendar(actor)
    legend = body.split("data-calendar-legend", 1)[1].split("</div>", 1)[0]
    assert "Урт чөлөө" in legend and "bg-sky-200" in legend
