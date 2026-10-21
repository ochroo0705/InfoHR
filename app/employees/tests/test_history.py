from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.db import IntegrityError
from psycopg.types.range import DateRange

from employees.models import ActivityEntry, Employee, Event, JobRecord, Position, SalaryRecord
from employees.services import history
from employees.services.history import HistoryError

from .conftest import hire_values

pytestmark = pytest.mark.django_db


def test_hire_creates_open_periods_and_log(hired: Employee) -> None:
    job = JobRecord.objects.get(employee=hired)
    assert hired.code == "E0001"
    assert job.period.lower == date(2026, 1, 5) and job.period.upper is None
    assert SalaryRecord.objects.get(employee=hired).base_salary == Decimal("2500000.00")
    kinds = list(ActivityEntry.objects.filter(employee=hired).values_list("kind", "sensitive"))
    assert ("created", False) in kinds and ("history", True) in kinds


def test_hire_without_salary(actor: User, job_values: dict[str, Any]) -> None:
    emp = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    assert not SalaryRecord.objects.filter(employee=emp).exists()


def test_change_job_splits_period(hired: Employee, actor: User) -> None:
    lead = Position.objects.create(name="Ахлах нягтлан")
    history.change_job(
        hired, effective=date(2026, 6, 1), changes={"position": lead}, change_type="correction", note="", by=actor
    )
    first, second = JobRecord.objects.filter(employee=hired).order_by("period")
    assert first.period.upper == date(2026, 6, 1) and first.position.name == "Нягтлан"
    assert second.period.lower == date(2026, 6, 1) and second.period.upper is None
    assert second.position == lead and second.department == first.department


def test_change_job_on_existing_start_date_refused(hired: Employee, actor: User) -> None:
    with pytest.raises(HistoryError):
        history.change_job(
            hired, effective=date(2026, 1, 5), changes={"status": "left"}, change_type="correction", note="", by=actor
        )


def test_change_job_before_hire_refused(hired: Employee, actor: User) -> None:
    with pytest.raises(HistoryError):
        history.change_job(
            hired, effective=date(2025, 12, 1), changes={"status": "left"}, change_type="correction", note="", by=actor
        )


def test_backdated_change_is_marked(hired: Employee, actor: User) -> None:
    history.change_job(
        hired,
        effective=date.today() - timedelta(days=3),
        changes={"status": "long_leave"},
        change_type="correction",
        note="",
        by=actor,
    )
    entry = ActivityEntry.objects.filter(employee=hired, kind="history").first()
    assert entry is not None and "буцаан" in entry.message


def test_job_on_and_salary_on(hired: Employee, actor: User) -> None:
    history.change_salary(
        hired, effective=date(2026, 7, 1), amount=Decimal("3000000"), change_type="correction", note="", by=actor
    )
    assert history.job_on(hired, date(2025, 1, 1)) is None
    before = history.salary_on(hired, date(2026, 6, 30))
    after = history.salary_on(hired, date(2026, 7, 1))
    assert before is not None and before.base_salary == Decimal("2500000.00")
    assert after is not None and after.base_salary == Decimal("3000000.00")


def test_change_salary_creates_first_period(actor: User, job_values: dict[str, Any]) -> None:
    emp = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    record = history.change_salary(
        emp, effective=date(2026, 1, 5), amount=Decimal("1800000"), change_type="hire", note="", by=actor
    )
    assert record.period.upper is None


def test_correct_job_edits_in_place_and_logs(hired: Employee, actor: User) -> None:
    record = JobRecord.objects.get(employee=hired)
    history.correct_job(record, changes={"contract_no": "Г-15"}, reason="буруу бичсэн", by=actor)
    assert JobRecord.objects.filter(employee=hired).count() == 1
    entry = ActivityEntry.objects.filter(employee=hired, kind="correction").get()
    assert entry.changes == [{"field": "Гэрээний дугаар", "old": "", "new": "Г-15"}]
    assert "буруу бичсэн" in entry.message


def test_correction_requires_reason(hired: Employee, actor: User) -> None:
    with pytest.raises(HistoryError):
        history.correct_salary(SalaryRecord.objects.get(employee=hired), amount=Decimal("1"), reason=" ", by=actor)


def test_salary_correction_log_is_sensitive(hired: Employee, actor: User) -> None:
    history.correct_salary(SalaryRecord.objects.get(employee=hired), amount=Decimal("2600000"), reason="typo", by=actor)
    assert ActivityEntry.objects.get(employee=hired, kind="correction").sensitive is True


def test_failure_rolls_back_everything(actor: User, job_values: dict[str, Any]) -> None:
    job_values["position"] = Position(name="unsaved")  # not saved -> insert fails
    with pytest.raises((ValueError, IntegrityError)):
        history.hire(hire_values(), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    assert not Employee.objects.exists() and not ActivityEntry.objects.exists()


def test_future_hire_has_no_current_job(actor: User, job_values: dict[str, Any]) -> None:
    emp = history.hire(
        hire_values(), {}, start=date.today() + timedelta(days=10), job=job_values, salary=None, by=actor
    )
    assert history.job_on(emp, date.today()) is None
    emp.refresh_from_db()
    assert emp.department_id == job_values["department"].pk  # coming job is copied (latest-period fallback)
    assert emp.emptype == 1 and emp.status == "active"


@pytest.mark.parametrize("bad", ["period", "positon", "employee", "id"])
def test_change_job_rejects_unknown_fields(hired: Employee, actor: User, bad: str) -> None:
    before = ActivityEntry.objects.count()
    with pytest.raises(HistoryError):
        history.change_job(
            hired, effective=date(2026, 6, 1), changes={bad: "x"}, change_type="correction", note="", by=actor
        )
    assert JobRecord.objects.filter(employee=hired).count() == 1
    assert JobRecord.objects.get(employee=hired).period.upper is None
    assert ActivityEntry.objects.count() == before


def test_change_salary_first_only_refuses_existing(hired: Employee, actor: User) -> None:
    with pytest.raises(HistoryError):
        history.change_salary(
            hired,
            effective=date(2026, 6, 1),
            amount=Decimal("3000000"),
            change_type="hire",
            note="",
            by=actor,
            first_only=True,
        )
    assert hired.salary_records.count() == 1


def test_change_job_splits_only_the_period_it_falls_in(hired: Employee, actor: User) -> None:
    lead = Position.objects.create(name="Ахлах нягтлан")
    history.change_job(
        hired, effective=date(2026, 3, 1), changes={"position": lead}, change_type="correction", note="", by=actor
    )
    history.change_job(
        hired, effective=date(2026, 2, 1), changes={"status": "long_leave"}, change_type="correction", note="", by=actor
    )
    first, second, third = JobRecord.objects.filter(employee=hired).order_by("period")
    assert first.period.lower == date(2026, 1, 5) and first.period.upper == date(2026, 2, 1)
    assert second.period.lower == date(2026, 2, 1) and second.period.upper == date(2026, 3, 1)
    assert third.period.lower == date(2026, 3, 1) and third.period.upper is None
    assert third.position == lead and third.status == "active"


def test_change_job_on_period_start_already_split_refused(hired: Employee, actor: User) -> None:
    lead = Position.objects.create(name="Ахлах нягтлан")
    history.change_job(
        hired, effective=date(2026, 3, 1), changes={"position": lead}, change_type="correction", note="", by=actor
    )
    with pytest.raises(HistoryError):
        history.change_job(
            hired, effective=date(2026, 3, 1), changes={"status": "left"}, change_type="correction", note="", by=actor
        )
    assert JobRecord.objects.filter(employee=hired).count() == 2


def test_change_salary_before_first_salary_refused(hired: Employee, actor: User) -> None:
    with pytest.raises(HistoryError, match="Энэ өдрөөс хойш цалингийн түүх байна"):
        history.change_salary(
            hired, effective=date(2025, 12, 1), amount=Decimal("1000000"), change_type="correction", note="", by=actor
        )
    assert hired.salary_records.count() == 1


def _event(employee: Employee, effective: date) -> Event:
    return Event.objects.create(employee=employee, type="promotion", effective=effective)


def test_change_job_links_event_and_log_false_skips_entry(hired: Employee, actor: User) -> None:
    lead = Position.objects.create(name="Ахлах нягтлан")
    event = _event(hired, date(2026, 6, 1))
    before = ActivityEntry.objects.filter(employee=hired).count()
    record = history.change_job(
        hired,
        effective=date(2026, 6, 1),
        changes={"position": lead},
        change_type="promotion",
        note="",
        by=actor,
        event=event,
        log=False,
    )
    assert record.event == event and list(event.job_records.all()) == [record]
    assert ActivityEntry.objects.filter(employee=hired).count() == before


def test_change_salary_log_false_skips_entry(hired: Employee, actor: User) -> None:
    event = _event(hired, date(2026, 6, 1))
    before = ActivityEntry.objects.filter(employee=hired).count()
    record = history.change_salary(
        hired,
        effective=date(2026, 6, 1),
        amount=Decimal("3000000"),
        change_type="salary_change",
        note="",
        by=actor,
        event=event,
        log=False,
    )
    assert record.event == event
    assert ActivityEntry.objects.filter(employee=hired).count() == before


def test_undo_merges_job_and_salary_back(hired: Employee, actor: User) -> None:
    lead = Position.objects.create(name="Ахлах нягтлан")
    event = _event(hired, date(2026, 6, 1))
    job = history.change_job(
        hired,
        effective=date(2026, 6, 1),
        changes={"position": lead},
        change_type="promotion",
        note="",
        by=actor,
        event=event,
    )
    salary = history.change_salary(
        hired,
        effective=date(2026, 6, 1),
        amount=Decimal("3000000"),
        change_type="promotion",
        note="",
        by=actor,
        event=event,
    )
    history.undo([job, salary])
    (only_job,) = JobRecord.objects.filter(employee=hired)
    (only_salary,) = SalaryRecord.objects.filter(employee=hired)
    assert only_job.period.lower == date(2026, 1, 5) and only_job.period.upper is None
    assert only_salary.period.upper is None and only_salary.base_salary == Decimal("2500000.00")


def test_undo_first_salary_period_deletes_it(actor: User, job_values: dict[str, Any]) -> None:
    emp = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    event = _event(emp, date(2026, 3, 1))
    record = history.change_salary(
        emp,
        effective=date(2026, 3, 1),
        amount=Decimal("1000000"),
        change_type="salary_change",
        note="",
        by=actor,
        event=event,
    )
    history.undo([record])
    assert not SalaryRecord.objects.filter(employee=emp).exists()


def test_undo_refused_when_later_history_has_gap(hired: Employee, actor: User) -> None:
    first = history.change_salary(
        hired, effective=date(2026, 3, 1), amount=Decimal("2600000"), change_type="salary_change", note="", by=actor
    )
    history.change_salary(
        hired, effective=date(2026, 6, 1), amount=Decimal("2700000"), change_type="salary_change", note="", by=actor
    )
    SalaryRecord.objects.filter(pk=first.pk).update(period=DateRange(date(2026, 3, 1), date(2026, 5, 1), "[)"))
    with pytest.raises(HistoryError):
        history.undo([first])


def test_undo_non_last_record_refused(hired: Employee, actor: User) -> None:
    first = history.change_salary(
        hired, effective=date(2026, 3, 1), amount=Decimal("2600000"), change_type="salary_change", note="", by=actor
    )
    history.change_salary(
        hired, effective=date(2026, 6, 1), amount=Decimal("2700000"), change_type="salary_change", note="", by=actor
    )
    with pytest.raises(HistoryError):
        history.undo([first])
    assert SalaryRecord.objects.filter(employee=hired).count() == 3
