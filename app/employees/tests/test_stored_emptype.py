"""Employee type is stored on the job record (D-028) and pension exits (D-029)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.utils import timezone
from macs.models import FiredReason

from employees.models import Employee, EmployeeExt, ensure_ext
from employees.services import events, history, macs_writes

from .conftest import hire_values, named

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def _rec(emp: Employee, actor: User, type: str, effective: date, **kw: Any) -> Any:
    args: dict[str, Any] = {"changes": {}, "salary": None, "reason": "", "note": "", "by": actor} | kw
    return events.record(emp, type=type, effective=effective, **args)


def _prod(emp: Employee) -> Employee:
    return Employee.objects.get(pk=emp.pk)


def _hire(actor: User, job_values: dict[str, Any], **ext: Any) -> Employee:
    return history.hire(hire_values(), ext, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)


def test_probation_does_not_end_by_date(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values, probation_end=TODAY - timedelta(days=1))
    macs_writes.sync_current(emp, TODAY)
    assert _prod(emp).emptype == 9


def test_hire_with_probation_is_9_else_1(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values, probation_end=TODAY + timedelta(days=30))
    assert emp.job_records.get().emptype == 9
    other = history.hire(hire_values("УБ11223344"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    assert other.job_records.get().emptype == 1 and _prod(other).emptype == 1


def test_contract_change_sets_type(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values, probation_end=TODAY + timedelta(days=30))
    _rec(emp, actor, "contract", TODAY, changes={"emptype": 1, "contract_no": "C-1"})
    assert _prod(emp).emptype == 1


def test_termination_with_pension_is_elder(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values)
    _rec(emp, actor, "termination", TODAY, fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"), pension=True)
    row = _prod(emp)
    assert (row.emptype, row.status, row.contract_flag, row.wagetest) == (6, "elder", "no", None)


def test_termination_without_pension_is_3(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values)
    _rec(emp, actor, "termination", TODAY, fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"))
    assert _prod(emp).emptype == 3


def test_contract_change_with_pension_marks_pensioner(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values)
    _rec(emp, actor, "contract", TODAY, changes={"contract_no": "P-1"}, pension=True)
    assert _prod(emp).status == "active"
    assert EmployeeExt.objects.get(employee=emp).is_pensioner is True


def test_opening_job_keeps_macs_type(actor: User, job_values: dict[str, Any]) -> None:
    emp = macs_writes.create_employee(hire_values(), {}, code=macs_writes.next_code(), by=actor)
    ensure_ext(emp)
    Employee.objects.filter(pk=emp.pk).update(
        department=job_values["department"],
        position=job_values["position"],
        salary=Decimal("1800000"),
        contract_start=date(2018, 3, 1),
        emptype=5,
        contract_end=date(2030, 1, 1),
    )
    emp = _prod(emp)
    _rec(emp, actor, "salary_change", TODAY, salary=Decimal("1900000"))
    first = emp.job_records.order_by("period").first()
    assert first is not None and first.emptype == 5


def _pensioner(emp: Employee) -> bool:
    return EmployeeExt.objects.get(employee=emp).is_pensioner


def test_cancel_pension_contract_change_clears_pensioner(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values)
    ev = _rec(emp, actor, "contract", TODAY + timedelta(days=5), changes={"contract_no": "P-1"}, pension=True)
    assert _pensioner(emp)
    events.cancel(ev, reason="алдаа", by=actor)
    assert not _pensioner(emp)


def test_cancel_keeps_pensioner_from_an_earlier_event(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values)
    _rec(emp, actor, "contract", TODAY + timedelta(days=5), changes={"contract_no": "P-1"}, pension=True)
    second = _rec(emp, actor, "contract", TODAY + timedelta(days=9), changes={"contract_no": "P-2"}, pension=True)
    events.cancel(second, reason="алдаа", by=actor)
    assert _pensioner(emp)


def test_rehire_after_pension_termination(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values)
    _rec(
        emp,
        actor,
        "termination",
        TODAY - timedelta(days=10),
        fired_reason=named(FiredReason, "Өөрийн хүсэлтээр"),
        pension=True,
    )
    assert _prod(emp).emptype == 6
    _rec(
        emp,
        actor,
        "rehire",
        TODAY - timedelta(days=2),
        changes={"emptype": 5, "contract_type": "fixed_term", "contract_end": TODAY + timedelta(days=300)},
    )
    row = _prod(emp)
    assert (row.emptype, row.status) == (5, "active")


def test_fixed_term_hire_is_5(actor: User, job_values: dict[str, Any]) -> None:
    job = job_values | {"contract_type": "fixed_term", "contract_end": date(2027, 1, 5)}
    emp = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=job, salary=None, by=actor)
    assert emp.job_records.get().emptype == 5 and _prod(emp).emptype == 5


def test_pension_on_transfer_rejected(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values)
    dep = macs_writes.save_department("Бусад")
    with pytest.raises(events.EventError) as exc:
        _rec(emp, actor, "transfer", TODAY, changes={"department": dep}, pension=True)
    assert "pension" in exc.value.errors


def test_legacy_job_without_emptype_keeps_production_value(actor: User, job_values: dict[str, Any]) -> None:
    emp = _hire(actor, job_values)
    emp.job_records.update(emptype=None)
    Employee.objects.filter(pk=emp.pk).update(emptype=5, status="active", contract_flag="yes")
    macs_writes.sync_current(_prod(emp), TODAY)
    assert _prod(emp).emptype == 5


@pytest.mark.parametrize(
    ("held", "status", "keeps"),
    [(8, "active", True), (2, "left", True), (4, "left", True), (8, "left", False), (2, "active", False)],
)
def test_keeps_emptype(held: int, status: str, keeps: bool) -> None:
    class J:
        pass

    job = J()
    job.status = status  # type: ignore[attr-defined]
    emp = Employee(emptype=held)
    assert macs_writes.keeps_emptype(emp, job, EmployeeExt()) is keeps  # type: ignore[arg-type]
