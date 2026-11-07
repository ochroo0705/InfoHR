"""build_table keeps the filtered raw rows and loads the columns the chosen layout draws with."""

from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict

from reports.filters import parse_filters
from reports.registry import REPORTS
from reports.table import build_table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "layout-rows-test"


@pytest.fixture
def recorded() -> list[tuple[str, ...]]:
    """The column keys each call to the report's rows callable was asked to load."""
    return []


@pytest.fixture
def layout_report(monkeypatch: pytest.MonkeyPatch, recorded: list[tuple[str, ...]]) -> Report:
    people = [
        SimpleNamespace(name="Б", dept="Санхүү"),
        SimpleNamespace(name="А", dept="Бүтээгдэхүүн"),
        SimpleNamespace(name="В", dept="Санхүү"),
    ]

    def rows(user: User, filters: Any) -> list[Any]:
        recorded.append(tuple(filters.columns))
        return list(people)

    report = Report(
        key=KEY,
        title="Тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
        ),
        default_columns=("name",),
        rows=rows,
        group_options=("dept",),
        layouts=("board",),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def test_board_loads_the_category_column_though_only_name_is_shown(
    layout_report: Report, accountant_user: User, recorded: list[tuple[str, ...]]
) -> None:
    table = build_table(layout_report, accountant_user, parse_filters(QueryDict("layout=board&lby=dept")))
    assert table.spec.layout == "board"
    assert table.spec.by is not None and table.spec.by.key == "dept"
    assert [c.key for c in table.columns] == ["name"]
    assert "dept" in recorded[-1]


def test_table_keeps_every_filtered_row_in_rows(layout_report: Report, accountant_user: User) -> None:
    table = build_table(layout_report, accountant_user, parse_filters(QueryDict("layout=board&lby=dept")))
    assert len(table.rows) == table.count == 3
    assert [r.name for r in table.rows] == ["Б", "А", "В"]  # the report's order, as the table has it without a sort


def test_untyped_numeric_value_column_is_summed_from_the_loaded_values(
    monkeypatch: pytest.MonkeyPatch, accountant_user: User, recorded: list[tuple[str, ...]]
) -> None:
    """score has plain ints and no numeric flag: its kind is read from the loaded rows, so sum is allowed."""
    people = [SimpleNamespace(dept="Санхүү", score=4), SimpleNamespace(dept="Бүтээгдэхүүн", score=6)]

    def rows(user: User, filters: Any) -> list[Any]:
        recorded.append(tuple(filters.columns))
        return list(people)

    report = Report(
        key=KEY,
        title="Тайлан",
        filters=(),
        columns=(
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
            Column(key="score", label="Оноо", value=lambda r: r.score),
        ),
        default_columns=("dept",),
        rows=rows,
        group_options=("dept",),
        layouts=("chart",),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    table = build_table(report, accountant_user, parse_filters(QueryDict("layout=chart&lby=dept&lval=score:sum")))
    assert table.spec.value is not None
    assert table.spec.value[0] is not None and table.spec.value[0].key == "score"
    assert table.spec.value[1] == "sum"
    assert "score" in recorded[-1]


def test_without_a_layout_the_load_is_the_shown_columns_only(
    layout_report: Report, accountant_user: User, recorded: list[tuple[str, ...]]
) -> None:
    table = build_table(layout_report, accountant_user, parse_filters(QueryDict("")))
    assert table.spec.layout == "table"
    assert recorded[-1] == ("name",)
    assert [c.key for c in table.columns] == ["name"]


@pytest.fixture
def salary_report(monkeypatch: pytest.MonkeyPatch, recorded: list[tuple[str, ...]]) -> Report:
    """A report whose pay column needs macs.view_salary; dept is the category, pay is a number."""
    people = [
        SimpleNamespace(name="Б", dept="Санхүү", pay=100),
        SimpleNamespace(name="А", dept="Бүтээгдэхүүн", pay=250),
    ]

    def rows(user: User, filters: Any) -> list[Any]:
        recorded.append(tuple(filters.columns))
        return list(people)

    report = Report(
        key=KEY,
        title="Тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
            Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary", numeric=True),
        ),
        default_columns=("name",),
        rows=rows,
        group_options=("dept",),
        layouts=("board", "chart"),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


@pytest.mark.parametrize("raw", ["layout=chart&lby=pay&lval=pay:sum", "layout=board&lby=pay"])
def test_a_viewer_without_salary_never_loads_or_uses_pay(
    salary_report: Report, hr_user: User, recorded: list[tuple[str, ...]], raw: str
) -> None:
    table = build_table(salary_report, hr_user, parse_filters(QueryDict(raw)))
    assert "pay" not in recorded[-1]
    assert table.spec.by is None or table.spec.by.key != "pay"
    assert table.spec.value[0] is None
    assert table.spec.by2 is None or table.spec.by2.key != "pay"


def test_a_viewer_with_salary_loads_pay_for_the_sum(
    salary_report: Report, accountant_user: User, recorded: list[tuple[str, ...]]
) -> None:
    table = build_table(salary_report, accountant_user, parse_filters(QueryDict("layout=chart&lby=dept&lval=pay:sum")))
    assert "pay" in recorded[-1]
    assert table.spec.value[0] is not None and table.spec.value[0].key == "pay"
    assert table.spec.value[1] == "sum"
