"""Inline edit from the data gaps and household income reports: the edit columns they offer (reports.cell_edit)."""

from collections.abc import Callable
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee

from reports import household_income
from reports.data_gaps import REPORT as DATA_GAPS
from reports.types import Column

from .conftest import legacy

pytestmark = pytest.mark.django_db

PAGE = "/reports/data-gaps/"
HEADER_SUFFIX = " <span"  # a column header is drawn as «<label> <span …» (templates/reports/_table.html)


def _header(label: str) -> str:
    return f">{label}{HEADER_SUFFIX}"


def test_data_gaps_edit_cell_for_a_blank_register_number(
    client: Client, login_as: Callable[..., User], actor: User, job_values: dict[str, Any]
) -> None:
    emp: Employee = legacy(actor, job_values, register_no="")  # a gap: the checked register number is blank
    login_as(client, "HR")
    page = client.get(PAGE + "?cols=code&cols=name&cols=register_no").content.decode()
    assert _header("Регистрийн дугаар") in page
    assert f'data-edit="/reports/cell/?person={emp.pk}&amp;field=register_no"' in page


def test_data_gaps_default_columns_are_unchanged(
    client: Client, login_as: Callable[..., User], actor: User, job_values: dict[str, Any]
) -> None:
    legacy(actor, job_values, email="")  # a gap in e-mail only; the register number is filled
    login_as(client, "HR")
    page = client.get(PAGE).content.decode()
    assert "Дутуу талбар" in page  # the original headers are shown
    assert _header("Бүрдэл, %") in page
    assert _header("Дутуу мэдээлэл") in page
    assert _header("Регистрийн дугаар") not in page  # the edit columns are not in the default set
    assert _header("Хувийн утас") not in page
    assert "data-edit=" not in page
    assert DATA_GAPS.default_columns == (
        "code",
        "name",
        "department",
        "position",
        "missing_count",
        "filled_pct",
        "missing",
    )
    assert DATA_GAPS.picks_columns is True


def test_household_income_gender_column_is_editable() -> None:
    gender = next(c for c in household_income.REPORT.columns if c.key == "gender")
    assert isinstance(gender, Column)
    assert gender.edit == "gender"
    assert household_income.REPORT.person is not None
