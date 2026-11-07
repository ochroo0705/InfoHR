"""Salary amounts keep exact 2-place values through the database (ExactMoneyField).

On PostgreSQL the column stays numeric(14,2). The Firebird double-column path is tested in
app/infohr_firebird/tests/test_exact_money_firebird.py.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from employees.exact_money import ExactMoneyField
from employees.models import ChangeType, Employee, SalaryRecord

pytestmark = pytest.mark.django_db

AMOUNTS = [Decimal("1234567.89"), Decimal("99999999999.99"), Decimal("0.01"), Decimal("0")]


def _record(employee: Employee, amount: Decimal, number: int = 0) -> SalaryRecord:
    # (employee, start_date) is unique, so every record gets its own start date. Each record is closed after one
    # day: an open-ended salary period would overlap the hire's open salary row (Firebird overlap trigger).
    start = date(1990, 1, 1) + timedelta(days=number)
    return SalaryRecord.objects.create(
        employee=employee,
        start_date=start,
        end_date=start + timedelta(days=1),
        base_salary=amount,
        change_type=ChangeType.CORRECTION,
    )


def test_base_salary_uses_exact_money_field() -> None:
    field = SalaryRecord._meta.get_field("base_salary")
    assert isinstance(field, ExactMoneyField)
    assert (field.max_digits, field.decimal_places) == (14, 2)


def test_round_trip_exact(hired: Employee) -> None:
    for number, amount in enumerate(AMOUNTS):
        record = _record(hired, amount, number)
        reread = SalaryRecord.objects.get(pk=record.pk).base_salary
        assert isinstance(reread, Decimal)
        assert reread == amount
        assert str(reread) == f"{amount:.2f}"


def test_thousand_additions_of_ten_cents_is_exact(hired: Employee) -> None:
    pks = [_record(hired, Decimal("0.10"), number).pk for number in range(1000)]
    amounts = [record.base_salary for record in SalaryRecord.objects.filter(pk__in=pks)]
    total = sum(amounts, Decimal("0"))
    assert len(amounts) == 1000
    assert total == Decimal("100.00")
    assert str(total) == "100.00"


def test_values_are_quantized_on_save(hired: Employee) -> None:
    record = _record(hired, Decimal("10.005"), 5000)
    assert SalaryRecord.objects.get(pk=record.pk).base_salary == Decimal("10.01")
