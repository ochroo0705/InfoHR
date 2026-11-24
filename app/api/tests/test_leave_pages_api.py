"""GET /api/v1/leave/balances and /leave/calendar: the balances page and the team calendar as the React pages read them.
The rules come from leave.services.balance_page and leave.services.calendar_page; these tests pin the API's shape, its
rights, its paging, the cells and the month edges."""

from datetime import date
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from config import batching
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.utils import timezone
from employees import daily_sync
from employees.models import Department, Employee, JobRecord, JobStatus
from employees.services import macs_writes
from employees.tests.conftest import _no_offboarding_templates  # noqa: F401 (autouse: no checklist gate here)
from leave import access
from leave.models import LeaveSettings, LeaveTypeExt
from leave.services import ledger, records, writes
from leave.services.balance_page import balance_batch
from leave.services.calendar_page import (
    ANNUAL_COLOR,
    LONG_LEAVE_COLOR,
    OTHER_COLOR,
    build_calendar,
)
from leave.services.ledger import NOT_CONFIGURED
from leave.services.records import Draft
from leave.tests.conftest import make_employee
from macs.models import LeaveTypeRow

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
BALANCES = "/api/v1/leave/balances"
CALENDAR = "/api/v1/leave/calendar"
NOT_LOGGED_IN = {"field_errors": {}, "form_errors": ["Нэвтрэх шаардлагатай."], "code": "not_authenticated"}
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
FIXED_TODAY = date(2026, 11, 24)  # a Tuesday in the month the calendar tests read
BALANCES_KEYS = {"today", "rows", "next_offset", "not_configured", "can_settings", "empty_text"}
BALANCE_ROW_KEYS = {"employee_id", "employee_name", "waiting", "period"}
PERIOD_KEYS = {"start", "end", "granted", "taken", "left"}
CALENDAR_KEYS = {
    "month",
    "title",
    "days",
    "lines",
    "prev",
    "next",
    "this_month",
    "departments",
    "department",
    "not_configured",
    "can_settings",
}
DAY_KEYS = {"date", "day", "off", "holiday", "today"}
LINE_KEYS = {"employee_id", "employee_name", "cells"}
CELL_KEYS = {"kind", "leave_type_id", "title"}
PERSONAL_KEYS = {"salary", "register_no", "work_phone", "phone", "birth_date", "gender"}
KIND_BY_COLOR = {ANNUAL_COLOR: "annual", OTHER_COLOR: "other", LONG_LEAVE_COLOR: "long", "": ""}


@pytest.fixture(autouse=True)
def _no_request_time_daily_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily sync runs on the first signed-in request of a process; these tests do not want it to write grants."""
    monkeypatch.setattr(daily_sync, "_needs_sync", lambda request: False)


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_superuser("leave_pages_actor", password=PASSWORD)  # noqa: S106


@pytest.fixture
def annual(db: None) -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Ээлжийн амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=True, is_paid=True)
    return row


@pytest.fixture
def sick(db: None) -> LeaveTypeRow:
    row = LeaveTypeRow.objects.create(name="Өвчний амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=True)
    return row


@pytest.fixture
def grants_on(db: None) -> None:
    """Automatic annual grants on, so the people have current periods to show."""
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})


@pytest.fixture
def employee(actor: User, grants_on: None) -> Employee:
    return make_employee(actor, hired=date(2024, 3, 1))


@pytest.fixture
def hr(db: None) -> User:
    user = User.objects.create_user("leave_pages_hr", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.HR)[0])
    return User.objects.get(pk=user.pk)  # fresh permission cache


@pytest.fixture
def today(monkeypatch: pytest.MonkeyPatch) -> date:
    """The API reads the day with timezone.localdate(); the month edges and the today mark need a fixed day."""
    monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: FIXED_TODAY)
    return FIXED_TODAY


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _direct(name: str, codenames: list[str]) -> User:
    """A user with the given leave permissions and no role group."""
    user = User.objects.create_user(name, password=PASSWORD)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="leave"))
    return User.objects.get(pk=user.pk)


def _all_keys(value: Any) -> set[str]:
    """Every key of every object in a JSON value, at any depth."""
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found |= _all_keys(item)
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found |= _all_keys(item)
        return found
    return set()


# --- rights and login ----------------------------------------------------------------------------------------------


def test_both_routes_need_a_signed_in_user(employee: Employee) -> None:
    anonymous = Client()
    for url in (BALANCES, CALENDAR):
        response = anonymous.get(url)
        assert response.status_code == 401, url
        assert response.json() == NOT_LOGGED_IN


def test_both_routes_need_the_view_right(employee: Employee) -> None:
    nobody = _direct("leave_pages_nobody", [])
    for url in (BALANCES, CALENDAR):
        response = _client(nobody).get(url)
        assert response.status_code == 403, url
        assert response.json() == FORBIDDEN


def test_view_right_alone_is_enough(employee: Employee) -> None:
    viewer = _direct("leave_pages_viewer", ["view_leave"])
    assert _client(viewer).get(BALANCES).status_code == 200
    assert _client(viewer).get(CALENDAR).status_code == 200


def test_can_settings_follows_the_settings_right(hr: User, employee: Employee) -> None:
    assert _client(hr).get(BALANCES).json()["can_settings"] is access.can_manage_settings(hr)
    viewer = _direct("leave_pages_plain_view", ["view_leave"])
    assert _client(viewer).get(BALANCES).json()["can_settings"] is False
    assert _client(viewer).get(CALENDAR).json()["can_settings"] is False


# --- balances ------------------------------------------------------------------------------------------------------


def test_balances_keys_and_no_store_and_no_personal_data(hr: User, employee: Employee) -> None:
    response = _client(hr).get(BALANCES)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == BALANCES_KEYS
    assert body["rows"] and set(body["rows"][0]) == BALANCE_ROW_KEYS
    assert _all_keys(body) <= BALANCES_KEYS | BALANCE_ROW_KEYS | PERIOD_KEYS
    assert _all_keys(body).isdisjoint(PERSONAL_KEYS)
    assert "УБ99112233" not in response.content.decode()


def test_balance_rows_equal_the_service(hr: User, employee: Employee, actor: User) -> None:
    newcomer = make_employee(actor, hired=timezone.localdate(), register_no="УБ99112244")
    expected, _ = balance_batch(hr, 0, batching.LIST_BATCH, timezone.localdate())
    rows = _client(hr).get(BALANCES).json()["rows"]
    assert [row["employee_id"] for row in rows] == [line.employee.pk for line in expected]
    for row, line in zip(rows, expected, strict=True):
        assert row["employee_name"] == line.employee.full_name
        assert row["waiting"] == (line.waiting.isoformat() if line.waiting else None)
        if line.period is None:
            assert row["period"] is None
        else:
            assert row["period"] == {
                "start": line.period.start.isoformat(),
                "end": line.period.end.isoformat(),
                "granted": line.period.granted,
                "taken": line.period.taken,
                "left": line.period.left,
            }
    assert {row["employee_id"] for row in rows} >= {employee.pk, newcomer.pk}


def test_person_without_a_grant_has_no_period(hr: User, employee: Employee, actor: User) -> None:
    no_grant = make_employee(actor, hired=timezone.localdate(), register_no="УБ99112245")
    ledger_periods = ledger.periods_many([no_grant], timezone.localdate())[no_grant.pk][0]
    row = next(r for r in _client(hr).get(BALANCES).json()["rows"] if r["employee_id"] == no_grant.pk)
    assert (row["period"] is None) == (not any(p.current for p in ledger_periods))


def test_waiting_is_set_only_before_eligibility(hr: User, employee: Employee, actor: User) -> None:
    rows = {r["employee_id"]: r for r in _client(hr).get(BALANCES).json()["rows"]}
    expected = {line.employee.pk: line.waiting for line in balance_batch(hr, 0, 60, timezone.localdate())[0]}
    for pk, waiting in expected.items():
        assert rows[pk]["waiting"] == (waiting.isoformat() if waiting else None)
    assert rows[employee.pk]["waiting"] is None  # hired in 2024: the right has started


def test_offset_abc_is_the_first_batch(hr: User, employee: Employee) -> None:
    client = _client(hr)
    assert client.get(BALANCES, {"offset": "abc"}).json() == client.get(BALANCES).json()


def test_next_offset_follows_the_batch_size(
    monkeypatch: pytest.MonkeyPatch, hr: User, employee: Employee, actor: User
) -> None:
    make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112246")
    make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112247")
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    client = _client(hr)
    first = client.get(BALANCES).json()
    assert len(first["rows"]) == 2
    assert first["next_offset"] == 2
    second = client.get(BALANCES, {"offset": "2"}).json()
    assert len(second["rows"]) == 1
    assert second["next_offset"] is None
    seen = [row["employee_id"] for row in first["rows"] + second["rows"]]
    assert seen == [line.employee.pk for line in balance_batch(hr, 0, 60, timezone.localdate())[0]]


def test_not_configured_text_follows_the_annual_type(hr: User, employee: Employee) -> None:
    assert _client(hr).get(BALANCES).json()["not_configured"] == NOT_CONFIGURED


def test_not_configured_is_empty_with_an_annual_type(hr: User, employee: Employee, annual: LeaveTypeRow) -> None:
    assert _client(hr).get(BALANCES).json()["not_configured"] == ""


def test_empty_list_has_the_empty_text(hr: User) -> None:
    body = _client(hr).get(BALANCES).json()
    assert body["rows"] == []
    assert body["empty_text"] == "Ажилтан алга"


# --- calendar ------------------------------------------------------------------------------------------------------


def test_calendar_keys_and_no_store(hr: User, employee: Employee, today: date) -> None:
    response = _client(hr).get(CALENDAR, {"month": "2026-11"})
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == CALENDAR_KEYS
    assert set(body["days"][0]) == DAY_KEYS
    assert set(body["lines"][0]) == LINE_KEYS
    assert set(body["lines"][0]["cells"][0]) == CELL_KEYS
    assert _all_keys(body).isdisjoint(PERSONAL_KEYS)
    assert "УБ99112233" not in response.content.decode()


def test_junk_month_is_the_current_month(hr: User, employee: Employee, today: date) -> None:
    client = _client(hr)
    body = client.get(CALENDAR, {"month": "garbage"}).json()
    assert body["month"] == "2026-11"
    assert body["title"] == "Багийн хуанли — 2026-11"
    assert body["this_month"] == ""
    assert client.get(CALENDAR, {"month": "1800-01"}).json()["month"] == "2026-11"
    assert client.get(CALENDAR, {"month": "2026-10"}).json()["this_month"] == "2026-11"


def test_days_and_today_and_holiday_marks(hr: User, employee: Employee, today: date) -> None:
    writes.set_holiday_dates(2026, {date(2026, 11, 26): "Тусгаар тогтнолын өдөр"})
    days = _client(hr).get(CALENDAR, {"month": "2026-11"}).json()["days"]
    assert len(days) == 30
    assert days[0] == {"date": "2026-11-01", "day": 1, "off": True, "holiday": False, "today": False}
    assert days[23] == {"date": "2026-11-24", "day": 24, "off": False, "holiday": False, "today": True}
    assert days[25] == {"date": "2026-11-26", "day": 26, "off": True, "holiday": True, "today": False}


def test_every_line_has_one_cell_per_day(hr: User, employee: Employee, actor: User, today: date) -> None:
    make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112248")
    body = _client(hr).get(CALENDAR, {"month": "2026-11"}).json()
    assert body["lines"]
    for line in body["lines"]:
        assert len(line["cells"]) == len(body["days"])


def test_cell_kinds_match_the_service(
    hr: User, employee: Employee, actor: User, annual: LeaveTypeRow, sick: LeaveTypeRow, today: date
) -> None:
    other = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112250")
    long_person = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112251")
    JobRecord.objects.filter(employee=long_person).update(status=JobStatus.LONG_LEAVE)
    records.record(Draft(employee, annual, date(2026, 11, 2), date(2026, 11, 2)), actor, date(2026, 10, 14))
    records.record(Draft(other, sick, date(2026, 11, 10), date(2026, 11, 10)), actor, date(2026, 10, 14))

    body = _client(hr).get(CALENDAR, {"month": "2026-11"}).json()
    by_id = {line["employee_id"]: line["cells"] for line in body["lines"]}
    assert by_id[employee.pk][1] == {"kind": "annual", "leave_type_id": annual.pk, "title": annual.name}
    assert by_id[other.pk][9] == {"kind": "other", "leave_type_id": sick.pk, "title": sick.name}
    assert by_id[long_person.pk][2] == {"kind": "long", "leave_type_id": None, "title": "Урт чөлөө"}

    service = build_calendar(hr, date(2026, 11, 1), None)
    for line in service.lines:
        for cell, api_cell in zip(line.cells, by_id[line.employee.pk], strict=True):
            assert api_cell["kind"] == KIND_BY_COLOR[cell.color]


def test_off_day_has_an_empty_kind(
    hr: User, employee: Employee, annual: LeaveTypeRow, actor: User, today: date
) -> None:
    records.record(Draft(employee, annual, date(2026, 11, 2), date(2026, 11, 2)), actor, date(2026, 10, 14))
    body = _client(hr).get(CALENDAR, {"month": "2026-11"}).json()
    assert body["days"][0]["off"] is True  # 1 Nov, a Sunday
    for line in body["lines"]:
        assert line["cells"][0] == {"kind": "", "leave_type_id": None, "title": ""}


def test_leave_spanning_a_weekend_and_a_holiday_fills_only_working_days(
    hr: User, employee: Employee, annual: LeaveTypeRow, actor: User, today: date
) -> None:
    writes.set_holiday_dates(2026, {date(2026, 11, 12): "Тестийн баяр"})
    records.record(Draft(employee, annual, date(2026, 11, 6), date(2026, 11, 9)), actor, date(2026, 10, 14))
    records.record(Draft(employee, annual, date(2026, 11, 11), date(2026, 11, 13)), actor, date(2026, 10, 14))
    body = _client(hr).get(CALENDAR, {"month": "2026-11"}).json()
    cells = next(line for line in body["lines"] if line["employee_id"] == employee.pk)["cells"]
    days = body["days"]
    assert days[5]["date"] == "2026-11-06" and days[6]["off"] and days[7]["off"]  # Fri, Sat, Sun
    assert days[11]["holiday"] is True and days[11]["off"] is True  # 12 Nov, the holiday
    for index in (5, 8, 10, 12):  # Fri 6, Mon 9, Wed 11, Fri 13: working days with leave
        assert cells[index]["kind"] == "annual", index
        assert cells[index]["leave_type_id"] == annual.pk
    for index in (6, 7, 11):  # Sat 7, Sun 8, holiday 12: off days, never filled
        assert cells[index] == {"kind": "", "leave_type_id": None, "title": ""}, index


def test_departments_and_department_echo(hr: User, employee: Employee, today: date) -> None:
    dept = Department.objects.get(name="Санхүү")
    body = _client(hr).get(CALENDAR, {"month": "2026-11", "department": str(dept.pk)}).json()
    assert body["department"] == dept.pk
    expected = [{"value": d.pk, "label": d.name} for d in Department.objects.exclude(ext__active=False)]
    assert body["departments"] == expected
    assert _client(hr).get(CALENDAR, {"department": "abc"}).json()["department"] is None


def test_scoped_user_cannot_widen_by_department(actor: User, employee: Employee, today: date) -> None:
    dept_a = Department.objects.get(name="Санхүү")
    dept_b = macs_writes.save_department("Бусад")
    outsider = make_employee(actor, hired=date(2024, 3, 1), register_no="УБ99112252")
    Employee.objects.filter(pk=outsider.pk).update(department=dept_b)  # the scope reads this column
    JobRecord.objects.filter(employee=outsider).update(department=dept_b)

    scoped = User.objects.create_user("leave_pages_scoped", password=PASSWORD)
    scoped.groups.add(Group.objects.get_or_create(name=roles.HR)[0])
    AccessScope.objects.create(user=scoped, limited=True, department_ids=[dept_a.pk])
    scoped = User.objects.get(pk=scoped.pk)

    body = _client(scoped).get(CALENDAR, {"month": "2026-11", "department": str(dept_b.pk)}).json()
    ids = {line["employee_id"] for line in body["lines"]}
    assert outsider.pk not in ids
    assert employee.pk not in ids


def test_prev_and_next_edges(hr: User, employee: Employee, today: date) -> None:
    client = _client(hr)
    january = client.get(CALENDAR, {"month": "1900-01"}).json()
    assert january["prev"] == ""
    assert january["next"] == "1900-02"
    december = client.get(CALENDAR, {"month": "2100-12"}).json()
    assert december["next"] == ""
    assert december["prev"] == "2100-11"


def test_long_leave_cells_fall_on_working_days(hr: User, employee: Employee, today: date) -> None:
    """A long-leave person with no counted leave gets long cells on working days only."""
    JobRecord.objects.filter(employee=employee).update(status=JobStatus.LONG_LEAVE)
    body = _client(hr).get(CALENDAR, {"month": "2026-11"}).json()
    cells = next(line for line in body["lines"] if line["employee_id"] == employee.pk)["cells"]
    assert cells[1]["kind"] == "long"  # 2 Nov, Monday
    assert cells[0]["kind"] == ""  # 1 Nov, Sunday


def test_settings_right_alone_is_not_enough(actor: User, employee: Employee) -> None:
    user = _direct("leave_pages_settings_only", [])
    user.user_permissions.add(Permission.objects.get(codename="manage_leave_settings", content_type__app_label="leave"))
    user = User.objects.get(pk=user.pk)
    assert _client(user).get(CALENDAR).status_code == 403
    assert _client(user).get(BALANCES).status_code == 403
