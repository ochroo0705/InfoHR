from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.query import QuerySet
from django.db.models.signals import post_delete, post_save

from employees import history_range
from employees.models import Employee, HrOrder, JobRecord, SalaryRecord
from employees.services import events, history, macs_writes, orders
from employees.services import setup as setup_service
from employees.services.history import HistoryError

from .conftest import hire_values

pytestmark = pytest.mark.django_db


def _job_periods(employee: Employee) -> list[tuple[date, date | None]]:
    return [
        (r.start_date, r.end_date) for r in JobRecord.objects.filter(employee=employee).order_by(*history_range.ORDER)
    ]


def _salary_periods(employee: Employee) -> list[tuple[date, date | None]]:
    return [
        (r.start_date, r.end_date)
        for r in SalaryRecord.objects.filter(employee=employee).order_by(*history_range.ORDER)
    ]


def _overlapping_later_job(employee: Employee, job_values: dict[str, Any]) -> None:
    """A bad row that overlaps the open period from 2026-03-01 (written directly: the guard must still refuse)."""
    JobRecord.objects.create(
        employee=employee,
        **history_range.span_kwargs(date(2026, 3, 1), date(2026, 3, 15)),
        change_type="correction",
        **job_values,
    )


def _overlapping_later_salary(employee: Employee) -> None:
    SalaryRecord.objects.create(
        employee=employee,
        **history_range.span_kwargs(date(2026, 3, 1), date(2026, 3, 15)),
        base_salary=Decimal("1"),
        change_type="correction",
    )


def test_history_writers_call_the_guard(hired: Employee, actor: User, job_values: dict[str, Any]) -> None:
    _overlapping_later_job(hired, job_values)
    _overlapping_later_salary(hired)
    jobs_before = _job_periods(hired)
    salaries_before = _salary_periods(hired)

    # A split at 2026-02-01 would make the new period [2026-02-01, open) overlap the bad row.
    with pytest.raises(HistoryError):
        history.change_job(
            hired,
            effective=date(2026, 2, 1),
            changes={"status": "long_leave"},
            change_type="correction",
            note="",
            by=actor,
        )
    with pytest.raises(HistoryError):
        history.insert_job(
            hired,
            effective=date(2026, 2, 1),
            changes={"status": "long_leave"},
            change_type="correction",
            note="",
            by=actor,
            event=None,
        )
    with pytest.raises(HistoryError):
        history.change_salary(
            hired, effective=date(2026, 2, 1), amount=Decimal("3000000"), change_type="correction", note="", by=actor
        )

    assert _job_periods(hired) == jobs_before
    assert _salary_periods(hired) == salaries_before


def test_events_take_the_history_lock_before_the_employee_row(
    monkeypatch: pytest.MonkeyPatch, hired: Employee, actor: User
) -> None:
    """One global lock order: the history lock first, then the Employee row (else two writers can deadlock)."""
    calls: list[str] = []
    original_lock = history_range.lock_employee
    original_select = QuerySet.select_for_update

    def spy_lock(employee_id: int) -> None:
        calls.append("history_lock")
        original_lock(employee_id)

    def spy_select(self: QuerySet, *args: Any, **kwargs: Any) -> QuerySet:
        if self.model is Employee:
            calls.append("employee_row")
        return original_select(self, *args, **kwargs)

    dept_a = macs_writes.save_department("Тест А")
    dept_b = macs_writes.save_department("Тест Б")
    dept_c = macs_writes.save_department("Тест В")
    monkeypatch.setattr(history_range, "lock_employee", spy_lock)
    monkeypatch.setattr(QuerySet, "select_for_update", spy_select)

    def assert_lock_first(entry: str) -> None:
        assert "history_lock" in calls and "employee_row" in calls, f"{entry}: {calls}"
        assert calls.index("history_lock") < calls.index("employee_row"), f"{entry}: {calls}"
        calls.clear()

    # events.record (a waiting transfer writes no history, but still takes the employee lock)
    applied = events.record(
        hired,
        type="transfer",
        effective=date(2026, 3, 1),
        changes={"department": dept_a},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    assert_lock_first("events.record")

    # events.apply_waiting
    events.apply_waiting(applied, by=actor)
    assert_lock_first("events.apply_waiting")

    # events.cancel
    cancelled = events.record(
        hired,
        type="transfer",
        effective=date(2026, 3, 15),
        changes={"department": dept_b},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    calls.clear()
    events.cancel(cancelled, reason="Буруу бүртгэсэн", by=actor)
    assert_lock_first("events.cancel")

    # orders.attach_signed_file (applies the waiting change it carries)
    waiting = events.record(
        hired,
        type="transfer",
        effective=date(2026, 5, 1),
        changes={"department": dept_c},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    order = orders.register(
        HrOrder.objects.get(event=waiting),
        number="А/1",
        date=date(2026, 5, 1),
        summary="",
        issued_by="",
        by=actor,
    )
    calls.clear()
    orders.attach_signed_file(
        order, SimpleUploadedFile("order.pdf", b"%PDF-1.4 test", content_type="application/pdf"), by=actor
    )
    assert_lock_first("orders.attach_signed_file")

    # setup.toggle
    calls.clear()
    setup_service.toggle(hired, "contract", actor)
    assert_lock_first("setup.toggle")


def test_every_history_writer_takes_the_lock(
    monkeypatch: pytest.MonkeyPatch, actor: User, job_values: dict[str, Any]
) -> None:
    events: list[str] = []
    original_lock = history_range.lock_employee

    def spy_lock(employee_id: int) -> None:
        events.append("lock")
        original_lock(employee_id)

    def row_written(sender: type, **_: object) -> None:
        events.append("row")

    monkeypatch.setattr(history_range, "lock_employee", spy_lock)
    post_save.connect(row_written, sender=JobRecord, weak=False)
    post_save.connect(row_written, sender=SalaryRecord, weak=False)
    post_delete.connect(row_written, sender=JobRecord, weak=False)
    post_delete.connect(row_written, sender=SalaryRecord, weak=False)
    try:
        # hire: the Employee row itself is created before the lock (it has no history yet); the history rows
        # must come after the lock.
        employee = history.hire(
            hire_values(), {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor
        )
        assert events.count("lock") >= 1
        assert events.index("lock") < events.index("row")

        events.clear()
        record = history.change_job(
            employee,
            effective=date(2026, 6, 1),
            changes={"status": "long_leave"},
            change_type="correction",
            note="",
            by=actor,
        )
        assert events and events[0] == "lock" and "row" in events
        assert events.index("lock") < events.index("row")

        events.clear()
        history.change_salary(
            employee, effective=date(2026, 7, 1), amount=Decimal("3000000"), change_type="correction", note="", by=actor
        )
        assert events and events[0] == "lock" and "row" in events

        events.clear()
        history.undo([record])
        assert events and events[0] == "lock" and "row" in events
    finally:
        post_save.disconnect(row_written, sender=JobRecord)
        post_save.disconnect(row_written, sender=SalaryRecord)
        post_delete.disconnect(row_written, sender=JobRecord)
        post_delete.disconnect(row_written, sender=SalaryRecord)
