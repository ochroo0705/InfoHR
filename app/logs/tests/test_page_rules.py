"""The request-free rules of the two log pages: addresses, the chip, the tabs, the chip tones and the Excel body."""

import io
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import openpyxl
import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.utils import timezone
from employees.models import ActivityEntry, Employee
from employees.services import history, macs_writes
from employees.tests.helpers import next_order_number

from logs import page_rules
from logs.employee_query import EmployeeLogFilter, filtered
from logs.system_query import SystemLogFilter

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105


def _user(name: str, role: str | None, *, first: str = "", last: str = "") -> User:
    user = User.objects.create_user(name, password=PASSWORD, first_name=first, last_name=last)  # noqa: S106
    if role is not None:
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


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
    return history.hire(
        values,
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=actor,
        order_number=next_order_number(),
    )


def _entry(employee: Employee, message: str, **fields: Any) -> ActivityEntry:
    fields.setdefault("kind", "changed")
    return ActivityEntry.objects.create(employee=employee, message=message, **fields)


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("page_rules_actor", password=PASSWORD)  # noqa: S106


@pytest.fixture
def own(actor: User) -> Employee:
    employee = _hire(actor, "Батын", "Сараа", "УБ99120001")
    _entry(employee, "Хаяг өөрчлөгдсөн", changes=[{"field": "Хаяг", "old": "Сүхбаатар", "new": "Баянзүрх"}])
    return employee


@pytest.fixture
def other(actor: User) -> Employee:
    employee = _hire(actor, "Доржийн", "Ганзориг", "УБ99120002")
    _entry(employee, "Ажлын байр шилжсэн")
    return employee


@pytest.fixture
def hr(own: Employee, other: Employee) -> User:
    return _user("page_rules_hr", "HR", first="Оюун", last="Хүний")


def test_employee_address_keeps_cleaned_filters_in_order() -> None:
    f = EmployeeLogFilter(
        q="a",
        emp="b",
        employee=5,
        by="c",
        kinds=["note", "created"],
        area="salary",
        field="Хаяг",
        date_from=date(2026, 1, 2),
        date_to=date(2026, 2, 3),
        system_only=True,
        oldest_first=True,
    )
    expected = urlencode(
        [
            ("q", "a"),
            ("emp", "b"),
            ("employee", "5"),
            ("by", "c"),
            ("kind", "note"),
            ("kind", "created"),
            ("area", "salary"),
            ("field", "Хаяг"),
            ("from", "2026-01-02"),
            ("to", "2026-02-03"),
            ("system", "1"),
            ("oldest", "1"),
        ]
    )
    assert page_rules.employee_address(f) == expected


def test_system_address_drops_empty_values() -> None:
    f = SystemLogFilter(by="x", categories=["access"])
    assert page_rules.system_address(f) == urlencode([("category", "access"), ("by", "x")])
    assert page_rules.system_address(SystemLogFilter()) == ""


def test_visible_chip_drops_a_person_the_user_may_not_see(own: Employee) -> None:
    staff = _user("page_rules_staff", "Employee", first="Сараа", last="Батын")
    f = EmployeeLogFilter(employee=own.pk)
    assert page_rules.visible_chip(staff, f) is None
    assert f.employee is None


def test_visible_chip_returns_a_visible_person_and_keeps_the_filter(hr: User, own: Employee) -> None:
    f = EmployeeLogFilter(employee=own.pk)
    assert page_rules.visible_chip(hr, f) == own
    assert f.employee == own.pk


def test_tabs_for_auditor_has_system_only() -> None:
    auditor = _user("page_rules_auditor", "Auditor")
    tabs = page_rules.tabs_for(auditor, "system")
    assert tabs == page_rules.LogTabs(employee=False, system=True, export=False)


def test_tabs_for_export_needs_both_rights(hr: User) -> None:
    # HR may export the employee log, but holds no audit right, so the system log offers no export.
    assert page_rules.tabs_for(hr, "employee") == page_rules.LogTabs(employee=True, system=False, export=True)
    assert page_rules.tabs_for(hr, "system").export is False


def test_tabs_for_system_export_true_with_audit_and_export_rights() -> None:
    # The Auditor role holds accounts.view_audit but no export right; grant the export right on top.
    auditor = _user("page_rules_auditor_export", "Auditor")
    export_perm = Permission.objects.get(codename="export_lists", content_type__app_label="accounts")
    auditor.user_permissions.add(export_perm)
    auditor = User.objects.get(pk=auditor.pk)  # fresh permission cache
    assert page_rules.tabs_for(auditor, "system") == page_rules.LogTabs(employee=False, system=True, export=True)


def test_tabs_for_system_export_false_with_audit_only() -> None:
    auditor = _user("page_rules_auditor_only", "Auditor")
    assert page_rules.tabs_for(auditor, "system").export is False


@pytest.mark.parametrize(
    ("kind", "tone"),
    [
        ("correction", "bg-amber-50 text-amber-700"),
        ("history", "bg-violet-50 text-violet-700"),
        ("note", "bg-sky-50 text-sky-700"),
        ("created", "bg-emerald-50 text-emerald-700"),
        ("added", "bg-emerald-50 text-emerald-700"),
        ("deleted", "bg-red-50 text-red-700"),
        ("cancelled", "bg-red-50 text-red-700"),
        ("changed", "bg-slate-100 text-slate-600"),
    ],
)
def test_kind_tone_per_kind(kind: str, tone: str) -> None:
    assert page_rules.kind_tone(kind) == f"whitespace-nowrap rounded px-1.5 py-0.5 text-xs {tone}"


def test_employee_workbook_filename_has_today_and_counts_rows(hr: User, own: Employee, other: Employee) -> None:
    f = EmployeeLogFilter()
    response, tally = page_rules.employee_workbook(hr, f)
    today = timezone.localdate().isoformat()
    assert f"employee-log-{today}.xlsx" in response["Content-Disposition"]
    expected = filtered(hr, f).count()
    assert tally.rows == expected
    sheet = openpyxl.load_workbook(filename=io.BytesIO(response.content)).active
    assert sheet.max_row - 1 == expected  # the header row is not a data row
