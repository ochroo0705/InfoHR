"""The Excel files of the employee and system logs: who may download, the rows, visibility, text cells, the cap."""

import io
from datetime import date
from decimal import Decimal
from typing import Any

import openpyxl
import pytest
from accounts.audit import Category
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group, Permission
from django.http import QueryDict
from django.test import Client
from django.utils import timezone
from employees.models import ActivityEntry, ActivityKind, Employee
from employees.services import history, macs_writes

from logs import export
from logs.employee_query import filtered, parse_filter

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
EMPLOYEE_URL = "/logs/export/"
SYSTEM_URL = "/logs/system/export/"
HIDDEN = "Цалингийн нууц өөрчлөлт"  # a sensitive (salary) entry
FORMULA = '=HYPERLINK("x")'
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _user(name: str, role: str | None, *, first: str = "", last: str = "") -> User:
    user = User.objects.create_user(name, password=PASSWORD, first_name=first, last_name=last)  # noqa: S106
    if role is not None:
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _take_export_switch(role: str) -> None:
    """Take `accounts.export_lists` away from a role group (the migrations give it to HR, Admin and Accountant)."""
    export_perm = Permission.objects.get(codename="export_lists", content_type__app_label="accounts")
    Group.objects.get(name=role).permissions.remove(export_perm)


def _hire(actor: User, family: str, given: str, register_no: str) -> Employee:
    job: dict[str, Any] = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {
        "family_name": family,
        "given_name": given,
        "register_no": register_no,
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
    }
    return history.hire(values, {}, start=date(2026, 1, 5), job=job, salary=Decimal("2500000"), by=actor)


def _entry(employee: Employee, message: str, **fields: Any) -> ActivityEntry:
    fields.setdefault("kind", ActivityKind.CHANGED)
    return ActivityEntry.objects.create(employee=employee, message=message, **fields)


def _system_row(message: str, **fields: Any) -> SystemLogEntry:
    fields.setdefault("actor_name", "system_actor")
    fields.setdefault("category", Category.ACCESS)
    fields.setdefault("action", "login")
    fields.setdefault("changes", [])
    return SystemLogEntry.objects.create(message=message, **fields)


def _sheet(response: Any) -> Any:
    """The first sheet of a downloaded file. Untyped on purpose: openpyxl's stubs type `active` as Optional."""
    return openpyxl.load_workbook(io.BytesIO(response.content)).active


def _messages(ws: Any, column: int) -> list[str]:
    """The text of one column below the headers, empty cells left out."""
    return [str(row[column - 1].value) for row in ws.iter_rows(min_row=2) if row[column - 1].value is not None]


@pytest.fixture
def actor(db: None) -> User:
    return _user("log_xlsx_actor", None)


@pytest.fixture
def own(actor: User) -> Employee:
    employee = _hire(actor, "Батын", "Сараа", "УБ99120001")
    _entry(employee, "Хаяг өөрчлөгдсөн", changes=[{"field": "Хаяг", "old": "Сүхбаатар", "new": "Баянзүрх"}])
    _entry(employee, HIDDEN, sensitive=True, changes=[{"field": "Цалин", "old": "1000", "new": "2000"}])
    _entry(employee, FORMULA)
    return employee


@pytest.fixture
def other(actor: User) -> Employee:
    employee = _hire(actor, "Доржийн", "Ганзориг", "УБ99120002")
    _entry(employee, "Ажлын байр шилжсэн")
    return employee


@pytest.fixture
def hr(own: Employee, other: Employee) -> User:
    return _user("log_xlsx_hr", "HR", first="Оюун", last="Хүний")


@pytest.fixture
def admin(own: Employee, other: Employee) -> User:
    return _user("log_xlsx_admin", "Admin", first="Болд", last="Админ")


@pytest.fixture
def system_rows(admin: User) -> None:
    _system_row("Нэвтэрсэн", actor=admin, ip="10.0.0.5")
    _system_row("Тайлан татсан", category=Category.EXPORT, action="export_list", ip="192.168.1.1")


def test_hr_downloads_the_employee_file_with_the_screen_rows(hr: User) -> None:
    response = _client(hr).get(EMPLOYEE_URL)
    assert response.status_code == 200
    assert response["Content-Type"] == XLSX
    assert response["Content-Disposition"] == f'attachment; filename="employee-log-{timezone.localdate()}.xlsx"'
    ws = _sheet(response)
    assert [c.value for c in ws[1]] == export.EMPLOYEE_HEADERS
    expected = [entry.message for entry in filtered(hr, parse_filter(QueryDict()))]
    assert _messages(ws, 6) == expected
    assert "Хаяг өөрчлөгдсөн" in _messages(ws, 6)


def test_sensitive_entry_is_absent_for_hr_and_present_for_admin(hr: User, admin: User) -> None:
    assert HIDDEN not in _messages(_sheet(_client(hr).get(EMPLOYEE_URL)), 6)
    assert HIDDEN in _messages(_sheet(_client(admin).get(EMPLOYEE_URL)), 6)


def test_employee_file_follows_the_address_filter(hr: User, own: Employee, other: Employee) -> None:
    ws = _sheet(_client(hr).get(EMPLOYEE_URL, {"employee": other.pk}))
    assert "Ажлын байр шилжсэн" in _messages(ws, 6)
    assert "Хаяг өөрчлөгдсөн" not in _messages(ws, 6)
    assert set(_messages(ws, 3)) == {"Доржийн Ганзориг"}


def test_formula_text_is_stored_as_text(hr: User) -> None:
    ws = _sheet(_client(hr).get(EMPLOYEE_URL))
    cells = [row[5] for row in ws.iter_rows(min_row=2) if row[5].value == FORMULA]
    assert len(cells) == 1
    assert cells[0].data_type == "s"


def test_employee_export_needs_export_switch(hr: User, own: Employee) -> None:
    _take_export_switch("HR")
    assert _client(hr).get(EMPLOYEE_URL).status_code == 403


def test_system_export_needs_export_switch(admin: User, system_rows: None) -> None:
    _take_export_switch("Admin")
    assert _client(admin).get(SYSTEM_URL).status_code == 403


def test_employee_role_gets_403(own: Employee) -> None:
    staff = _user("log_xlsx_staff", "Employee", first="Сараа", last="Батын")
    assert _client(staff).get(EMPLOYEE_URL).status_code == 403


def test_hr_gets_403_on_the_system_export(hr: User, system_rows: None) -> None:
    assert _client(hr).get(SYSTEM_URL).status_code == 403


def test_anonymous_is_sent_to_login(own: Employee) -> None:
    response = Client().get(EMPLOYEE_URL)
    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_each_export_adds_one_export_log_row_without_names(hr: User, own: Employee) -> None:
    before = SystemLogEntry.objects.filter(action="export_log").count()
    _client(hr).get(EMPLOYEE_URL, {"emp": "Батын"})
    assert SystemLogEntry.objects.filter(action="export_log").count() == before + 1
    entry = SystemLogEntry.objects.filter(action="export_log").latest("id")
    assert entry.category == Category.EXPORT
    assert "Батын" not in entry.message
    assert "Ажилтан: сонгосон" in entry.message


def test_system_export_matches_its_filter_and_logs_once(admin: User, system_rows: None) -> None:
    before = SystemLogEntry.objects.filter(action="export_log").count()
    response = _client(admin).get(SYSTEM_URL, {"category": Category.EXPORT})
    assert response.status_code == 200
    ws = _sheet(response)
    assert [c.value for c in ws[1]] == export.SYSTEM_HEADERS
    assert _messages(ws, 6) == ["Тайлан татсан"]
    assert SystemLogEntry.objects.filter(action="export_log").count() == before + 1


def test_button_shows_only_with_export_switch(hr: User, admin: User, own: Employee) -> None:
    assert 'id="log-excel"' in _client(hr).get("/logs/").content.decode()
    _take_export_switch("HR")
    assert 'id="log-excel"' not in _client(hr).get("/logs/").content.decode()
    assert 'id="log-excel"' in _client(admin).get("/logs/system/").content.decode()


def test_button_href_carries_the_current_filter(hr: User, admin: User, own: Employee) -> None:
    body = _client(hr).get("/logs/", {"q": "abc"}).content.decode()
    assert 'href="/logs/export/?q=abc"' in body
    body = _client(admin).get("/logs/system/", {"q": "abc"}).content.decode()
    assert 'href="/logs/system/export/?q=abc"' in body
    assert 'href="/logs/export/"' in _client(hr).get("/logs/").content.decode()  # no filter, no query


def test_default_row_limit_is_100000() -> None:
    assert export.ROW_LIMIT == 100_000


def test_row_limit_cuts_the_file_with_a_last_line(monkeypatch: pytest.MonkeyPatch, hr: User, own: Employee) -> None:
    monkeypatch.setattr(export, "ROW_LIMIT", 3)
    ws = _sheet(_client(hr).get(EMPLOYEE_URL))
    lines = [row[0].value for row in ws.iter_rows(min_row=2)]
    assert len(lines) == 4
    assert str(lines[-1]).startswith("Хязгаарласан")
