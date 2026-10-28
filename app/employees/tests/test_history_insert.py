from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User

from employees.models import ChangeType, Employee, JobRecord, Position, SalaryRecord
from employees.services import history, macs_writes
from employees.services.history import HistoryError

from .conftest import hire_values

pytestmark = pytest.mark.django_db

SPLIT_MESSAGE = "Энэ өдрөөс эхэлсэн хугацаа аль хэдийн байна. Засвар ашиглана уу."


def _hire_from_jan_first(actor: User, job_values: dict[str, Any]) -> Employee:
    """Record A: hired 2026-01-01 in department D1 (Санхүү) with position P1 (Нягтлан)."""
    return history.hire(hire_values(), {}, start=date(2026, 1, 1), job=job_values, salary=None, by=actor)


def _periods(model: type[JobRecord] | type[SalaryRecord], employee: Employee) -> list[tuple[date, date | None]]:
    rows = model.objects.filter(employee=employee).order_by("period")
    return [(r.period.lower, r.period.upper) for r in rows]


def _job_values(employee: Employee) -> list[tuple[date, date | None, int, int]]:
    """Every job record as (start, end, department id, position id), ordered by start."""
    rows = JobRecord.objects.filter(employee=employee).order_by("period")
    return [(r.period.lower, r.period.upper, r.department_id, r.position_id) for r in rows]


def test_insert_carries_field_through_later_records(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire_from_jan_first(actor, job_values)
    lead = Position.objects.create(name="Ахлах нягтлан")
    history.change_job(
        emp,
        effective=date(2026, 6, 1),
        changes={"position": lead},
        change_type="promotion",
        note="",
        by=actor,
    )
    d2 = macs_writes.save_department("Инженер")
    inserted = history.insert_job(
        emp,
        effective=date(2026, 3, 1),
        changes={"department": d2},
        change_type="transfer",
        note="Шилжилт",
        by=actor,
        event=None,
    )
    first, middle, later = JobRecord.objects.filter(employee=emp).order_by("period")
    assert first.period.lower == date(2026, 1, 1) and first.period.upper == date(2026, 3, 1)
    assert first.department == job_values["department"] and first.position == job_values["position"]
    assert inserted.pk == middle.pk
    assert middle.period.lower == date(2026, 3, 1) and middle.period.upper == date(2026, 6, 1)
    assert middle.department == d2 and middle.position == job_values["position"]
    assert middle.change_type == "transfer" and middle.note == "Шилжилт"
    assert later.period.lower == date(2026, 6, 1) and later.period.upper is None
    assert later.department == d2 and later.position == lead
    assert later.change_type == "promotion"


def test_insert_refused_when_later_record_changed_same_field(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire_from_jan_first(actor, job_values)
    history.change_job(
        emp,
        effective=date(2026, 6, 1),
        changes={"department": macs_writes.save_department("Худалдаа")},
        change_type="transfer",
        note="",
        by=actor,
    )
    before = _job_values(emp)
    d2 = macs_writes.save_department("Инженер")
    with pytest.raises(HistoryError) as refused:
        history.insert_job(
            emp,
            effective=date(2026, 3, 1),
            changes={"department": d2},
            change_type="transfer",
            note="",
            by=actor,
            event=None,
        )
    assert "2026-06-01" in str(refused.value)
    assert ChangeType.TRANSFER.label in str(refused.value)
    assert _job_values(emp) == before


def test_insert_refused_when_later_record_already_holds_new_value(actor: User, job_values: dict[str, Any]) -> None:
    """Conservative ruling: a later record that already has the NEW value still counts as a conflict (the check
    is `!= old`), so the waiting change must be cancelled and recorded again."""
    emp = _hire_from_jan_first(actor, job_values)
    d2 = macs_writes.save_department("Инженер")
    history.change_job(
        emp,
        effective=date(2026, 6, 1),
        changes={"department": d2},
        change_type="transfer",
        note="",
        by=actor,
    )
    before = _job_values(emp)
    with pytest.raises(HistoryError) as refused:
        history.insert_job(
            emp,
            effective=date(2026, 3, 1),
            changes={"department": d2},
            change_type="transfer",
            note="",
            by=actor,
            event=None,
        )
    assert "2026-06-01" in str(refused.value)
    assert _job_values(emp) == before


def test_insert_refused_on_any_field_writes_nothing(actor: User, job_values: dict[str, Any]) -> None:
    """Two fields change. Department agrees with the old value everywhere, position differs on the later record:
    the whole insert is refused before any write, so no record may show the new department either."""
    emp = _hire_from_jan_first(actor, job_values)
    lead = Position.objects.create(name="Ахлах нягтлан")
    history.change_job(
        emp,
        effective=date(2026, 6, 1),
        changes={"position": lead},
        change_type="promotion",
        note="",
        by=actor,
    )
    before_periods = _periods(JobRecord, emp)
    before_values = _job_values(emp)
    with pytest.raises(HistoryError) as refused:
        history.insert_job(
            emp,
            effective=date(2026, 3, 1),
            changes={
                "department": macs_writes.save_department("Инженер"),
                "position": Position.objects.create(name="Дарга"),
            },
            change_type="transfer",
            note="",
            by=actor,
            event=None,
        )
    assert "2026-06-01" in str(refused.value)
    assert _periods(JobRecord, emp) == before_periods
    assert _job_values(emp) == before_values


def test_insert_keeps_periods_contiguous_and_non_overlapping(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire_from_jan_first(actor, job_values)
    history.change_job(
        emp,
        effective=date(2026, 6, 1),
        changes={"position": Position.objects.create(name="Ахлах нягтлан")},
        change_type="promotion",
        note="",
        by=actor,
    )
    history.change_job(
        emp,
        effective=date(2026, 9, 1),
        changes={"position": Position.objects.create(name="Дарга")},
        change_type="promotion",
        note="",
        by=actor,
    )
    d2 = macs_writes.save_department("Инженер")
    history.insert_job(
        emp,
        effective=date(2026, 3, 1),
        changes={"department": d2},
        change_type="transfer",
        note="",
        by=actor,
        event=None,
    )
    periods = _periods(JobRecord, emp)
    assert periods == [
        (date(2026, 1, 1), date(2026, 3, 1)),
        (date(2026, 3, 1), date(2026, 6, 1)),
        (date(2026, 6, 1), date(2026, 9, 1)),
        (date(2026, 9, 1), None),
    ]
    for (_, upper), (lower, _) in zip(periods, periods[1:], strict=False):
        assert upper == lower  # contiguous: each period starts where the previous one ends
    departments = [r.department_id for r in JobRecord.objects.filter(employee=emp).order_by("period")]
    assert departments == [job_values["department"].pk, d2.pk, d2.pk, d2.pk]


def test_insert_in_last_open_period_matches_change_job(actor: User, job_values: dict[str, Any]) -> None:
    """With no later records, insert_job gives the same result as change_job: the old period is closed at
    `effective` and the new record is open-ended."""
    via_change = history.hire(
        hire_values("УБ11111111"), {}, start=date(2026, 1, 1), job=job_values, salary=None, by=actor
    )
    via_insert = history.hire(
        hire_values("УБ22222222"), {}, start=date(2026, 1, 1), job=job_values, salary=None, by=actor
    )
    lead = Position.objects.create(name="Ахлах нягтлан")
    history.change_job(
        via_change, effective=date(2026, 3, 1), changes={"position": lead}, change_type="promotion", note="", by=actor
    )
    history.insert_job(
        via_insert,
        effective=date(2026, 3, 1),
        changes={"position": lead},
        change_type="promotion",
        note="",
        by=actor,
        event=None,
    )
    assert _periods(JobRecord, via_insert) == _periods(JobRecord, via_change)
    assert _periods(JobRecord, via_insert) == [(date(2026, 1, 1), date(2026, 3, 1)), (date(2026, 3, 1), None)]
    assert _job_values(via_insert) == _job_values(via_change)


def test_insert_with_no_changes_refused(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire_from_jan_first(actor, job_values)
    before = _job_values(emp)
    with pytest.raises(HistoryError, match="Өөрчлөх талбар алга"):
        history.insert_job(
            emp, effective=date(2026, 3, 1), changes={}, change_type="transfer", note="", by=actor, event=None
        )
    assert _job_values(emp) == before


def test_insert_unknown_field_refused(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire_from_jan_first(actor, job_values)
    before = _job_values(emp)
    with pytest.raises(HistoryError, match="'positon' талбарыг засах боломжгүй"):
        history.insert_job(
            emp,
            effective=date(2026, 3, 1),
            changes={"positon": job_values["position"]},
            change_type="transfer",
            note="",
            by=actor,
            event=None,
        )
    assert _job_values(emp) == before


def test_insert_salary_refused_when_later_salary_exists(hired: Employee, actor: User) -> None:
    history.change_salary(
        hired, effective=date(2026, 6, 1), amount=Decimal("3000000"), change_type="salary_change", note="", by=actor
    )
    before = _periods(SalaryRecord, hired)
    with pytest.raises(HistoryError) as refused:
        history.insert_salary(
            hired,
            effective=date(2026, 3, 1),
            amount=Decimal("2600000"),
            change_type="salary_change",
            note="",
            by=actor,
            event=None,
        )
    assert "2026-06-01" in str(refused.value)
    assert ChangeType.SALARY_CHANGE.label in str(refused.value)
    assert _periods(SalaryRecord, hired) == before


def test_insert_salary_without_later_salary_splits_like_change_salary(hired: Employee, actor: User) -> None:
    record = history.insert_salary(
        hired,
        effective=date(2026, 3, 1),
        amount=Decimal("2600000"),
        change_type="salary_change",
        note="",
        by=actor,
        event=None,
    )
    assert record.period.lower == date(2026, 3, 1) and record.period.upper is None
    assert _periods(SalaryRecord, hired) == [(date(2026, 1, 5), date(2026, 3, 1)), (date(2026, 3, 1), None)]


def test_insert_at_period_start_is_refused_like_split(hired: Employee, actor: User) -> None:
    history.change_job(
        hired,
        effective=date(2026, 3, 1),
        changes={"position": Position.objects.create(name="Ахлах нягтлан")},
        change_type="promotion",
        note="",
        by=actor,
    )
    before = _job_values(hired)
    with pytest.raises(HistoryError) as refused:
        history.insert_job(
            hired,
            effective=date(2026, 3, 1),
            changes={"department": macs_writes.save_department("Бусад")},
            change_type="transfer",
            note="",
            by=actor,
            event=None,
        )
    assert str(refused.value) == SPLIT_MESSAGE
    assert _job_values(hired) == before
