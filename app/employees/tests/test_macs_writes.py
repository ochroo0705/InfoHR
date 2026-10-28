from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User
from django.utils import timezone
from macs.models import EmployeeHistory, Movement
from psycopg.types.range import DateRange

from employees.models import (
    ChangeType,
    ContractType,
    Department,
    Employee,
    EmployeeExt,
    EmployeeType,
    JobRecord,
    JobStatus,
    Position,
    SalaryRecord,
)
from employees.services import macs_writes


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("w_actor", password="x-long-pass-123")  # noqa: S106


def _create(actor: User, **extra: object):  # type: ignore[no-untyped-def]
    values = {
        "given_name": "Сараа",
        "family_name": "Батын",
        "register_no": "УБ99112233",
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
        **extra,
    }
    return macs_writes.create_employee(values, {}, code=macs_writes.next_code(), by=actor)


@pytest.mark.django_db
def test_create_applies_the_old_trigger_rules(actor: User) -> None:
    e = _create(actor)
    e.refresh_from_db()
    assert e.pk > 0  # from gen_employeeid
    assert e.fullname == "Батын".ljust(25) + ", Сараа"
    assert e.birth_year == 1999
    assert e.hr_flag == "yes"
    assert e.sector_years == 0
    assert e.loginpass == str(e.pk)
    assert e.code == "E0001"
    assert EmployeeExt.objects.filter(employee=e).exists()


@pytest.mark.django_db
def test_hire_date_and_contract_start_fill_each_other(actor: User) -> None:
    e = _create(actor)
    assert e.contract_start == date(2026, 1, 5)
    e2 = _create(actor, register_no="УБ99112234", first_hire_date=None, contract_start=date(2026, 2, 1))
    assert e2.first_hire_date == date(2026, 2, 1)


@pytest.mark.parametrize(
    ("status", "stored", "pension", "expected", "flags"),
    [
        ("active", 1, False, 1, ("active", "no", None)),
        ("active", 5, False, 5, ("active", "yes", None)),
        ("active", 9, False, 9, ("active", "no", 2)),
        ("long_leave", 1, False, 1, ("active", "no", None)),
        ("left", 1, False, 3, ("inactive", "no", None)),
        ("left", 1, True, 6, ("elder", "no", None)),
    ],
)
def test_emptype_mapping(
    status: str, stored: int, pension: bool, expected: int, flags: tuple[str, str, int | None]
) -> None:
    class Ev:  # minimal Event stand-in
        pass

    ev = Ev()
    ev.pension = pension  # type: ignore[attr-defined]

    class J:  # minimal JobRecord stand-in: the type is stored, never derived from dates
        pass

    job = J()
    job.status, job.emptype, job.event_id, job.event = status, stored, 1, ev  # type: ignore[attr-defined]
    ext = EmployeeExt(probation_end=date(2020, 1, 1))  # a past probation end changes nothing
    assert macs_writes.emptype_for(job, ext, date(2026, 6, 1)) == expected  # type: ignore[arg-type]
    assert macs_writes.EMPTYPE_FLAGS[expected] == flags
    emp = Employee()
    macs_writes._set_emptype(emp, expected)
    assert (emp.emptype, emp.status, emp.contract_flag, emp.wagetest) == (expected, *flags)


@pytest.mark.django_db
def test_next_code_compares_numbers(actor: User) -> None:
    assert macs_writes.next_code() == "E0001"
    for code in ("E9999", "E0010"):
        macs_writes.create_employee(
            {"given_name": "Тест", "family_name": "Тест", "register_no": f"УБ{code[1:]}1111"},
            {},
            code=code,
            by=actor,
        )
    assert macs_writes.next_code() == "E10000"


def _dept_pos() -> tuple[Department, Position]:
    return macs_writes.save_department("Санхүү"), macs_writes.save_position("Нягтлан")


def _job(employee: Employee, dep: Department, pos: Position, start: date, end: date | None, status: str) -> None:
    JobRecord.objects.create(
        employee=employee,
        period=DateRange(start, end, "[)"),
        position=pos,
        department=dep,
        employee_type=EmployeeType.FULL_TIME,
        status=status,
        contract_type=ContractType.OPEN_ENDED,
        contract_no="C-1",
        contract_start=start,
        contract_end=end,
        change_type=ChangeType.HIRE,
    )


@pytest.mark.django_db
def test_sync_current_copies_the_job_and_salary_valid_today(actor: User) -> None:
    e = _create(actor)
    dep, pos = _dept_pos()
    today = date(2026, 6, 1)
    _job(e, dep, pos, date(2026, 1, 5), None, JobStatus.ACTIVE)
    SalaryRecord.objects.create(
        employee=e,
        period=DateRange(date(2026, 1, 5), None, "[)"),
        base_salary=Decimal("1500000"),
        change_type=ChangeType.HIRE,
    )
    macs_writes.sync_current(e, today)
    e.refresh_from_db()
    assert e.department_id == dep.pk and e.position_id == pos.pk
    assert e.salary == Decimal("1500000")
    assert (e.emptype, e.status, e.contract_flag) == (1, "active", "no")
    assert e.changed_date == today


@pytest.mark.django_db
def test_sync_current_future_only_hire_is_not_inactive(actor: User) -> None:
    e = _create(actor)
    dep, pos = _dept_pos()
    _job(e, dep, pos, date(2026, 9, 1), None, JobStatus.ACTIVE)
    macs_writes.sync_current(e, date(2026, 6, 1))
    e.refresh_from_db()
    assert e.department_id == dep.pk
    assert e.salary == 0
    assert (e.emptype, e.status) == (1, "active")


@pytest.mark.django_db
def test_sync_current_leaver_is_inactive(actor: User) -> None:
    e = _create(actor)
    dep, pos = _dept_pos()
    _job(e, dep, pos, date(2025, 1, 1), date(2026, 3, 31), JobStatus.LEFT)
    macs_writes.sync_current(e, date(2026, 6, 1))
    e.refresh_from_db()
    assert (e.emptype, e.status, e.contract_flag) == (3, "inactive", "no")


@pytest.mark.django_db
def test_movement_and_history_snapshot(actor: User) -> None:
    e = _create(actor)
    macs_writes.record_movement(e, "in", date(2026, 1, 5))
    macs_writes.snapshot_history(e)
    assert Movement.objects.filter(employee=e, kind="in").count() == 1
    snap = EmployeeHistory.objects.get(employee_id_value=e.pk)
    assert snap.fullname == "Батын".ljust(25) + ", Сараа" and snap.id > 0


@pytest.mark.django_db
def test_departments_and_positions_get_ext_rows() -> None:
    d = macs_writes.save_department("Санхүү")
    p = macs_writes.save_position("Нягтлан")
    assert Department.objects.get(pk=d.pk).ext.active
    assert Position.objects.get(pk=p.pk).ext.active
    assert macs_writes.save_department("Санхүү 2", department=d).name == "Санхүү 2"


def _event(e: Employee, type_: str, day: date, **extra: object) -> None:
    from employees.models import Event

    # An in-force change: an unapplied (waiting) event is ignored by the MACS flags.
    Event.objects.create(employee=e, type=type_, effective=day, applied_at=timezone.now(), **extra)


def _reason(name: str = "Өөрийн хүсэлтээр"):  # type: ignore[no-untyped-def]
    from macs.models import FiredReason

    return FiredReason.objects.create(name=name)


@pytest.mark.django_db
def test_long_leave_sets_flags_on_the_day(actor: User) -> None:
    e = _create(actor)
    dep, pos = _dept_pos()
    _job(e, dep, pos, date(2026, 1, 5), date(2026, 7, 1), JobStatus.ACTIVE)
    _job(e, dep, pos, date(2026, 7, 1), None, JobStatus.LONG_LEAVE)
    _event(e, "leave_start", date(2026, 7, 1), reason="childcare")
    macs_writes.sync_current(e, date(2026, 6, 1))
    e.refresh_from_db()
    assert (e.taken_leave, e.leave_type) == (0, None)
    macs_writes.sync_current(e, date(2026, 7, 1))
    e.refresh_from_db()
    assert (e.taken_leave, e.leave_type) == (1, 2)


@pytest.mark.django_db
def test_return_clears_flags(actor: User) -> None:
    e = _create(actor)
    dep, pos = _dept_pos()
    _job(e, dep, pos, date(2026, 1, 5), date(2026, 7, 1), JobStatus.ACTIVE)
    _job(e, dep, pos, date(2026, 7, 1), date(2026, 8, 1), JobStatus.LONG_LEAVE)
    _job(e, dep, pos, date(2026, 8, 1), None, JobStatus.ACTIVE)
    _event(e, "leave_start", date(2026, 7, 1), reason="maternity")
    macs_writes.sync_current(e, date(2026, 7, 15))
    e.refresh_from_db()
    assert (e.taken_leave, e.leave_type) == (1, 3)
    macs_writes.sync_current(e, date(2026, 8, 1))
    e.refresh_from_db()
    assert (e.taken_leave, e.leave_type) == (0, None)


@pytest.mark.django_db
def test_termination_sets_reason_and_died(actor: User) -> None:
    from lists.models import DEATH, MeaningfulEntry

    e = _create(actor)
    dep, pos = _dept_pos()
    died = _reason("Нас барсан")
    MeaningfulEntry.objects.create(key=DEATH, value=died.pk)
    _job(e, dep, pos, date(2026, 1, 5), date(2026, 3, 1), JobStatus.ACTIVE)
    _job(e, dep, pos, date(2026, 3, 1), None, JobStatus.LEFT)
    _event(e, "termination", date(2026, 3, 1), fired_reason=died)
    macs_writes.sync_current(e, date(2026, 3, 1))
    e.refresh_from_db()
    assert (e.fired_reason_id, e.died) == (died.pk, "yes")


@pytest.mark.django_db
def test_termination_without_death_meaning_died_no(actor: User) -> None:
    e = _create(actor)
    dep, pos = _dept_pos()
    r = _reason()
    _job(e, dep, pos, date(2026, 1, 5), date(2026, 3, 1), JobStatus.ACTIVE)
    _job(e, dep, pos, date(2026, 3, 1), None, JobStatus.LEFT)
    _event(e, "termination", date(2026, 3, 1), fired_reason=r)
    macs_writes.sync_current(e, date(2026, 3, 1))
    e.refresh_from_db()
    assert (e.fired_reason_id, e.died) == (r.pk, "no")


@pytest.mark.django_db
def test_scheduled_termination_leaves_flags_until_day(actor: User) -> None:
    e = _create(actor)
    dep, pos = _dept_pos()
    r = _reason()
    _job(e, dep, pos, date(2026, 1, 5), date(2026, 3, 1), JobStatus.ACTIVE)
    _job(e, dep, pos, date(2026, 3, 1), None, JobStatus.LEFT)
    _event(e, "termination", date(2026, 3, 1), fired_reason=r)
    macs_writes.sync_current(e, date(2026, 2, 1))
    e.refresh_from_db()
    assert (e.fired_reason_id, e.died) == (None, "no")
    macs_writes.sync_current(e, date(2026, 3, 1))
    e.refresh_from_db()
    assert e.fired_reason_id == r.pk


@pytest.mark.django_db
def test_rehire_clears_reason_and_died(actor: User) -> None:
    from lists.models import DEATH, MeaningfulEntry

    e = _create(actor)
    dep, pos = _dept_pos()
    died = _reason("Нас барсан")
    MeaningfulEntry.objects.create(key=DEATH, value=died.pk)
    _job(e, dep, pos, date(2026, 1, 5), date(2026, 3, 1), JobStatus.ACTIVE)
    _job(e, dep, pos, date(2026, 3, 1), date(2026, 5, 1), JobStatus.LEFT)
    _job(e, dep, pos, date(2026, 5, 1), None, JobStatus.ACTIVE)
    _event(e, "termination", date(2026, 3, 1), fired_reason=died)
    macs_writes.sync_current(e, date(2026, 4, 1))
    e.refresh_from_db()
    assert (e.fired_reason_id, e.died) == (died.pk, "yes")
    macs_writes.sync_current(e, date(2026, 5, 1))
    e.refresh_from_db()
    assert (e.fired_reason_id, e.died) == (None, "no")


@pytest.mark.django_db
def test_legacy_employee_flags_untouched(actor: User) -> None:
    e = _create(actor)
    r = _reason()
    e.taken_leave, e.leave_type, e.fired_reason_id, e.died = 1, 3, r.pk, "yes"
    e.save()
    macs_writes.sync_current(e, date(2026, 6, 1))
    e.refresh_from_db()
    assert (e.taken_leave, e.leave_type, e.fired_reason_id, e.died) == (1, 3, r.pk, "yes")
