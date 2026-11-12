"""My page: the manager's team strip («Багийн чөлөө») and the holiday line; the Today page's link to My page.

A manager sees names and dates only (no leave type) for the own team, even without the leave view right.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from leave.models import LeaveTypeExt
from macs.models import LeaveAssign, LeaveTypeRow, LegalHoliday

from employees import views_me
from employees.models import Employee, JobRecord
from employees.scope import team_ids
from employees.services import history
from employees.tests.conftest import hire_values, link_login

from .test_views import login_as

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 30)
PASSWORD = "x-long-pass-123"  # noqa: S105
LEAVE_TYPE = "Өвчний амралт"


@pytest.fixture(autouse=True)
def _frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """The My page and the Today page read timezone.localdate(); freeze it so the fixed dates sit in the window."""
    monkeypatch.setattr(timezone, "localdate", lambda *a, **k: TODAY)


@pytest.fixture
def sick() -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name=LEAVE_TYPE)
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=True)
    return row


@pytest.fixture
def boss(actor: User, job_values: dict[str, Any]) -> Employee:
    values = hire_values("УБ99000010") | {"given_name": "Батаа"}
    return history.hire(values, {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor)


def _hire(actor: User, job_values: dict[str, Any], register_no: str, given: str, manager: Employee | None) -> Employee:
    values = hire_values(register_no) | {"given_name": given}
    emp = history.hire(values, {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor)
    if manager is not None:
        JobRecord.objects.filter(employee=emp).update(manager=manager)
    return emp


def _leave(employee: Employee, leave_type: LeaveTypeRow, start: date, end: date) -> None:
    """A recorded leave as the old program wrote it (status NULL = recorded)."""
    LeaveAssign.objects.create(employee=employee, leave_type=leave_type, date1=start, date2=end, status=None)


def _away(manager: Employee) -> list[dict[str, Any]]:
    return views_me._team_away(manager, TODAY, team_ids(manager.pk, TODAY))


def _login(employee: Employee, name: str) -> Client:
    """A login in the Employee role, linked to `employee` (may use My page, no employee rights)."""
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name="Employee")[0])
    link_login(employee, user)
    client = Client()
    client.force_login(user)
    return client


def test_team_away_lists_only_the_team(
    actor: User, boss: Employee, job_values: dict[str, Any], sick: LeaveTypeRow
) -> None:
    report = _hire(actor, job_values, "УБ99000011", "Болд", boss)
    _hire(actor, job_values, "УБ99000012", "Отгон", boss)  # no leave
    outsider = _hire(actor, job_values, "УБ99000013", "Гантулга", None)
    _leave(report, sick, date(2026, 11, 2), date(2026, 11, 3))
    _leave(outsider, sick, date(2026, 11, 2), date(2026, 11, 3))

    found = _away(boss)

    assert [(a["employee"].pk, a["start"], a["end"]) for a in found] == [
        (report.pk, date(2026, 11, 2), date(2026, 11, 3))
    ]


def test_team_away_lists_a_report_on_leave_today(
    actor: User, boss: Employee, job_values: dict[str, Any], sick: LeaveTypeRow
) -> None:
    report = _hire(actor, job_values, "УБ99000014", "Болд", boss)
    _leave(report, sick, TODAY, TODAY)
    assert [a["employee"].pk for a in _away(boss)] == [report.pk]


def test_team_away_ignores_leave_after_the_window(
    actor: User, boss: Employee, job_values: dict[str, Any], sick: LeaveTypeRow
) -> None:
    report = _hire(actor, job_values, "УБ99000015", "Болд", boss)
    _leave(report, sick, date(2026, 11, 13), date(2026, 11, 14))  # window is 2026-10-30 .. 2026-11-12
    assert _away(boss) == []


def test_team_away_empty_without_reports(actor: User, job_values: dict[str, Any], sick: LeaveTypeRow) -> None:
    alone = _hire(actor, job_values, "УБ99000016", "Ганаа", None)
    assert _away(alone) == []


def test_me_page_shows_team_block_for_a_manager(
    actor: User, boss: Employee, job_values: dict[str, Any], sick: LeaveTypeRow
) -> None:
    report = _hire(actor, job_values, "УБ99000017", "Болд", boss)
    _leave(report, sick, date(2026, 11, 2), date(2026, 11, 3))
    body = _login(boss, "boss_page").get(reverse("me")).content.decode()
    assert "data-team-away" in body
    assert "Багийн чөлөө" in body
    assert "Болд · 2026-11-02 – 2026-11-03" in body


def test_team_block_says_when_nobody_is_away(actor: User, boss: Employee, job_values: dict[str, Any]) -> None:
    _hire(actor, job_values, "УБ99000018", "Болд", boss)
    body = _login(boss, "boss_quiet").get(reverse("me")).content.decode()
    assert "data-team-away" in body
    assert "Ойрын 14 хоногт чөлөөтэй хүн алга." in body


def test_me_page_has_no_team_block_without_reports(actor: User, job_values: dict[str, Any]) -> None:
    alone = _hire(actor, job_values, "УБ99000019", "Ганаа", None)
    body = _login(alone, "alone_page").get(reverse("me")).content.decode()
    assert "data-team-away" not in body
    assert "Багийн чөлөө" not in body


def test_team_block_shows_no_leave_type(
    actor: User, boss: Employee, job_values: dict[str, Any], sick: LeaveTypeRow
) -> None:
    report = _hire(actor, job_values, "УБ99000020", "Болд", boss)
    _leave(report, sick, date(2026, 11, 2), date(2026, 11, 3))
    body = _login(boss, "boss_type").get(reverse("me")).content.decode()
    assert "data-team-away" in body
    assert LEAVE_TYPE not in body


def test_me_page_holiday_line_when_a_holiday_is_coming(actor: User, boss: Employee) -> None:
    LegalHoliday.objects.create(name="Тестийн баяр", start_date=date(2026, 11, 2), end_date=date(2026, 11, 2), hdays=1)
    body = _login(boss, "boss_hol").get(reverse("me")).content.decode()
    assert "Баяр ёслол: 2026-11-02 Тестийн баяр" in body


def test_me_page_no_holiday_line_when_none(actor: User, boss: Employee) -> None:
    body = _login(boss, "boss_nohol").get(reverse("me")).content.decode()
    assert "Баяр ёслол" not in body


def test_today_links_to_own_page_only_for_a_linked_login(client: Client, boss: Employee) -> None:
    user = User.objects.create_user("hr_linked", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name="HR")[0])
    link_login(boss, user)
    client.force_login(user)
    body = client.get(reverse("employees:today")).content.decode()
    assert f'href="{reverse("me")}"' in body
    assert "Миний хуудас →" in body

    client.logout()
    login_as(client, "HR", "hr_unlinked")
    body = client.get(reverse("employees:today")).content.decode()
    assert "Миний хуудас →" not in body


def test_one_person_with_two_leaves_is_one_entry(
    actor: User, boss: Employee, job_values: dict[str, Any], sick: LeaveTypeRow
) -> None:
    report = _hire(actor, job_values, "УБ99000021", "Болд", boss)
    _leave(report, sick, date(2026, 11, 2), date(2026, 11, 3))
    _leave(report, sick, date(2026, 11, 9), date(2026, 11, 10))
    found = _away(boss)
    assert [(a["employee"].pk, a["start"], a["end"]) for a in found] == [
        (report.pk, date(2026, 11, 2), date(2026, 11, 10))
    ]
    body = _login(boss, "boss_two").get(reverse("me")).content.decode()
    assert body.count("Болд · ") == 1


def test_team_strip_plus_n_counts_people(
    actor: User, boss: Employee, job_values: dict[str, Any], sick: LeaveTypeRow
) -> None:
    for i in range(9):
        report = _hire(actor, job_values, f"УБ9900003{i}", f"Ажилтан{i}", boss)
        _leave(report, sick, date(2026, 11, 2), date(2026, 11, 2))
        _leave(report, sick, date(2026, 11, 4), date(2026, 11, 4))  # a second leave must not add a line
    body = _login(boss, "boss_many").get(reverse("me")).content.decode()
    assert body.count(" · 2026-11-02 – 2026-11-04") == 8
    assert "+1</p>" in body


def test_manager_without_leave_view_right_sees_only_own_team(
    actor: User, boss: Employee, job_values: dict[str, Any], sick: LeaveTypeRow
) -> None:
    report = _hire(actor, job_values, "УБ99000040", "Болд", boss)
    outsider = _hire(actor, job_values, "УБ99000041", "Гантулга", None)
    _leave(report, sick, date(2026, 11, 2), date(2026, 11, 3))
    _leave(outsider, sick, date(2026, 11, 4), date(2026, 11, 5))
    client = _login(boss, "boss_privacy")
    user = User.objects.get(username="boss_privacy")
    assert not user.has_perm("leave.view_leave")
    body = client.get(reverse("me")).content.decode()
    assert "Болд · 2026-11-02 – 2026-11-03" in body
    assert "Гантулга" not in body
    assert "2026-11-04" not in body
    assert LEAVE_TYPE not in body
