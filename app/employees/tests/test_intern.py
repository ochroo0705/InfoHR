"""Interns: a type of their own, always on a fixed-term contract (the end date is the planned end of the internship)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User

from employees.models import ContractType, EmployeeType, JobRecord, contract_errors
from employees.services import events, history
from employees.services.events import EventError

from .conftest import hire_values
from .helpers import record_signed

pytestmark = pytest.mark.django_db


def _intern_job(job_values: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        **job_values,
        "employee_type": EmployeeType.INTERN,
        "contract_type": ContractType.FIXED_TERM,
        "contract_start": date(2026, 1, 5),
        "contract_end": date(2026, 4, 5),
        **extra,
    }


def test_an_intern_must_be_fixed_term() -> None:
    assert contract_errors("open_ended", None, None, EmployeeType.INTERN) == {
        "contract_type": "Дадлагжигч хугацаатай гэрээтэй байна."
    }
    assert contract_errors("open_ended", None, None, EmployeeType.FULL_TIME) == {}
    assert "contract_end" in contract_errors("fixed_term", None, None, EmployeeType.INTERN)  # an end date is needed
    assert contract_errors("fixed_term", date(2026, 1, 5), date(2026, 4, 5), EmployeeType.INTERN) == {}


def test_job_row_clean_refuses_an_open_ended_intern(job_values: dict[str, Any]) -> None:
    row = JobRecord(employee_type=EmployeeType.INTERN, contract_type=ContractType.OPEN_ENDED)
    errors = contract_errors(row.contract_type, row.contract_start, row.contract_end, row.employee_type)
    assert "contract_type" in errors


def test_intern_is_hired_with_no_salary_and_gets_the_fixed_term_code(actor: User, job_values: dict[str, Any]) -> None:
    intern = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=_intern_job(job_values), salary=None, by=actor)
    job = history.job_on(intern, date(2026, 1, 5))
    assert job is not None and job.employee_type == EmployeeType.INTERN
    assert job.emptype == 5  # the MACS code for a fixed-term contract: no new code in the MACS tables
    intern.refresh_from_db()
    assert intern.emptype == 5


def test_contract_change_turns_an_intern_into_staff(actor: User, job_values: dict[str, Any]) -> None:
    intern = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=_intern_job(job_values), salary=None, by=actor)
    record_signed(
        intern,
        type="contract",
        effective=date(2026, 4, 6),
        changes={"employee_type": EmployeeType.FULL_TIME, "contract_type": ContractType.OPEN_ENDED},
        salary=None,
        reason="",
        note="",
        by=actor,
    )
    job = history.job_on(intern, date(2026, 4, 6))
    assert job is not None and job.employee_type == EmployeeType.FULL_TIME and job.contract_end is None


def test_a_contract_change_cannot_make_an_open_ended_intern(actor: User, job_values: dict[str, Any]) -> None:
    staff = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=job_values, salary=Decimal("2500000"), by=actor)
    with pytest.raises(EventError) as caught:
        events.record(
            staff,
            type="contract",
            effective=date(2026, 4, 6),
            changes={"employee_type": EmployeeType.INTERN},
            salary=None,
            reason="",
            note="",
            by=actor,
        )
    assert "contract_type" in caught.value.errors
