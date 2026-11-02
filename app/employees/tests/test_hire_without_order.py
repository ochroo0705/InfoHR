from datetime import date
from typing import Any

import pytest
from accounts.models import User

from employees.models import HrOrder, JobRecord
from employees.services import history
from employees.tests.conftest import hire_values


def test_hire_without_order_creates_no_order(actor: User, job_values: dict[str, Any]) -> None:
    e = history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=None,
        by=actor,
        with_order=False,
    )

    assert HrOrder.objects.filter(employee=e).count() == 0
    assert JobRecord.objects.filter(employee=e).count() == 1
    assert e.pk is not None


def test_hire_default_still_creates_pending_order(actor: User, job_values: dict[str, Any]) -> None:
    e = history.hire(hire_values(), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)

    orders = HrOrder.objects.filter(employee=e)
    assert orders.count() == 1
    assert orders.get().is_hire is True


def test_minimal_values_hire(actor: User, job_values: dict[str, Any]) -> None:
    values = {
        "family_name": "Батын",
        "given_name": "Сараа",
        "passport_no": "A1234567",
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "first_hire_date": date(2026, 1, 5),
    }

    e = history.hire(values, {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor, with_order=False)

    assert e.pk is not None
    assert HrOrder.objects.filter(employee=e).count() == 0


def test_order_args_refused_without_order(actor: User, job_values: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        history.hire(
            hire_values(),
            {},
            start=date(2026, 1, 5),
            job=job_values,
            salary=None,
            by=actor,
            with_order=False,
            order_number="1",
        )


def test_hire_sets_setup_required_unless_the_caller_says_otherwise(actor: User, job_values: dict[str, Any]) -> None:
    kwargs: dict[str, Any] = {"start": date(2026, 1, 5), "job": job_values, "salary": None, "by": actor}
    default = history.hire(hire_values("УБ99112233"), {}, **kwargs)
    skipped = history.hire(hire_values("УБ99112244"), {"setup_required": False}, **kwargs)
    assert default.ext.setup_required is True
    assert skipped.ext.setup_required is False
