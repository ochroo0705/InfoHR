import itertools
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from macs.models import FiredReason

from employees.models import Employee, Event, HrOrder, OrderState, ensure_ext
from employees.services import history, macs_writes
from employees.services.movements import changes

from .conftest import hire_values, named
from .helpers import record_signed

pytestmark = pytest.mark.django_db

_register_numbers = itertools.count(10_000_000)


def legacy(by: User, jobs: dict[str, Any], **columns: Any) -> Employee:
    """An employee with a MACS row and no HR job history (copy of reports/tests/conftest.py::legacy)."""
    register_no = f"УБ{next(_register_numbers)}"
    emp = macs_writes.create_employee(hire_values(register_no), {}, code=macs_writes.next_code(), by=by)
    ensure_ext(emp)
    values = {"department": jobs["department"], "position": jobs["position"], "salary": Decimal("1800000")}
    Employee.objects.filter(pk=emp.pk).update(**{**values, **columns})
    return Employee.objects.get(pk=emp.pk)


def transfer(employee: Employee, to: str, on: date, by: User) -> Event:
    """Move the employee to another department from `on` (copy of reports/tests/conftest.py::transfer)."""
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
def left_employee(actor: User, job_values: dict[str, Any]) -> Employee:
    """Hired in January 2026 and dismissed on 2026-03-01 (copy of reports/tests/conftest.py::left_employee)."""
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


def test_hire_and_transfer_with_previous_department(hired: Employee, actor: User) -> None:
    transfer(hired, to="Борлуулалт", on=date(2026, 6, 1), by=actor)
    got = changes(Employee.objects.all(), date(2026, 1, 1), date(2026, 12, 31))
    assert [(c.kind, c.day) for c in got] == [("hire", date(2026, 1, 5)), ("transfer", date(2026, 6, 1))]
    assert got[1].from_department is not None and got[1].from_department.name == "Санхүү"
    assert got[1].department is not None and got[1].department.name == "Борлуулалт"
    assert got[0].from_department is None and not got[0].legacy


def test_window_and_kinds_filter(hired: Employee, actor: User) -> None:
    transfer(hired, to="Борлуулалт", on=date(2026, 6, 1), by=actor)
    got = changes(Employee.objects.all(), date(2026, 2, 1), date(2026, 12, 31), kinds={"transfer"})
    assert [c.kind for c in got] == ["transfer"]
    assert got[0].from_department is not None and got[0].from_department.name == "Санхүү"


def test_termination_carries_reason(left_employee: Employee) -> None:
    got = changes(Employee.objects.all(), date(2026, 1, 1), date(2026, 12, 31), kinds={"termination"})
    assert len(got) == 1
    assert got[0].fired_reason is not None and got[0].fired_reason.name == "Өөрийн хүсэлтээр"
    assert got[0].day == date(2026, 3, 1)


def test_legacy_person_shows_only_as_hire(actor: User, job_values: dict[str, Any]) -> None:
    emp = legacy(actor, job_values, first_hire_date=date(2025, 4, 1))
    got = changes(Employee.objects.filter(pk=emp.pk), date(2025, 1, 1), date(2025, 12, 31))
    assert [(c.kind, c.legacy, c.department.name if c.department else None) for c in got] == [("hire", True, "Санхүү")]
    assert (
        changes(Employee.objects.filter(pk=emp.pk), date(2025, 1, 1), date(2025, 12, 31), kinds={"termination"}) == []
    )


def test_hire_order_number_shown_and_cancelled_hidden(hired: Employee) -> None:
    order = HrOrder.objects.get(employee=hired, is_hire=True)
    HrOrder.objects.filter(pk=order.pk).update(number="77", state=OrderState.REGISTERED)
    assert changes(Employee.objects.all(), date(2026, 1, 1), date(2026, 12, 31))[0].order_number == "77"
    HrOrder.objects.filter(pk=order.pk).update(state=OrderState.CANCELLED)
    assert changes(Employee.objects.all(), date(2026, 1, 1), date(2026, 12, 31))[0].order_number == ""


def test_legacy_hire_kept_after_first_event(actor: User, job_values: dict[str, Any]) -> None:
    emp = legacy(actor, job_values, first_hire_date=date(2026, 2, 1))
    transfer(emp, to="Борлуулалт", on=date(2026, 6, 1), by=actor)
    got = changes(Employee.objects.filter(pk=emp.pk), date(2026, 1, 1), date(2026, 12, 31), kinds={"hire", "transfer"})
    assert [c.kind for c in got] == ["hire", "transfer"]
    assert got[0].day == date(2026, 2, 1) and got[0].legacy


def test_hired_person_has_one_hire(hired: Employee, actor: User) -> None:
    transfer(hired, to="Борлуулалт", on=date(2026, 6, 1), by=actor)
    got = changes(Employee.objects.filter(pk=hired.pk), date(2026, 1, 1), date(2026, 12, 31), kinds={"hire"})
    assert [(c.kind, c.legacy) for c in got] == [("hire", False)]


def test_event_order_number_shown_and_cancelled_hidden(hired: Employee, actor: User) -> None:
    ev = transfer(hired, to="Борлуулалт", on=date(2026, 6, 1), by=actor)
    HrOrder.objects.filter(event=ev).update(number="88", state=OrderState.REGISTERED)
    got = changes(Employee.objects.all(), date(2026, 1, 1), date(2026, 12, 31), kinds={"transfer"})
    assert [c.order_number for c in got] == ["88"]
    HrOrder.objects.filter(event=ev).update(state=OrderState.CANCELLED)
    got = changes(Employee.objects.all(), date(2026, 1, 1), date(2026, 12, 31), kinds={"transfer"})
    assert [c.order_number for c in got] == [""]
