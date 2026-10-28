from datetime import date
from decimal import Decimal

import pytest
from django.db import connection, models

from macs.models import (
    AddedValBudgetRow,
    AddedValStat,
    Branch,
    Employee,
    EmployeeGradeRow,
    FactoryAccidentRow,
    InfoRow,
    LoanRow,
)


@pytest.fixture
def employee(db: None) -> Employee:
    return Employee.objects.create(given_name="Т", family_name="Б")


def test_phase5_mirrors_are_unmanaged() -> None:
    for model in (AddedValStat, AddedValBudgetRow, FactoryAccidentRow, LoanRow, InfoRow, EmployeeGradeRow):
        assert model._meta.managed is False, model.__name__


def test_phase5_tables_and_columns() -> None:
    assert AddedValStat._meta.db_table == "hr_addedvalstat"
    assert AddedValStat._meta.pk.column == "stat_id"
    assert AddedValStat._meta.get_field("percentm").column == "percentm"

    assert AddedValBudgetRow._meta.db_table == "hr_addedvalbudg"
    assert AddedValBudgetRow._meta.get_field("stat").column == "stat_ident"
    assert AddedValBudgetRow._meta.get_field("year").column == "byear"
    assert AddedValBudgetRow._meta.get_field("employee").column == "emp_ident"
    assert AddedValBudgetRow._meta.get_field("dep_id").column == "dep_ident"
    assert AddedValBudgetRow._meta.get_field("budget12").column == "budget12"
    assert AddedValBudgetRow._meta.get_field("exec1").column == "exec1"

    assert FactoryAccidentRow._meta.db_table == "factory_accident"
    assert FactoryAccidentRow._meta.pk.column == "faccident_id"
    assert FactoryAccidentRow._meta.get_field("kind").column == "faccident"
    assert FactoryAccidentRow._meta.get_field("type_code").column == "faccident_type"
    assert FactoryAccidentRow._meta.get_field("employee").column == "empid"
    assert FactoryAccidentRow._meta.get_field("accident_date").column == "accident_date"
    assert FactoryAccidentRow._meta.get_field("branch").column == "branch_ident"

    assert LoanRow._meta.db_table == "hr_loan"
    assert LoanRow._meta.pk.column == "loan_id"
    assert LoanRow._meta.get_field("employee").column == "emp_ident"
    assert LoanRow._meta.get_field("loan_ref").column == "loanref1_ident"
    assert LoanRow._meta.get_field("pay_permonth").column == "pay_permonth"

    assert InfoRow._meta.db_table == "info"
    assert InfoRow._meta.pk.column == "registerno"
    assert InfoRow._meta.get_field("orgtype_code").column == "orgtype_code"

    assert EmployeeGradeRow._meta.db_table == "employee"
    assert EmployeeGradeRow._meta.pk.column == "employee_id"
    assert EmployeeGradeRow._meta.get_field("grade_perc").column == "grade_perc"


def test_budget_months_quarter_two() -> None:
    row = AddedValBudgetRow(
        stat=1,
        year=2026,
        dep_id=3,
        budget4=Decimal("4"),
        budget5=Decimal("5"),
        budget6=Decimal("6"),
        exec4=Decimal("40"),
        exec5=Decimal("50"),
        exec6=Decimal("60"),
    )
    assert row.months(2) == [
        (Decimal("4"), Decimal("40")),
        (Decimal("5"), Decimal("50")),
        (Decimal("6"), Decimal("60")),
    ]


def test_budget_months_quarter_four_and_one() -> None:
    row = AddedValBudgetRow(stat=1, year=2026, dep_id=3, budget10=Decimal("10"), exec12=Decimal("12"))
    assert row.months(4)[0] == (Decimal("10"), Decimal("0"))
    assert row.months(4)[2] == (Decimal("0"), Decimal("12"))
    assert row.months(1) == [(Decimal("0"), Decimal("0"))] * 3


def test_budget_months_rejects_bad_quarter() -> None:
    row = AddedValBudgetRow(stat=1, year=2026, dep_id=3)
    with pytest.raises(ValueError):
        row.months(5)
    with pytest.raises(ValueError):
        row.months(0)


def test_budget_composite_primary_key() -> None:
    pk = AddedValBudgetRow._meta.pk
    assert isinstance(pk, models.CompositePrimaryKey)
    assert [field.name for field in pk.fields] == ["stat", "year", "employee", "dep_id"]


@pytest.mark.django_db
def test_added_val_stat_roundtrip() -> None:
    stat = AddedValStat.objects.create(description="Борлуулалт", stat_type=1, percentm=Decimal("25"))
    stat.refresh_from_db()
    assert stat.pk is not None
    assert stat.description == "Борлуулалт"
    assert stat.percentm == Decimal("25")


@pytest.mark.django_db
def test_loan_roundtrip(employee: Employee) -> None:
    loan = LoanRow.objects.create(
        employee=employee,
        get_date=date(2026, 3, 1),
        end_date=date(2027, 3, 1),
        amount=Decimal("1200000"),
        pay_permonth=Decimal("100000"),
    )
    loan.refresh_from_db()
    assert loan.employee_id == employee.pk
    assert loan.get_date == date(2026, 3, 1)
    assert loan.end_date == date(2027, 3, 1)
    assert loan.amount == Decimal("1200000")
    assert loan.loan_ref_id is None


@pytest.mark.django_db
def test_factory_accident_roundtrip(employee: Employee) -> None:
    branch = Branch.objects.create(name="Төв салбар")
    # faccident_type is a foreign key to factory_accident_type (no model here): seed one type row.
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO factory_accident_type (description) VALUES (%s) RETURNING faccident_type_id", ["Тест"]
        )
        type_id = cursor.fetchone()[0]
    accident = FactoryAccidentRow.objects.create(
        kind="accident",
        type_code=type_id,
        employee=employee,
        accident_date=date(2026, 5, 7),
        group_accident=1,
        facc_type=2,
        facc_reason=3,
        facc_result=1,
        name="Гэмтэл",
        description="Тайлбар",
        branch=branch,
    )
    accident.refresh_from_db()
    assert accident.kind == "accident"
    assert accident.employee_id == employee.pk
    assert accident.accident_date == date(2026, 5, 7)
    assert accident.branch_id == branch.pk
