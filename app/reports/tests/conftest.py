import itertools
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from employees.models import Employee, Event, ensure_ext
from employees.services import history, macs_writes
from employees.tests.conftest import actor, hire_values, hired, job_values, named  # noqa: F401 (fixtures)
from employees.tests.helpers import record_signed
from macs.models import FiredReason

from reports.filters import Filters
from reports.registry import REPORTS
from reports.types import Column, Report


def render_all(report: Report, rows: list[Any]) -> None:
    """Build every cell the page builds: each column's value for each row. Query-count tests measure this,
    because the page reads cells, not rows."""
    for row in rows:
        for col in report.columns:
            col.value(row)


def count_queries(report: Report, user: User, f: Filters) -> tuple[int, int]:
    """(R, T): the queries of `rows()` alone, and of `rows()` followed by rendering every cell. Rendering adds
    T - R; a per-row query in a cell makes that grow with the number of rows, so compare it for 1 and 3 people.
    One untimed call first warms the user's permission cache, so the two timed blocks start alike."""
    report.rows(user, f)
    with CaptureQueriesContext(connection) as only_rows:
        report.rows(user, f)
    with CaptureQueriesContext(connection) as rows_and_cells:
        render_all(report, report.rows(user, f))
    return len(only_rows), len(rows_and_cells)


_register_numbers = itertools.count(10_000_000)


def _make_user(role: str, name: str) -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return user


def legacy(by: User, jobs: dict[str, Any], **columns: Any) -> Employee:
    """An employee with a MACS row and no HR job history, as employees/tests/test_legacy_fallback.py makes one.
    Every call gets its own register number unless `columns` names one."""
    register_no = f"УБ{next(_register_numbers)}"
    emp = macs_writes.create_employee(hire_values(register_no), {}, code=macs_writes.next_code(), by=by)
    ensure_ext(emp)
    values = {"department": jobs["department"], "position": jobs["position"], "salary": Decimal("1800000")}
    Employee.objects.filter(pk=emp.pk).update(**{**values, **columns})
    return Employee.objects.get(pk=emp.pk)


def transfer(employee: Employee, to: str, on: date, by: User) -> Event:
    """Move the employee to another department from `on`, recorded as HR records a transfer (test_events.py `rec`)."""
    dept = macs_writes.save_department(to)
    return record_signed(
        employee,
        type="transfer",
        effective=on,
        changes={"department": dept},
        salary=None,
        reason="",
        note="",
        by=by,
    )


@pytest.fixture
def left_employee(actor: User, job_values: dict[str, Any]) -> Employee:  # noqa: F811 (the imported fixtures)
    """Hired in January 2026 and dismissed on 2026-03-01 (a second person, so `hired` stays working)."""
    emp = history.hire(
        hire_values(register_no="УБ99112244"),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("1500000"),
        by=actor,
    )
    record_signed(
        emp,
        type="termination",
        effective=date(2026, 3, 1),
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )
    return emp


@pytest.fixture
def login_as() -> Callable[..., User]:
    """Log a client in as a new user with one role group (Admin, HR, Accountant or Employee)."""

    def _login(client: Client, role: str, name: str = "viewer") -> User:
        user = _make_user(role, name)
        client.force_login(user)
        return user

    return _login


@pytest.fixture
def hr_user() -> User:
    """An HR user who is not logged in (view_personal, no view_salary)."""
    return _make_user("HR", "hr-user")


@pytest.fixture
def accountant_user() -> User:
    """An accountant who is not logged in (view_salary, no view_personal)."""
    return _make_user("Accountant", "accountant-user")


@pytest.fixture
def login_hr(client: Client, login_as: Callable[..., User]) -> User:
    """The client logged in as an HR user (view_reports, view_employees, export_lists)."""
    return login_as(client, "HR", "hr-viewer")


@pytest.fixture
def fake_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """A small report registered under the key «fake» for the duration of one test."""
    people = [
        SimpleNamespace(name="Бат", pay=1000, regno="УБ12345678", dept="Санхүү"),
        SimpleNamespace(name="Дорж", pay=2000, regno="УБ87654321", dept="Борлуулалт"),
        SimpleNamespace(name="Сараа", pay=None, regno=None, dept=None),
    ]
    report = Report(
        key="fake",
        title="Туршилт",
        filters=("state",),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary", numeric=True),
            Column(key="regno", label="Регистр", value=lambda r: r.regno, needs="macs.view_personal"),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
        ),
        default_columns=("name",),
        rows=lambda user, filters: people,
        group_options=("dept",),
    )
    monkeypatch.setitem(REPORTS, "fake", report)
    return report


@pytest.fixture
def mixed_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """A report whose one column mixes numbers, text and a missing value, registered as «mixed»."""
    values = [3, "", None, "abc", 1]
    report = Report(
        key="mixed",
        title="Холимог",
        filters=(),
        columns=(Column(key="v", label="Утга", value=lambda r: r.v),),
        default_columns=("v",),
        rows=lambda user, filters: [SimpleNamespace(v=x) for x in values],
    )
    monkeypatch.setitem(REPORTS, "mixed", report)
    return report


@pytest.fixture
def fake_all_filters_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """A report that declares every filter, registered as «fake-all»."""
    report = Report(
        key="fake-all",
        title="Бүх шүүлтүүр",
        filters=("state", "as_of", "branch", "department", "position", "gender"),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name),),
        default_columns=("name",),
        rows=lambda user, filters: [],
    )
    monkeypatch.setitem(REPORTS, "fake-all", report)
    return report


@pytest.fixture
def fake_period_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """A report with the period and the new movement and order filters, registered as «fake-period»."""
    report = Report(
        key="fake-period",
        title="Хугацаатай",
        filters=("period", "change", "reason", "order_type", "discipline", "employee"),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name),),
        default_columns=("name",),
        rows=lambda user, filters: [],
        group_options=("name",),
    )
    monkeypatch.setitem(REPORTS, "fake-period", report)
    return report
