from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, transaction

from employees.history_range import (
    ORDER,
    ORDER_DESC,
    SPAN_FIELDS,
    Span,
    ends_on,
    ensure_free,
    get_span,
    lock_employee,
    on,
    overlapping,
    set_span,
    span_kwargs,
    starts_after,
)
from employees.models import ChangeType, Employee, HistoryLock, JobRecord, SalaryRecord
from employees.services.history import HistoryError

from .conftest import duplicate_start_refused

pytestmark = pytest.mark.django_db


def _only_job_records(employee: Employee) -> None:
    JobRecord.objects.filter(employee=employee).delete()


def _record(employee: Employee, job_values: dict[str, Any], start: date, end: date | None) -> JobRecord:
    return JobRecord.objects.create(employee=employee, **job_values, **span_kwargs(start, end))


def _matching(employee: Employee, q: Any) -> set[int]:
    return set(JobRecord.objects.filter(employee=employee).filter(q).values_list("pk", flat=True))


def test_on_includes_start_excludes_end(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    rec = _record(hired, job_values, date(2026, 1, 5), date(2026, 3, 1))
    assert _matching(hired, on(date(2026, 1, 5))) == {rec.pk}
    assert _matching(hired, on(date(2026, 2, 28))) == {rec.pk}
    assert _matching(hired, on(date(2026, 3, 1))) == set()


def test_on_open_ended_covers_later_days(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    rec = _record(hired, job_values, date(2026, 1, 5), None)
    assert _matching(hired, on(date(2030, 1, 1))) == {rec.pk}


def test_starts_after_is_strict(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    first = _record(hired, job_values, date(2026, 1, 5), date(2026, 3, 1))
    second = _record(hired, job_values, date(2026, 3, 1), None)
    assert _matching(hired, starts_after(date(2026, 3, 1))) == set()
    assert _matching(hired, starts_after(date(2026, 2, 1))) == {second.pk}
    assert _matching(hired, starts_after(date(2025, 12, 1))) == {first.pk, second.pk}


def test_ends_on_matches_exact_end(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    first = _record(hired, job_values, date(2026, 1, 5), date(2026, 3, 1))
    _record(hired, job_values, date(2026, 3, 1), None)
    assert _matching(hired, ends_on(date(2026, 3, 1))) == {first.pk}
    assert _matching(hired, ends_on(date(2026, 2, 28))) == set()


def test_overlapping_adjacent_records_do_not_overlap(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    ends = _record(hired, job_values, date(2026, 1, 5), date(2026, 3, 1))
    starts = _record(hired, job_values, date(2026, 3, 1), None)
    assert _matching(hired, overlapping(date(2026, 3, 1), date(2026, 4, 1))) == {starts.pk}
    assert _matching(hired, overlapping(date(2026, 2, 1), date(2026, 3, 1))) == {ends.pk}


def test_overlapping_open_ended_overlaps_any_later_range(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    rec = _record(hired, job_values, date(2026, 3, 1), None)
    assert _matching(hired, overlapping(date(2030, 1, 1), date(2030, 2, 1))) == {rec.pk}
    assert _matching(hired, overlapping(date(2026, 1, 1), date(2026, 3, 1))) == set()


def test_span_contains_matches_on(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    rec = _record(hired, job_values, date(2026, 1, 5), date(2026, 3, 1))
    span = get_span(rec)
    assert span == Span(date(2026, 1, 5), date(2026, 3, 1))
    for day in (date(2026, 1, 4), date(2026, 1, 5), date(2026, 2, 28), date(2026, 3, 1)):
        assert (day in span) == (_matching(hired, on(day)) == {rec.pk})


def test_set_span_then_get_span_round_trips(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    rec = _record(hired, job_values, date(2026, 1, 5), None)
    set_span(rec, date(2026, 2, 1), date(2026, 5, 1))
    rec.save(update_fields=SPAN_FIELDS)
    rec.refresh_from_db()
    assert get_span(rec) == Span(date(2026, 2, 1), date(2026, 5, 1))


def test_order_is_by_start_with_open_end_last(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    middle = _record(hired, job_values, date(2026, 3, 1), date(2026, 5, 1))
    last = _record(hired, job_values, date(2026, 5, 1), None)
    first = _record(hired, job_values, date(2026, 1, 5), date(2026, 3, 1))
    qs = JobRecord.objects.filter(employee=hired)
    assert [r.pk for r in qs.order_by(*ORDER)] == [first.pk, middle.pk, last.pk]
    assert [r.pk for r in qs.order_by(*ORDER_DESC)] == [last.pk, middle.pk, first.pk]


def test_period_property_matches_fields(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    rec = _record(hired, job_values, date(2026, 1, 5), date(2026, 3, 1))
    fresh = JobRecord.objects.get(pk=rec.pk)
    assert fresh.start_date == date(2026, 1, 5) and fresh.end_date == date(2026, 3, 1)
    assert fresh.period == Span(date(2026, 1, 5), date(2026, 3, 1))
    assert fresh.period.lower == fresh.start_date and fresh.period.upper == fresh.end_date


def test_unique_start_per_employee(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    _record(hired, job_values, date(2026, 1, 5), None)
    with duplicate_start_refused("IHR_JOB_OVERLAP"), transaction.atomic():
        _record(hired, job_values, date(2026, 1, 5), date(2026, 2, 1))


def test_no_range_column_remains() -> None:
    for model in (JobRecord, SalaryRecord):
        names = {f.name for f in model._meta.concrete_fields}
        assert "period" not in names
        assert {"start_date", "end_date"} <= names


@pytest.mark.pg_only(
    "PostgreSQL only: the 0024 and 0025 migrations convert a PostgreSQL range column (period) to start_date and "
    "end_date, and the test runs PostgreSQL SET CONSTRAINTS; Firebird has no range column"
)
def test_period_migration_reverses_and_reapplies_with_data(hired: Employee, job_values: dict[str, Any]) -> None:
    """Rolled back with the test transaction. Runs the 0025 migration backwards and forwards over real rows."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    before = [("employees", "0024_firebird_reserved_columns")]
    after = [("employees", "0025_period_to_start_end")]
    _only_job_records(hired)
    SalaryRecord.objects.filter(employee=hired).delete()
    _record(hired, job_values, date(2026, 1, 5), date(2026, 3, 1))
    _record(hired, job_values, date(2026, 3, 1), None)
    SalaryRecord.objects.create(
        employee=hired,
        **span_kwargs(date(2026, 1, 5), None),
        base_salary=Decimal("2500000"),
        change_type=ChangeType.HIRE,
    )
    employee_id = hired.pk
    job_sql = "select lower(period), upper(period) from employees_jobrecord where employee_id = %s order by 1"
    salary_sql = "select lower(period), upper(period) from employees_salaryrecord where employee_id = %s"

    connection.cursor().execute("SET CONSTRAINTS ALL IMMEDIATE")  # no pending deferred checks before ALTER TABLE
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    executor.loader.build_graph()
    with connection.cursor() as cur:
        cur.execute(job_sql, [employee_id])
        assert cur.fetchall() == [(date(2026, 1, 5), date(2026, 3, 1)), (date(2026, 3, 1), None)]
        cur.execute(salary_sql, [employee_id])
        assert cur.fetchall() == [(date(2026, 1, 5), None)]

    executor = MigrationExecutor(connection)
    executor.migrate(after)
    executor.loader.build_graph()
    with connection.cursor() as cur:
        cur.execute(
            "select start_date, end_date from employees_jobrecord where employee_id = %s order by 1", [employee_id]
        )
        assert cur.fetchall() == [(date(2026, 1, 5), date(2026, 3, 1)), (date(2026, 3, 1), None)]
        cur.execute("select start_date, end_date from employees_salaryrecord where employee_id = %s", [employee_id])
        assert cur.fetchall() == [(date(2026, 1, 5), None)]


def test_ensure_free_refuses_overlap(hired: Employee) -> None:
    # `hired` has one open-ended job period from 2026-01-05.
    with pytest.raises(HistoryError):
        ensure_free(JobRecord, hired.pk, date(2026, 3, 1), date(2026, 4, 1))


def test_ensure_free_allows_adjacent(hired: Employee, job_values: dict[str, Any]) -> None:
    _only_job_records(hired)
    _record(hired, job_values, date(2026, 1, 5), date(2026, 3, 1))
    ensure_free(JobRecord, hired.pk, date(2026, 3, 1), None)  # starts on the day the other ends: adjacent
    ensure_free(JobRecord, hired.pk, date(2025, 12, 1), date(2026, 1, 5))  # ends on the day the other starts


def test_ensure_free_refuses_second_open_ended_record(hired: Employee) -> None:
    with pytest.raises(HistoryError):
        ensure_free(JobRecord, hired.pk, date(2030, 1, 1), None)


def test_ensure_free_ignores_the_record_being_moved(hired: Employee) -> None:
    rec = JobRecord.objects.get(employee=hired)
    ensure_free(JobRecord, hired.pk, date(2026, 1, 5), None, exclude_pk=rec.pk)


def test_ensure_free_refuses_empty_span(hired: Employee) -> None:
    _only_job_records(hired)
    with pytest.raises(HistoryError):
        ensure_free(JobRecord, hired.pk, date(2026, 3, 1), date(2026, 3, 1))


def test_one_day_record_is_allowed(hired: Employee, job_values: dict[str, Any]) -> None:
    day = date(2026, 3, 1)
    _only_job_records(hired)
    _record(hired, job_values, date(2026, 1, 5), day)
    ensure_free(JobRecord, hired.pk, day, day + timedelta(days=1))
    _record(hired, job_values, day, day + timedelta(days=1))
    ensure_free(JobRecord, hired.pk, day + timedelta(days=1), None)


def test_lock_employee_creates_row_once_and_increments() -> None:
    employee_id = 990001  # plain integer: no employee row is needed for the lock
    with transaction.atomic():
        lock_employee(employee_id)
    assert HistoryLock.objects.get(employee_id=employee_id).counter == 1
    with transaction.atomic():
        lock_employee(employee_id)
    assert HistoryLock.objects.filter(employee_id=employee_id).count() == 1
    assert HistoryLock.objects.get(employee_id=employee_id).counter == 2


class _FakeLockManager:
    """Stands in for HistoryLock.objects: the UPDATE matches no row, and the INSERT loses to another writer."""

    def __init__(self) -> None:
        self.updates = 0

    def filter(self, **_: Any) -> "_FakeLockManager":
        return self

    def update(self, **_: Any) -> int:
        self.updates += 1
        return 0

    def create(self, **_: Any) -> None:
        raise IntegrityError("UNIQUE violation on the lock row")


def test_lock_employee_raises_history_error_when_another_writer_created_the_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLockManager()
    monkeypatch.setattr(HistoryLock, "objects", fake)
    with (
        pytest.raises(HistoryError, match="Өөр хэрэглэгч энэ ажилтны түүхийг засаж байна. Дахин оролдоно уу."),
        transaction.atomic(),
    ):
        lock_employee(990002)
    assert fake.updates == 1  # no second UPDATE after the lost INSERT
