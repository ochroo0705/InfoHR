"""The chart and pivot pages: the data table, the chart's JSON, the pivot totals, the empty text, the lazy Plotly
load, and the per-viewer rules."""

import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.templatetags.hr import mnt

from reports.registry import REPORTS
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

APP = Path(__file__).resolve().parents[2]  # the app/ folder
KEY = "layout-views-c-test"
PAGE = f"/reports/{KEY}/"
ROWS = 75
DEPTS = ("Санхүү", "Ачаа", None)
SALARY = 8765432  # the value a viewer without macs.view_salary must never see
CHART_JSON = re.compile(r'<script id="report-chart-data" type="application/json">(.*?)</script>', re.S)


def _people() -> list[Any]:
    return [
        SimpleNamespace(name=f"Ажилтан {n:02d}", dept=DEPTS[n % 3], start=None, pay=SALARY + n)
        for n in range(1, ROWS + 1)
    ]


@pytest.fixture
def views_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = Report(
        key=KEY,
        title="Ажилтны тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
            Column(
                key="pay",
                label="Цалин",
                value=lambda r: r.pay,
                needs="macs.view_salary",
                numeric=True,
                money=True,
                kind="number",
            ),
        ),
        default_columns=("name", "dept"),
        rows=lambda user, filters: _people(),
        group_options=("dept",),
        layouts=("chart", "pivot"),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _chart_data(page: str) -> dict[str, Any]:
    match = CHART_JSON.search(page)
    assert match is not None, "no report-chart-data script"
    data: dict[str, Any] = json.loads(match.group(1))
    return data


def _assert_no_pay(page: str) -> None:
    """No salary of any row shows in the page, raw or as the mnt filter formats it, and no «Цалин» label."""
    for person in _people():
        assert str(person.pay) not in page
        assert mnt(person.pay) not in page
    assert "Цалин" not in page


# ---- the chart ----


def test_chart_page_has_the_data_table_and_the_numbers_as_json(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "chart", "lby": "dept"}).content.decode()
    data = _chart_data(page)
    assert data["kind"] == "bar"
    assert data["labels"] == ["Ачаа", "Санхүү", "—"]  # the blank category is last and shown as «—»
    assert data["values"] == [25.0, 25.0, 25.0]
    # the same numbers in a plain table under the chart
    assert "Ачаа" in page and "Санхүү" in page
    assert re.search(r"<td[^>]*>25</td>", page)


def test_chart_donut_and_line_kinds_reach_the_json(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    donut = client.get(PAGE, {"layout": "chart", "lby": "dept", "lchart": "donut"}).content.decode()
    assert _chart_data(donut)["kind"] == "donut"
    assert 'data-kind="donut"' in donut
    line = client.get(PAGE, {"layout": "chart", "lby": "dept", "lchart": "line"}).content.decode()
    assert _chart_data(line)["kind"] == "line"
    assert 'data-kind="line"' in line


def test_chart_money_sum_is_in_the_table_and_the_json(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"layout": "chart", "lby": "dept", "lval": "pay:sum"}).content.decode()
    total = sum(p.pay for p in _people() if p.dept == "Санхүү")
    assert mnt(total) in page  # the table shows the money format
    data = _chart_data(page)
    assert data["money"] is True
    assert data["values"][data["labels"].index("Санхүү")] == float(total)


def test_chart_loads_plotly_only_through_the_data_attribute(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "chart", "lby": "dept"}).content.decode()
    assert re.search(r"<script[^>]*plotly", page) is None  # no Plotly <script> in the page
    assert "data-report-chart" in page
    assert 'data-plotly-src="' in page and "vendor/plotly/plotly-basic.min.js" in page
    assert 'role="img"' in page


# ---- the static files ----


def test_report_chart_script_exists_and_base_loads_it_once() -> None:
    assert (APP / "static" / "js" / "report_chart.js").is_file()
    base = (APP / "templates" / "base.html").read_text(encoding="utf-8")
    assert base.count("js/report_chart.js") == 1


def test_plotly_file_is_named_only_in_a_data_attribute() -> None:
    """The Plotly file is loaded by report_chart.js on first use, never by a <script> in a template or in base.html."""
    files = list((APP / "reports" / "templates").glob("**/*.html")) + [APP / "static" / "js" / "report_chart.js"]
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "plotly-basic" in line:
                assert "data-plotly-src=" in line, f"{path}: {line.strip()}"
    assert "plotly-basic" not in (APP / "templates" / "base.html").read_text(encoding="utf-8")


def test_chart_with_no_rows_shows_the_empty_text(
    client: Client, login_as: Callable[..., User], views_report: Report, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(REPORTS, KEY, replace(views_report, rows=lambda user, filters: []))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "chart", "lby": "dept"}).content.decode()
    assert "Өгөгдөл олдсонгүй" in page
    assert "report-chart-data" not in page


# ---- the pivot ----


def test_pivot_has_the_total_column_and_row_and_the_grand_total(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "pivot", "lby": "dept"}).content.decode()
    assert re.search(r'<th scope="col"[^>]*>Дүн</th>', page)  # the total column header
    assert '<th scope="row">Дүн</th>' in page  # the total row label
    foot = re.search(r"<tfoot>(.*?)</tfoot>", page, re.S)
    assert foot is not None
    assert ">75<" in foot.group(1)  # the grand total is the filtered count


def test_pivot_grand_total_is_the_money_sum(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lval": "pay:sum"}).content.decode()
    foot = re.search(r"<tfoot>(.*?)</tfoot>", page, re.S)
    assert foot is not None
    assert mnt(sum(p.pay for p in _people())) in foot.group(1)


def test_pivot_with_the_same_column_as_row_is_still_200(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lby2": "dept"})
    assert response.status_code == 200
    assert "Өгөгдөл олдсонгүй" not in response.content.decode()


def test_pivot_with_no_rows_shows_the_empty_text(
    client: Client, login_as: Callable[..., User], views_report: Report, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(REPORTS, KEY, replace(views_report, rows=lambda user, filters: []))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "pivot", "lby": "dept"}).content.decode()
    assert "Өгөгдөл олдсонгүй" in page
    assert re.search(r'<th scope="col"[^>]*>Дүн</th>', page) is None


# ---- the per-viewer rules ----


@pytest.mark.parametrize("layout", ["chart", "pivot"])
def test_hidden_salary_in_every_key_gives_no_salary_and_no_pay_option(
    client: Client, login_as: Callable[..., User], views_report: Report, layout: str
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": layout, "lby": "pay", "lby2": "pay", "lval": "pay:sum"})
    assert response.status_code == 200
    page = response.content.decode()
    _assert_no_pay(page)
    assert not re.search(r"\bpay\b", page)  # the layout bar offers no pay option either


# ---- hostile text: a category or a title with markup never reaches the page raw ----

HOSTILE = "<script>alert(1)</script>\"x' & </script>"


@pytest.fixture
def hostile_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    rows = [
        SimpleNamespace(name=HOSTILE, dept=HOSTILE, start=date(2026, 3, 15), end=date(2026, 3, 20), pay=1),
        SimpleNamespace(name="Ок", dept="Ок", start=date(2026, 3, 16), end=None, pay=2),
    ]
    report = Report(
        key=KEY,
        title="Ажилтны тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
            Column(key="start", label="Эхэлсэн", value=lambda r: r.start, kind="date"),
            Column(key="end", label="Дууссан", value=lambda r: r.end, kind="date"),
        ),
        default_columns=("name", "dept"),
        rows=lambda user, filters: rows,
        group_options=("dept",),
        layouts=("chart", "pivot", "calendar", "timeline"),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


@pytest.mark.parametrize(
    "params",
    [
        {"layout": "chart", "lby": "dept"},
        {"layout": "pivot", "lby": "dept"},
        {"layout": "calendar", "lby": "start"},
        {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"},
    ],
    ids=["chart", "pivot", "calendar", "timeline"],
)
def test_hostile_text_is_escaped_on_every_page(
    client: Client, login_as: Callable[..., User], hostile_report: Report, params: dict[str, str]
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {**params, "lmonth": "2026-03"})
    assert response.status_code == 200
    page = response.content.decode()
    assert HOSTILE not in page  # the raw string never appears
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;alert(1)" in page  # it is shown as escaped text


def test_chart_json_keeps_the_category_text_for_plotly_to_escape(
    client: Client, login_as: Callable[..., User], hostile_report: Report
) -> None:
    login_as(client, "HR")
    data = _chart_data(client.get(PAGE, {"layout": "chart", "lby": "dept"}).content.decode())
    assert HOSTILE in data["labels"]  # the JSON is data; report_chart.js escapes it before Plotly


def test_report_chart_js_reads_no_css_variables() -> None:
    """Plotly cannot read oklch() values, so the chart colours are hex constants, not page variables."""
    script = (APP / "static" / "js" / "report_chart.js").read_text(encoding="utf-8")
    assert "getPropertyValue" not in script
    assert "getComputedStyle" not in script


def test_timeline_with_only_undated_rows_says_no_data_and_counts_them(
    client: Client, login_as: Callable[..., User], hostile_report: Report, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [SimpleNamespace(name="А", dept="А", start=None, end=None, pay=0) for _ in range(2)]
    monkeypatch.setitem(REPORTS, KEY, replace(hostile_report, rows=lambda user, filters: rows))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}).content.decode()
    assert "Өгөгдөл олдсонгүй" in page
    assert "Огноогүй: 2" in page
    assert "data-bar" not in page


def test_timeline_bars_carry_an_aria_label_with_title_and_dates(
    client: Client, login_as: Callable[..., User], hostile_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "timeline", "lby": "start", "lby2": "end", "lyear": "all"}).content.decode()
    assert 'role="img" aria-label="Ок: 2026-03-16 – 2026-03-16"' in page
