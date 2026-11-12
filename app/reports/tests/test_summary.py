"""The summary a chart or pivot address adds to print and Excel: the screen's numbers as a grid, the row table stays."""

import io
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import openpyxl
import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from employees.models import Employee
from employees.services import history, macs_writes

from reports.filters import parse_filters
from reports.staff_list import REPORT
from reports.summary import summary_of
from reports.table import build_table

from .conftest import hire_values

pytestmark = pytest.mark.django_db

PRINT = "/reports/staff-list/print/"
EXCEL = "/reports/staff-list/excel/"
XLSX_SHEET = "staff-list"
SUMMARY_SHEET = "Нэгтгэл"


def _table(user: User, query: str) -> Any:
    return build_table(REPORT, user, parse_filters(QueryDict(query)))


@pytest.fixture
def staff(actor: User, job_values: dict[str, Any]) -> list[Employee]:
    """Two people in Санхүү (accountant and engineer) and one in Ачаа; all working since 2026-01-05."""
    people = []
    for register_no, dept, pos in [
        ("УБ70000001", "Санхүү", "Нягтлан"),
        ("УБ70000002", "Санхүү", "Инженер"),
        ("УБ70000003", "Ачаа", "Нягтлан"),
    ]:
        job = {
            **job_values,
            "department": macs_writes.save_department(dept),
            "position": macs_writes.save_position(pos),
        }
        people.append(
            history.hire(
                hire_values(register_no=register_no),
                {},
                start=date(2026, 1, 5),
                job=job,
                salary=Decimal("2500000"),
                by=actor,
            )
        )
    return people


def test_chart_summary_counts_by_department(hr_user: User, staff: list[Employee]) -> None:
    summary = summary_of(_table(hr_user, "layout=chart&lby=department"))
    assert summary is not None
    assert summary.kind == "bar"
    assert summary.head == ["Хэлтэс", "Тоо"]
    assert summary.lines == [["Ачаа", 1], ["Санхүү", 2]]  # the screen's order: named categories by casefold
    assert summary.foot is None
    assert summary.money is False
    assert summary.title == "Диаграм: Хэлтэс · Тоо"


def test_stacked_chart_summary_ends_with_the_total(hr_user: User, staff: list[Employee]) -> None:
    summary = summary_of(_table(hr_user, "layout=chart&lchart=stacked&lby=department&lby2=position"))
    assert summary is not None
    assert summary.kind == "stacked"
    assert summary.head[0] == "Хэлтэс" and summary.head[-1] == "Нийт"
    series = summary.head[1:-1]
    assert series == ["Инженер", "Нягтлан"]
    for line in summary.lines:
        assert len(line) == len(summary.head)
        assert line[-1] == sum(line[1:-1])
    assert summary.lines == [["Ачаа", 0, 1, 1], ["Санхүү", 1, 1, 2]]


def test_pivot_summary_has_totals_and_grand_total(hr_user: User, staff: list[Employee]) -> None:
    summary = summary_of(_table(hr_user, "layout=pivot&lby=department&lby2=position"))
    assert summary is not None
    assert summary.kind == "pivot"
    assert summary.title.startswith("Хөрвүүлэлт: Хэлтэс / Албан тушаал")
    assert summary.foot is not None
    assert summary.foot[0] == "Дүн"
    assert summary.foot[-1] == 3


def test_table_layout_and_empty_result_have_no_summary(hr_user: User, staff: list[Employee]) -> None:
    assert summary_of(_table(hr_user, "")) is None
    assert summary_of(_table(hr_user, "layout=chart&lby=department&state=left")) is None


def test_print_chart_address_shows_summary_before_the_row_table(
    client: Client, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    login_as(client, "HR")
    page = client.get(f"{PRINT}?layout=chart&lby=department").content.decode()
    assert "Диаграм: Хэлтэс · Тоо" in page
    row_table = page.index("<thead>", page.index("<thead>") + 1)  # the first thead is the summary's
    assert page.index("Ачаа") < row_table and page.index("Санхүү") < row_table
    assert "Нийт: 3" in page


def test_print_table_address_has_no_summary(
    client: Client, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    login_as(client, "HR")
    page = client.get(f"{PRINT}?cols=code&cols=name").content.decode()
    assert "<h2" not in page


def test_excel_chart_address_adds_a_summary_sheet_with_a_chart(
    client: Client, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    login_as(client, "HR")
    resp = client.get(f"{EXCEL}?layout=chart&lby=department")
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == [XLSX_SHEET, SUMMARY_SHEET]
    ws: Any = wb[SUMMARY_SHEET]
    assert ws["A3"].value == "Хэлтэс" and ws["B3"].value == "Тоо"
    assert ws["B4"].value == 1 and ws["B5"].value == 2
    assert ws["B4"].data_type == "n"
    assert len(ws._charts) == 1


def test_excel_pivot_address_adds_a_summary_sheet_without_a_chart(
    client: Client, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    login_as(client, "HR")
    resp = client.get(f"{EXCEL}?layout=pivot&lby=department&lby2=position")
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == [XLSX_SHEET, SUMMARY_SHEET]
    assert len(wb[SUMMARY_SHEET]._charts) == 0


def test_excel_table_address_has_one_sheet(
    client: Client, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    login_as(client, "HR")
    resp = client.get(f"{EXCEL}?cols=code")
    assert openpyxl.load_workbook(io.BytesIO(resp.content)).sheetnames == [XLSX_SHEET]


def test_summary_label_starting_with_equals_is_text(
    client: Client, login_as: Callable[..., User], actor: User, job_values: dict[str, Any]
) -> None:
    job = {**job_values, "department": macs_writes.save_department("=Касса")}
    history.hire(
        hire_values(register_no="УБ70000009"),
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=actor,
    )
    login_as(client, "HR")
    resp = client.get(f"{EXCEL}?layout=chart&lby=department")
    ws: Any = openpyxl.load_workbook(io.BytesIO(resp.content))[SUMMARY_SHEET]
    cells = [cell for row in ws.iter_rows() for cell in row if cell.value == "=Касса"]
    assert len(cells) == 1 and cells[0].data_type == "s"


def test_excel_stacked_chart_has_one_series_per_stack_not_the_total(
    client: Client, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    login_as(client, "HR")
    resp = client.get(f"{EXCEL}?layout=chart&lchart=stacked&lby=department&lby2=position")
    ws: Any = openpyxl.load_workbook(io.BytesIO(resp.content))[SUMMARY_SHEET]
    (chart,) = ws._charts
    assert len(chart.series) == 2  # Инженер and Нягтлан; the Нийт column is not a series
    assert chart.grouping == "stacked" and chart.overlap == 100
