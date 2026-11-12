"""Small-group protection: a chart or pivot money figure over fewer rows than REPORTS_MIN_GROUP is not shown."""

import io
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import openpyxl
import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee
from employees.services import history, macs_writes

from reports import layouts as layouts_mod
from reports import privacy
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.summary import summary_of
from reports.table import Table
from reports.types import Column

from .conftest import hire_values

TODAY = date(2026, 11, 7)

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
GENDER = Column(key="gender", label="Хүйс", value=lambda r: r.gender, kind="text")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number", numeric=True, money=True)
AGE = Column(key="age", label="Нас", value=lambda r: r.age, kind="number", numeric=True)


def _row(dept: object = "Санхүү", pay: object = 0, gender: object = "Эр", age: object = 30) -> Any:
    return SimpleNamespace(name="x", dept=dept, pay=pay, gender=gender, age=age)


def _rows(dept: str, pays: list[int]) -> list[Any]:
    return [_row(dept=dept, pay=Decimal(p)) for p in pays]


def _table(rows: list[Any], spec: LayoutSpec) -> Table:
    columns = [NAME, DEPT, GENDER, PAY, AGE]
    return Table(columns=columns, groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)


def _chart_spec(value: tuple[Column | None, str], by: Column = DEPT) -> LayoutSpec:
    return LayoutSpec(layout="chart", by=by, by2=None, value=value, chart="bar", month=date(2026, 11, 1))


def _pivot_spec(value: tuple[Column | None, str]) -> LayoutSpec:
    return LayoutSpec(layout="pivot", by=DEPT, by2=GENDER, value=value, chart="bar", month=date(2026, 11, 1))


def test_default_hides_a_money_aggregate_under_three_rows(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 3  # the default too
    assert privacy.masked((PAY, "avg"), [_row(), _row()]) is True
    assert privacy.masked((PAY, "avg"), [_row(), _row(), _row()]) is False


def test_count_and_missing_column_are_never_hidden() -> None:
    assert privacy.masked((None, "count"), [_row()]) is False
    assert privacy.masked((PAY, "count"), [_row()]) is False


def test_non_money_number_column_is_never_hidden() -> None:
    assert privacy.masked((AGE, "avg"), [_row()]) is False


def test_empty_bucket_is_not_hidden() -> None:
    assert privacy.masked((PAY, "sum"), []) is False


def test_setting_one_or_zero_turns_the_rule_off(settings: Any) -> None:
    rows = [_row(), _row()]
    settings.REPORTS_MIN_GROUP = 1
    assert privacy.masked((PAY, "avg"), rows) is False
    settings.REPORTS_MIN_GROUP = 0
    assert privacy.masked((PAY, "avg"), rows) is False


def test_larger_setting_hides_four_rows(settings: Any) -> None:
    settings.REPORTS_MIN_GROUP = 5
    assert privacy.masked((PAY, "avg"), [_row()] * 4) is True


def test_chart_hides_the_money_average_of_small_departments() -> None:
    rows = _rows("Ачаа", [100, 200, 300]) + _rows("Санхүү", [100, 200]) + _rows("Тээвэр", [500])
    spec = _chart_spec((PAY, "avg"))
    chart = layouts_mod.build_chart(_table(rows, spec), spec)
    assert [p.label for p in chart.points] == ["Ачаа", "Санхүү", "Тээвэр"]
    assert chart.points[0].value == 200
    assert chart.points[1].value is None
    assert chart.points[2].value is None
    assert chart.masked is True


def test_chart_count_of_the_same_departments_shows_every_number() -> None:
    rows = _rows("Ачаа", [100, 200, 300]) + _rows("Санхүү", [100, 200]) + _rows("Тээвэр", [500])
    spec = _chart_spec((None, "count"))
    chart = layouts_mod.build_chart(_table(rows, spec), spec)
    assert [p.value for p in chart.points] == [3, 2, 1]
    assert chart.masked is False


def test_chart_without_small_groups_is_not_masked() -> None:
    rows = _rows("Ачаа", [100, 200, 300]) + _rows("Санхүү", [100, 200, 400])
    spec = _chart_spec((PAY, "avg"))
    chart = layouts_mod.build_chart(_table(rows, spec), spec)
    assert chart.masked is False


def test_pivot_hides_small_cells_but_shows_a_large_row_total() -> None:
    rows = [
        _row(dept="Ачаа", pay=Decimal(100), gender="Эр"),
        _row(dept="Ачаа", pay=Decimal(200), gender="Эр"),
        _row(dept="Ачаа", pay=Decimal(300), gender="Эмэгтэй"),
        _row(dept="Санхүү", pay=Decimal(400), gender="Эмэгтэй"),
    ]
    spec = _pivot_spec((PAY, "sum"))
    pivot = layouts_mod.build_pivot(_table(rows, spec), spec)
    assert pivot.row_labels == ["Ачаа", "Санхүү"]
    # col_labels are Эмэгтэй, Эр: every cell is under 3 rows, so each cell is hidden; Ачаа's total has 3 rows
    assert pivot.col_labels == ["Эмэгтэй", "Эр"]
    assert pivot.cells[0] == [None, None]
    assert pivot.cells[1][0] is None
    assert pivot.row_totals[0] == Decimal(600)
    assert pivot.masked is True


def test_pivot_with_no_small_figures_is_not_masked() -> None:
    rows = _rows("Ачаа", [100, 200, 300])
    spec = LayoutSpec(layout="pivot", by=DEPT, by2=None, value=(PAY, "sum"), chart="bar", month=date(2026, 11, 1))
    pivot = layouts_mod.build_pivot(_table(rows, spec), spec)
    assert pivot.grand == Decimal(600)
    assert pivot.masked is False


def test_summary_of_a_masked_chart_holds_none_and_is_marked() -> None:
    rows = _rows("Ачаа", [100, 200, 300]) + _rows("Санхүү", [100])
    spec = _chart_spec((PAY, "avg"))
    summary = summary_of(_table(rows, spec))
    assert summary is not None
    assert summary.lines[0][1] == 200
    assert summary.lines[1][1] is None
    assert summary.masked is True


def test_summary_of_an_unmasked_chart_is_not_marked() -> None:
    rows = _rows("Ачаа", [100, 200, 300])
    summary = summary_of(_table(rows, _chart_spec((None, "count"))))
    assert summary is not None
    assert summary.masked is False


# --- the screen, the print page and the Excel file (a real staff list) ---

PRINT = "/reports/staff-list/print/"
EXCEL = "/reports/staff-list/excel/"
SCREEN = "/reports/staff-list/?layout=chart&lby=department&lval=salary:avg"
NOTE = "мөртэй бүлгийн мөнгөн дүнг нуусан"


@pytest.fixture
def staff(actor: User, job_values: dict[str, Any]) -> list[Employee]:
    """Two people in Санхүү and one in Ачаа, each on the same salary, so Ачаа's average is one person's pay."""
    people = []
    for register_no, dept, pos in [
        ("УБ70000011", "Санхүү", "Нягтлан"),
        ("УБ70000012", "Санхүү", "Инженер"),
        ("УБ70000013", "Ачаа", "Нягтлан"),
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


@pytest.mark.django_db
def test_screen_chart_shows_the_note_for_a_one_person_department(
    client: Client, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    login_as(client, "Admin")
    page = client.get(SCREEN).content.decode()
    assert NOTE in page


@pytest.mark.django_db
def test_screen_chart_has_no_note_when_the_setting_is_one(
    client: Client, login_as: Callable[..., User], staff: list[Employee], settings: Any
) -> None:
    settings.REPORTS_MIN_GROUP = 1
    login_as(client, "Admin")
    page = client.get(SCREEN).content.decode()
    assert NOTE not in page


@pytest.mark.django_db
def test_print_page_shows_the_note_under_the_summary(
    client: Client, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    login_as(client, "Admin")
    page = client.get(f"{PRINT}?layout=chart&lby=department&lval=salary:avg").content.decode()
    assert NOTE in page
    assert page.index(NOTE) < page.index("<table>")  # the note sits with the summary, above the row table


@pytest.mark.django_db
def test_excel_summary_writes_the_note_under_its_last_row(
    client: Client, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    login_as(client, "Admin")
    resp = client.get(f"{EXCEL}?layout=chart&lby=department&lval=salary:avg")
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    ws: Any = wb["Нэгтгэл"]
    # the summary has two categories (rows 4 and 5); the note is the row after them
    assert ws["B4"].value is None
    assert NOTE in ws["A6"].value
