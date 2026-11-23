"""GET /api/v1/logs/employee/export and GET /api/v1/logs/system/export: the two Excel files as the API serves them.

The rows, the filters and the workbook come from logs.page_rules and logs.export (the code the Django views use);
these tests pin the API's rights (403 "forbidden" without the view right AND accounts.export_lists, 401 without a
login), the filename, the one export-log row each download writes, and that a person the user may not see is dropped
from the file.
"""

import io
from typing import Any

import openpyxl
import pytest
from accounts.audit import Category
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone
from employees.models import Employee

from api.tests.logs_support import (  # noqa: F401
    FORBIDDEN,
    NOT_LOGGED_IN,
    _client,
    _entry,
    _system_entry,
    _user,
    admin,
    auditor,
    hr,
    job_values,
    other,
    own,
    scoped,
    take_export_switch,
)

pytestmark = pytest.mark.django_db

EMPLOYEE_URL = "/api/v1/logs/employee/export"
SYSTEM_URL = "/api/v1/logs/system/export"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_WORD = "Экспорт"  # every test message that the filter should keep carries this word
MESSAGE_COLUMN = 6  # 1-based: «Мессеж» in the employee file and «Дэлгэрэнгүй» in the system file
NAME_COLUMN = 3  # 1-based: «Ажилтан» in the employee file
SYSTEM_IP_COLUMN = 7  # 1-based: «IP» in the system file


def _sheet(response: Any) -> Any:
    """The first sheet of a downloaded file. Untyped on purpose: openpyxl's stubs type `active` as Optional."""
    return openpyxl.load_workbook(io.BytesIO(response.content)).active


def _column(ws: Any, column: int) -> list[str]:
    """The text of one column below the headers, empty cells left out."""
    return [str(row[column - 1].value) for row in ws.iter_rows(min_row=2) if row[column - 1].value is not None]


def _export_log_count() -> int:
    return SystemLogEntry.objects.filter(action="export_log").count()


def _grant_directly(user: User, codename: str) -> User:
    """Give one permission to the user alone (not through a group) and return the user with a fresh cache."""
    perm = Permission.objects.get(codename=codename, content_type__app_label="accounts")
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)


# Employee file


def test_employee_export_requires_login(db: None) -> None:
    response = Client().get(EMPLOYEE_URL)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_employee_export_403_without_export_right_and_without_view_employees(
    hr: User,  # noqa: F811
    own: Employee,  # noqa: F811
    auditor: User,  # noqa: F811
) -> None:
    nobody = _user("logs_export_nobody", None)
    response = _client(nobody).get(EMPLOYEE_URL)
    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert _client(auditor).get(EMPLOYEE_URL).status_code == 403  # no view_employees
    take_export_switch("HR")
    response = _client(hr).get(EMPLOYEE_URL)  # view_employees but no export switch
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_employee_export_needs_view_employees_even_with_export_right_granted_directly(db: None) -> None:
    user = _grant_directly(_user("logs_export_direct", None), "export_lists")
    assert user.has_perm("accounts.export_lists") is True
    assert user.has_perm("macs.view_employees") is False
    response = _client(user).get(EMPLOYEE_URL)
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_employee_export_returns_workbook_with_filtered_rows(hr: User, own: Employee, other: Employee) -> None:  # noqa: F811
    _entry(own, f"{EXPORT_WORD} нэг")
    _entry(other, f"{EXPORT_WORD} хоёр")
    _entry(own, "Бусад бичлэг")

    response = _client(hr).get(EMPLOYEE_URL, {"q": EXPORT_WORD})

    assert response.status_code == 200
    assert response["Content-Type"] == XLSX
    ws = _sheet(response)
    assert [c.value for c in ws[1]] == ["Огноо", "Хэн", "Ажилтан", "Код", "Төрөл", "Мессеж", "Өөрчлөлт"]
    assert sorted(_column(ws, MESSAGE_COLUMN)) == sorted([f"{EXPORT_WORD} нэг", f"{EXPORT_WORD} хоёр"])
    assert set(_column(ws, NAME_COLUMN)) == {"Батын Сараа", "Доржийн Ганзориг"}


def test_employee_export_logs_one_export_without_typed_text(hr: User, own: Employee) -> None:  # noqa: F811
    _entry(own, f"{EXPORT_WORD} нэг")
    before = _export_log_count()

    response = _client(hr).get(EMPLOYEE_URL, {"emp": "Батын", "q": "Сараа"})

    assert response.status_code == 200
    assert _export_log_count() == before + 1
    entry = SystemLogEntry.objects.filter(action="export_log").latest("id")
    assert entry.category == Category.EXPORT
    assert "Ажилтны бүртгэл" in entry.message
    assert "Ажилтан: сонгосон" in entry.message
    assert "Батын" not in entry.message
    assert "Сараа" not in entry.message


def test_employee_export_ignores_hidden_person_filter(scoped: tuple[Employee, Employee, User]) -> None:  # noqa: F811
    inside, outside, limited = scoped
    _entry(inside, f"{EXPORT_WORD} дотно")
    _entry(outside, f"{EXPORT_WORD} гадна")

    control = _client(limited).get(EMPLOYEE_URL, {"q": EXPORT_WORD, "employee": str(inside.pk)})
    assert control.status_code == 200
    assert _column(_sheet(control), NAME_COLUMN) == ["Дотно Оюун"]

    response = _client(limited).get(EMPLOYEE_URL, {"q": EXPORT_WORD, "employee": str(outside.pk)})
    assert response.status_code == 200
    ws = _sheet(response)
    assert _column(ws, NAME_COLUMN) == ["Дотно Оюун"]  # the hidden person's rows are not in the file
    assert all("Гадна" not in text for text in _column(ws, MESSAGE_COLUMN))
    entry = SystemLogEntry.objects.filter(action="export_log").latest("id")
    assert "Гадна" not in entry.message


def test_export_filename_has_today(hr: User, admin: User, own: Employee) -> None:  # noqa: F811
    response = _client(hr).get(EMPLOYEE_URL)
    assert response["Content-Disposition"] == f'attachment; filename="employee-log-{timezone.localdate()}.xlsx"'
    assert response["Cache-Control"] == "no-store"
    system = _client(admin).get(SYSTEM_URL)
    assert system["Content-Disposition"] == f'attachment; filename="system-log-{timezone.localdate()}.xlsx"'
    assert system["Cache-Control"] == "no-store"


# System file


def test_system_export_requires_login(db: None) -> None:
    response = Client().get(SYSTEM_URL)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_system_export_403_without_export_right_and_without_view_audit(hr: User, admin: User, auditor: User) -> None:  # noqa: F811
    nobody = _user("logs_export_sys_nobody", None)
    assert _client(nobody).get(SYSTEM_URL).status_code == 403
    assert _client(hr).get(SYSTEM_URL).json() == FORBIDDEN  # HR has no view_audit
    assert _client(auditor).get(SYSTEM_URL).status_code == 403  # view_audit but no export switch
    take_export_switch("Admin")
    response = _client(admin).get(SYSTEM_URL)  # view_audit but no export switch
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_system_export_needs_view_audit_even_with_export_right_granted_directly(db: None) -> None:
    user = _grant_directly(_user("logs_export_direct_sys", None), "export_lists")
    assert user.has_perm("accounts.export_lists") is True
    assert user.has_perm("accounts.view_audit") is False
    response = _client(user).get(SYSTEM_URL)
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_system_export_returns_workbook_with_filtered_rows(admin: User) -> None:  # noqa: F811
    _system_entry(f"{EXPORT_WORD} нэг", actor=admin, ip="10.0.0.5")
    _system_entry(f"{EXPORT_WORD} хоёр", actor=admin, ip="192.168.1.1")
    _system_entry("Бусад бичлэг", actor=admin)

    response = _client(admin).get(SYSTEM_URL, {"q": EXPORT_WORD})

    assert response.status_code == 200
    assert response["Content-Type"] == XLSX
    ws = _sheet(response)
    assert [c.value for c in ws[1]] == ["Огноо", "Хэн", "Ангилал", "Үйлдэл", "Зорилт", "Дэлгэрэнгүй", "IP"]
    assert sorted(_column(ws, MESSAGE_COLUMN)) == sorted([f"{EXPORT_WORD} нэг", f"{EXPORT_WORD} хоёр"])
    assert sorted(_column(ws, SYSTEM_IP_COLUMN)) == ["10.0.0.5", "192.168.1.1"]


def test_system_export_logs_one_export_without_typed_text(admin: User) -> None:  # noqa: F811
    _system_entry(f"{EXPORT_WORD} нэг", actor=admin)
    before = _export_log_count()

    response = _client(admin).get(SYSTEM_URL, {"q": "нэг", "by": admin.username})

    assert response.status_code == 200
    assert _export_log_count() == before + 1
    entry = SystemLogEntry.objects.filter(action="export_log").latest("id")
    assert entry.category == Category.EXPORT
    assert "Системийн бүртгэл" in entry.message
    assert "Хэн хийсэн: сонгосон" in entry.message
    assert admin.username not in entry.message
    assert "нэг" not in entry.message
