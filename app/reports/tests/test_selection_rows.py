"""A report says which employee each row is (Report.person), and every cell of a row carries that id."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from employees.access import visible_employees
from employees.models import Employee

from reports import registry
from reports.filters import Filters
from reports.table import build_table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db


def _report(person: Callable[[Any], int] | None) -> Report:
    people = [SimpleNamespace(id=7, name="Бат"), SimpleNamespace(id=9, name="Дорж")]
    return Report(
        key="person-test",
        title="Туршилт",
        filters=("state",),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="id", label="Дугаар", value=lambda r: r.id),
        ),
        default_columns=("name", "id"),
        rows=lambda user, filters: people,
        person=person,
    )


def test_cells_carry_person_when_report_opts_in(hr_user: User) -> None:
    table = build_table(_report(lambda r: r.id), hr_user, Filters())
    rows = [row for _, group in table.groups for row in group]
    assert [[cell.person for cell in row] for row in rows] == [[7, 7], [9, 9]]


def test_cells_person_zero_without_person(hr_user: User) -> None:
    table = build_table(_report(None), hr_user, Filters())
    rows = [row for _, group in table.groups for row in group]
    assert all(cell.person == 0 for row in rows for cell in row)


def test_staff_list_opts_in(hr_user: User, hired: Employee) -> None:
    report = registry.get("staff-list")
    assert report is not None and report.person is not None
    table = build_table(report, hr_user, Filters())
    visible = set(visible_employees(hr_user).values_list("pk", flat=True))
    rows = [row for _, group in table.groups for row in group]
    assert rows, "the staff list should show at least the hired employee"
    for row in rows:
        assert row[0].person in visible
    assert hired.pk in {row[0].person for row in rows}
