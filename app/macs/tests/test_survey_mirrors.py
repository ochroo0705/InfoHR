import pytest

from macs.models import (
    Branch,
    Employee,
    EmployeeIncomeRow,
    IncomeLevel,
    NazgRow,
    OccupationKind,
    Position,
)


@pytest.mark.django_db
def test_income_level_roundtrip() -> None:
    row = IncomeLevel.objects.create(level="Доод", lower=0, upper=150000)
    row.refresh_from_db()
    assert row.pk is not None
    assert row.level == "Доод"
    assert row.lower == 0
    assert row.upper == 150000


@pytest.mark.django_db
def test_nazg_row_roundtrip() -> None:
    position = Position.objects.create(name="Инженер")
    branch = Branch.objects.create(name="Төв салбар")
    row = NazgRow.objects.create(
        kind="Main",
        qty=3,
        year=2026,
        position=position,
        branch=branch,
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.kind == "Main"
    assert row.qty == 3
    assert row.year == 2026
    assert row.position_id == position.pk
    assert row.branch_id == branch.pk


@pytest.mark.django_db
def test_occupation_kind_reads_position_row() -> None:
    # The occupation table has no separate create path here: a position row
    # (written by the Position model) is read back through OccupationKind.
    position = Position.objects.create(name="Механик")
    OccupationKind.objects.filter(pk=position.pk).update(character="ENG")
    kind = OccupationKind.objects.get(pk=position.pk)
    assert kind.character == "ENG"


@pytest.mark.django_db
def test_employee_income_row_reads_employee_income() -> None:
    # The employee table is written by the Employee model; the income column is
    # set through the mirror and read back.
    employee = Employee.objects.create(given_name="Б", family_name="Д")
    EmployeeIncomeRow.objects.filter(pk=employee.pk).update(income=1200000)
    row = EmployeeIncomeRow.objects.get(pk=employee.pk)
    assert row.income == 1200000


def test_mirrors_are_unmanaged() -> None:
    for model in (IncomeLevel, NazgRow, OccupationKind, EmployeeIncomeRow):
        assert model._meta.managed is False, model.__name__
