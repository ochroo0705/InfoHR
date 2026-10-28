from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.db import connection
from django.test import Client
from employees.models import Employee
from macs.models import LoanRefRow, LoanRow

from reports.filters import Filters
from reports.loans import LOANS
from reports.types import Column, Report

from .conftest import count_queries, legacy

pytestmark = pytest.mark.django_db

YEAR = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))


@pytest.fixture(autouse=True)
def no_production_loans() -> None:
    """The test database may hold production loans; each test starts with none."""
    LoanRow.objects.all().delete()


def _loan(employee: Employee, on: date | None, reason: LoanRefRow | None = None, amount: str = "1200000") -> LoanRow:
    """A loan row as the old program keeps one (hr_loan), with a one-year end date."""
    return LoanRow.objects.create(
        employee=employee,
        get_date=on,
        end_date=date(2027, 3, 1),
        amount=Decimal(amount),
        pay_permonth=Decimal("100000"),
        loan_ref=reason,
    )


def _reason(description: str) -> LoanRefRow:
    """A loan reason (loan_refs). The table has a NOT NULL `ref_type` the mirror does not map, so the row is inserted
    as SQL, as test_phase5_models.py does for the accident types."""
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO loan_refs (description, ref_type) VALUES (%s, %s) RETURNING ref_id", [description, 1]
        )
        ref_id = cursor.fetchone()[0]
    return LoanRefRow.objects.get(pk=ref_id)


def _column(report: Report, key: str) -> Column:
    return next(c for c in report.columns if c.key == key)


def test_loans_in_period_with_reason_and_money_columns(accountant_user: User, hired: Employee) -> None:
    _loan(hired, date(2026, 2, 10), reason=_reason("Орон сууц"))
    _loan(hired, date(2026, 5, 1))
    _loan(hired, date(2025, 12, 31))
    rows = LOANS.rows(accountant_user, YEAR)
    assert [r.item.get_date for r in rows] == [date(2026, 2, 10), date(2026, 5, 1)]
    first = rows[0]
    assert _column(LOANS, "reason").value(first) == "Орон сууц"
    assert _column(LOANS, "end_date").value(first) == date(2027, 3, 1)
    amount = _column(LOANS, "amount")
    assert amount.money and amount.numeric
    assert amount.value(first) == Decimal("1200000.00")
    per_month = _column(LOANS, "per_month")
    assert per_month.money and per_month.numeric
    assert per_month.value(first) == Decimal("100000.00")


def test_loan_without_reference_shows_blank_reason(accountant_user: User, hired: Employee) -> None:
    _loan(hired, date(2026, 3, 3), reason=None)
    assert _column(LOANS, "reason").value(LOANS.rows(accountant_user, YEAR)[0]) is None


def test_loan_without_get_date_is_left_out(accountant_user: User, hired: Employee) -> None:
    _loan(hired, None)
    _loan(hired, date(2026, 3, 3))
    assert len(LOANS.rows(accountant_user, YEAR)) == 1


def test_hr_is_refused_and_accountant_opens(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "hr-loans")
    assert client.get("/reports/loans/").status_code == 403
    login_as(client, "Accountant", "accountant-loans")
    for suffix in ("", "print/", "excel/"):
        assert client.get(f"/reports/loans/{suffix}").status_code == 200


def test_employee_role_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee", "viewer")
    assert client.get("/reports/loans/").status_code == 403


def test_loan_query_count_does_not_grow_with_rows(
    accountant_user: User, actor: User, job_values: dict[str, Any], hired: Employee
) -> None:
    # Three different people, legacy first (the one-person baseline is legacy too); legacy people have no HR job row.
    first, *others = [legacy(actor, job_values), hired, legacy(actor, job_values)]
    _loan(first, date(2026, 2, 10), reason=_reason("Орон сууц"))
    one = count_queries(LOANS, accountant_user, YEAR)
    for person in others:
        _loan(person, date(2026, 2, 11), reason=_reason("Машин"))
    assert len(LOANS.rows(accountant_user, YEAR)) == 3
    three = count_queries(LOANS, accountant_user, YEAR)
    assert three[1] - three[0] == one[1] - one[0]  # rendering adds the same queries for 1 and 3 people
