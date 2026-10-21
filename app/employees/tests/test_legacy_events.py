"""Events on employees migrated from MACS with no HR history (QC 1d, 1e): the starting records come from the
MACS row, and the MACS leave/leaving flags survive the first event."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone
from macs.models import FiredReason

from employees.models import ActivityEntry, Employee, Event, ensure_ext
from employees.services import events, history, macs_writes

from .conftest import hire_values
from .test_insurance_columns import login_as

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def _legacy(actor: User, job_values: dict[str, Any], **columns: Any) -> Employee:
    """A MACS-only employee: production row and HR ext, no job or salary records."""
    emp = macs_writes.create_employee(hire_values(), {}, code=macs_writes.next_code(), by=actor)
    ensure_ext(emp)
    values = {
        "department": job_values["department"],
        "position": job_values["position"],
        "salary": Decimal("1800000"),
        "contract_start": date(2018, 3, 1),
    }
    Employee.objects.filter(pk=emp.pk).update(**{**values, **columns})
    return Employee.objects.get(pk=emp.pk)


def _macs_row(emp: Employee) -> Any:
    return Employee.objects.values().get(pk=emp.pk)


def test_start_from_macs_creates_opening_records_from_the_macs_row(actor: User, job_values: dict[str, Any]) -> None:
    emp = _legacy(actor, job_values, emptype=5, contract_no="A-12", contract_end=date(2027, 3, 1))
    before = _macs_row(emp)
    history.start_from_macs(emp, by=actor, effective=TODAY)
    job = emp.job_records.get()
    assert job.change_type == "opening" and job.period.lower == date(2018, 3, 1) and job.period.upper is None
    assert job.department_id == job_values["department"].pk and job.position_id == job_values["position"].pk
    assert job.employee_type == "contract" and job.contract_type == "fixed_term"
    assert job.contract_no == "A-12" and job.contract_end == date(2027, 3, 1) and job.status == "active"
    salary = emp.salary_records.get()
    assert salary.base_salary == Decimal("1800000") and salary.change_type == "opening"
    assert salary.period.lower == date(2018, 3, 1)
    assert _macs_row(emp) == before  # the MACS row is not written
    assert ActivityEntry.objects.filter(employee=emp, kind="history", message__contains="MACS").exists()


def test_start_period_falls_back_to_hire_date_then_effective_date(actor: User, job_values: dict[str, Any]) -> None:
    emp = _legacy(actor, job_values, contract_start=None, first_hire_date=date(2019, 5, 2))
    history.start_from_macs(emp, by=actor, effective=TODAY)
    assert emp.job_records.get().period.lower == date(2019, 5, 2)
    assert emp.job_records.get().contract_start is None  # the blank contract start is not filled (QC 3b)
    other = _legacy(actor, job_values, contract_start=None, first_hire_date=None)
    history.start_from_macs(other, by=actor, effective=TODAY)
    assert other.job_records.get().period.lower == TODAY


def test_salary_change_on_legacy_creates_starting_records_then_the_change(
    actor: User, job_values: dict[str, Any]
) -> None:
    emp = _legacy(actor, job_values)
    events.record(
        emp,
        type="salary_change",
        effective=TODAY,
        changes={},
        salary=Decimal("2000000"),
        reason="",
        note="",
        by=actor,
    )
    opening = emp.salary_records.get(change_type="opening")
    assert opening.base_salary == Decimal("1800000") and opening.period.upper == TODAY
    change = emp.salary_records.get(change_type="salary_change")
    assert change.base_salary == Decimal("2000000") and change.period.lower == TODAY and change.period.upper is None
    job = emp.job_records.get()
    assert job.change_type == "opening" and job.period.upper is None  # a salary change does not touch the job
    emp.refresh_from_db()
    assert emp.salary == Decimal("2000000")


def test_transfer_on_legacy_starts_then_transfers(actor: User, job_values: dict[str, Any]) -> None:
    emp = _legacy(actor, job_values)
    other = macs_writes.save_department("Захиргаа")
    events.record(
        emp,
        type="transfer",
        effective=TODAY,
        changes={"department": other, "position": job_values["position"]},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    records = list(emp.job_records.order_by("period"))
    assert [r.change_type for r in records] == ["opening", "transfer"]
    assert records[0].department_id == job_values["department"].pk and records[0].period.upper == TODAY
    assert records[1].department_id == other.pk
    emp.refresh_from_db()
    assert emp.department_id == other.pk


def test_long_leave_legacy_keeps_taken_leave_and_leave_type(actor: User, job_values: dict[str, Any]) -> None:
    emp = _legacy(actor, job_values, taken_leave=1, leave_type=2)
    events.record(
        emp,
        type="salary_change",
        effective=TODAY,
        changes={},
        salary=Decimal("2000000"),
        reason="",
        note="",
        by=actor,
    )
    emp.refresh_from_db()
    assert emp.taken_leave == 1 and emp.leave_type == 2
    assert emp.job_records.get().status == "long_leave"


def test_left_legacy_keeps_fired_reason_and_died(actor: User, job_values: dict[str, Any]) -> None:
    reason = FiredReason.objects.create(name="Өөрийн хүсэлтээр")
    emp = _legacy(actor, job_values, emptype=3, fired_reason=reason, died="yes")
    events.record(
        emp,
        type="salary_change",
        effective=TODAY,
        changes={},
        salary=Decimal("2000000"),
        reason="",
        note="",
        by=actor,
    )
    emp.refresh_from_db()
    assert emp.fired_reason_id == reason.pk and emp.died == "yes" and emp.emptype == 3
    assert emp.job_records.get().status == "left"


def test_start_from_macs_twice_creates_nothing_new(actor: User, job_values: dict[str, Any]) -> None:
    emp = _legacy(actor, job_values)
    history.start_from_macs(emp, by=actor, effective=TODAY)
    counts = (emp.job_records.count(), emp.salary_records.count(), ActivityEntry.objects.count())
    assert history.start_from_macs(emp, by=actor, effective=TODAY) is None
    assert (emp.job_records.count(), emp.salary_records.count(), ActivityEntry.objects.count()) == counts


def test_missing_department_is_asked_and_required(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    emp = _legacy(actor, job_values, department=None)
    login_as(client, "Accountant")
    url = f"/employees/{emp.pk}/event/salary_change/"
    assert 'name="start_department"' in client.get(url).content.decode()
    data = {"effective": TODAY.isoformat(), "salary": "2000000", "reason": "", "note": ""}
    response = client.post(url, data)
    assert response.status_code == 200 and not Event.objects.exists()
    assert not emp.job_records.exists() and not emp.salary_records.exists()


def test_missing_department_saved_with_form_creates_start(
    client: Client, actor: User, job_values: dict[str, Any]
) -> None:
    emp = _legacy(actor, job_values, department=None)
    login_as(client, "Accountant")
    url = f"/employees/{emp.pk}/event/salary_change/"
    data = {
        "effective": TODAY.isoformat(),
        "salary": "2000000",
        "reason": "",
        "note": "",
        "start_department": job_values["department"].pk,
        "start_position": job_values["position"].pk,
    }
    assert client.post(url, data).status_code == 204
    assert emp.job_records.get().department_id == job_values["department"].pk


def test_menu_shows_for_legacy_employee(client: Client, actor: User, job_values: dict[str, Any]) -> None:
    emp = _legacy(actor, job_values)
    login_as(client, "Accountant")
    body = client.get(f"/employees/{emp.pk}/").content.decode()
    assert f"/employees/{emp.pk}/event/salary_change/" in body


@pytest.mark.parametrize(("emptype", "status", "wagetest"), [(6, "elder", None), (8, "active", 1), (9, "active", 2)])
def test_unmodelled_macs_emptype_survives_the_first_event(
    actor: User, job_values: dict[str, Any], emptype: int, status: str, wagetest: int | None
) -> None:
    emp = _legacy(actor, job_values, emptype=emptype, status=status, wagetest=wagetest)
    events.record(
        emp, type="salary_change", effective=TODAY, changes={}, salary=Decimal("2000000"), reason="", note="", by=actor
    )
    emp.refresh_from_db()
    assert (emp.emptype, emp.status, emp.wagetest) == (emptype, status, wagetest)
    assert emp.salary == Decimal("2000000")


def test_planned_first_event_does_not_start_the_history_in_the_future(actor: User, job_values: dict[str, Any]) -> None:
    from datetime import timedelta

    from employees.listing import row_for

    emp = _legacy(actor, job_values, contract_start=None, first_hire_date=None)
    history.start_from_macs(emp, by=actor, effective=TODAY + timedelta(days=30))
    assert emp.job_records.get().period.lower == TODAY
    assert row_for(Employee.objects.get(pk=emp.pk), TODAY).state == "active"


@pytest.mark.parametrize("emptype", [2, 4])
def test_reserve_and_applicant_rows_keep_their_emptype(actor: User, job_values: dict[str, Any], emptype: int) -> None:
    emp = _legacy(actor, job_values, emptype=emptype, status="resource" if emptype == 2 else "new")
    history.start_from_macs(emp, by=actor, effective=TODAY)
    macs_writes.sync_current(emp, TODAY)
    emp.refresh_from_db()
    assert emp.emptype == emptype and emp.job_records.get().status == "left"


def test_contract_row_without_end_date_opens_as_open_ended(actor: User, job_values: dict[str, Any]) -> None:
    emp = _legacy(actor, job_values, emptype=5, contract_end=None)
    history.start_from_macs(emp, by=actor, effective=TODAY)
    job = emp.job_records.get()
    assert job.employee_type == "contract" and job.contract_type == "open_ended"
