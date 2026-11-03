import itertools
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from macs.models import FiredReason

from employees import company_stats, today
from employees.listing import Row, employee_rows
from employees.models import Employee, EmployeeExt
from employees.services import history, macs_writes

from .conftest import hire_values, named
from .helpers import record_signed
from .test_movements import legacy

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)
_numbers = itertools.count(20_000_000)
_users = itertools.count(1)


def _user(role: str = "HR", name: str | None = None) -> User:
    name = name or f"cs_user{next(_users)}"
    u = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=u.pk)


def _rows() -> list[Row]:
    return employee_rows(Employee.objects.all(), TODAY)


def _hire(actor: User, jobs: dict[str, Any], on: date, **job: Any) -> Employee:
    values = {**hire_values(f"УБ{next(_numbers)}"), "first_hire_date": on}
    return history.hire(values, {}, start=on, job={**jobs, **job}, salary=Decimal("1500000"), by=actor)


def _terminate(emp: Employee, on: date, actor: User) -> None:
    record_signed(
        emp,
        type="termination",
        effective=on,
        changes={},
        salary=None,
        reason="",
        note="",
        by=actor,
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
    )


def _stats(user: User | None = None) -> company_stats.Company:
    result = company_stats.company(user or _user(), _rows(), TODAY)
    assert result is not None
    return result


def _values(points: list[company_stats.Point]) -> dict[str, float | None]:
    return {p.label: p.value for p in points}


def test_returns_none_without_view_employees(hired: Employee) -> None:
    assert company_stats.company(_user("Employee", "plain"), _rows(), TODAY) is None


def test_last_headcount_point_equals_the_tile(hired: Employee) -> None:
    stats = _stats()
    assert len(stats.headcount) == 12 and len(stats.turnover) == 12
    assert stats.headcount[-1].label == "2026-10"
    assert stats.headcount[0].label == "2025-11"
    assert stats.headcount[-1].value == 1 == today.headcount(_rows())


def test_headcount_walks_back_over_a_hire_and_a_termination(actor: User, job_values: dict[str, Any]) -> None:
    _hire(actor, job_values, date(2026, 9, 4))  # 40 days ago
    leaver = _hire(actor, job_values, date(2025, 9, 9))
    _terminate(leaver, date(2026, 9, 24), actor)  # 20 days ago
    _hire(actor, job_values, date(2025, 12, 10))
    _hire(actor, job_values, date(2026, 10, 10))
    got = _values(_stats().headcount)
    assert got["2025-11"] == 1  # only the first leaver
    assert got["2025-12"] == 2
    assert got["2026-08"] == 2  # leaver and December hire
    assert got["2026-09"] == 2  # September hire in, leaver out
    assert got["2026-10"] == 3 == today.headcount(_rows())


def test_person_without_hr_row_does_not_shift_the_trend(actor: User, job_values: dict[str, Any]) -> None:
    # The Today page counts only people with an HR row; the walk back must use the same people, so a hire of
    # someone outside those rows (visible, but never touched in HR) leaves the trend as it is.
    _hire(actor, job_values, date(2025, 9, 9))
    user = _user()
    rows = employee_rows(Employee.objects.filter(ext__isnull=False), TODAY)
    before = company_stats.company(user, rows, TODAY)
    outsider = _hire(actor, job_values, date(2026, 9, 4))
    EmployeeExt.objects.filter(employee=outsider).delete()  # hire() writes the HR row; drop it: no HR row
    assert Employee.objects.filter(ext__isnull=True).exists()
    after = company_stats.company(user, rows, TODAY)
    assert before is not None and after is not None
    assert _values(after.headcount) == _values(before.headcount)


def test_turnover_is_leavers_over_average_headcount(actor: User, job_values: dict[str, Any]) -> None:
    _hire(actor, job_values, date(2026, 9, 4))
    leaver = _hire(actor, job_values, date(2025, 9, 9))
    _terminate(leaver, date(2026, 9, 24), actor)
    _hire(actor, job_values, date(2025, 12, 10))
    _hire(actor, job_values, date(2026, 10, 10))
    got = _values(_stats().turnover)
    assert got["2026-09"] == 50.0  # 1 leaver, headcount 2 at both ends of the month
    assert got["2026-10"] == 0.0
    assert got["2025-11"] == 0.0


def test_turnover_has_one_decimal(actor: User, job_values: dict[str, Any]) -> None:
    for n in range(3):
        _hire(actor, job_values, date(2026, 1, 5 + n))
    leaver = _hire(actor, job_values, date(2026, 1, 8))
    _terminate(leaver, date(2026, 10, 5), actor)  # 4 at the start of October, 3 now: average 3.5
    assert _values(_stats().turnover)["2026-10"] == 28.6


def test_turnover_is_none_when_no_headcount() -> None:
    stats = _stats()
    assert [p.value for p in stats.turnover] == [None] * 12


def test_same_month_hire_and_leave_counts_once(hired: Employee, actor: User, job_values: dict[str, Any]) -> None:
    short = _hire(actor, job_values, date(2026, 10, 2))
    _terminate(short, date(2026, 10, 8), actor)
    stats = _stats()
    assert (stats.hires_month, stats.leavers_month) == (1, 1)
    got = _values(stats.headcount)
    assert got["2026-10"] == 1 and got["2026-09"] == 1
    assert _values(stats.turnover)["2026-10"] == 100.0  # 1 leaver over an average headcount of 1
    assert all(v is None or v >= 0 for v in got.values())


def test_departments_top_eight_then_other(actor: User, job_values: dict[str, Any]) -> None:
    for n in range(9):
        _hire(actor, job_values, date(2026, 1, 5), department=macs_writes.save_department(f"Хэлтэс {n}"))
    _hire(actor, job_values, date(2026, 1, 5), department=macs_writes.save_department("Хэлтэс 0"))
    bars = _stats().departments
    assert len(bars) == 9
    assert bars[0].label == "Хэлтэс 0" and bars[0].value == 2 and bars[0].pct == 100
    assert bars[-1].label == "Бусад" and bars[-1].value == 1 and bars[-1].pct == 50
    assert sum(b.value for b in bars) == 10


def test_person_without_department_is_unknown(actor: User, job_values: dict[str, Any]) -> None:
    legacy(actor, job_values, department=None)
    bars = _stats().departments
    assert [(b.label, b.value, b.pct) for b in bars] == [("Тодорхойгүй", 1, 100)]


def _months_ago(months: int) -> date:
    index = TODAY.year * 12 + TODAY.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def test_tenure_bands_use_first_hire_date(actor: User, job_values: dict[str, Any]) -> None:
    for months in (3, 9, 18, 40, 90):
        _hire(actor, job_values, _months_ago(months))
    bars = _stats().tenure
    assert [b.label for b in bars] == ["0–6 сар", "6–12 сар", "1–2 жил", "2–5 жил", "5+ жил"]
    assert [b.value for b in bars] == [1, 1, 1, 1, 1]
    assert all(b.pct == 100 for b in bars)


def test_partial_scope_flag(hired: Employee) -> None:
    assert _stats().partial_scope is False
    limited = _user("HR", "limited")
    AccessScope.objects.update_or_create(user=limited, defaults={"limited": True})
    assert _stats(limited).partial_scope is True


def test_partial_history_flag(hired: Employee, actor: User, job_values: dict[str, Any]) -> None:
    assert _stats().partial_history is False
    legacy(actor, job_values, first_hire_date=date(2025, 4, 1))
    assert _stats().partial_history is True


def test_empty_company_gives_zeros_not_errors() -> None:
    stats = _stats()
    assert [p.value for p in stats.headcount] == [0] * 12
    assert stats.departments == []
    assert [b.value for b in stats.tenure] == [0] * 5 and [b.pct for b in stats.tenure] == [0] * 5
    assert (stats.hires_month, stats.leavers_month) == (0, 0)
    assert stats.partial_history is False
