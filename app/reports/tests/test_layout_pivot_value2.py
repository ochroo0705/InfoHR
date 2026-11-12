"""The pivot's second value (lval2): a second grid under the first with the same rows, columns and drill links, its own
caption, the money rule for small groups, a hidden column dropped, the percent on the first value only, and the layout
bar's «Утга 2» select."""

import re
from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from employees.templatetags.hr import mnt

from reports import layouts as layouts_mod
from reports.filters import Filters, parse_filters
from reports.layouts import LayoutSpec, resolve, used_params
from reports.registry import REPORTS
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "layout-pivot-value2-test"
PAGE = f"/reports/{KEY}/"
SECRET_VALUE = 99999  # numeric, needs x.y: a viewer without x.y must never see it
GRID = re.compile(r'<div class="ptable')
CAPTION = re.compile(r"<caption[^>]*>(.*?)</caption>", re.S)
PAY_SUM = f"Цалин ({layouts_mod.AGG_TEXT['sum']})"
COUNT = layouts_mod.AGG_TEXT["count"]

NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
LEVEL = Column(key="level", label="Түвшин", value=lambda r: r.level, kind="text")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary", numeric=True, money=True)
SECRET = Column(key="secret", label="Нууц", value=lambda r: r.secret, needs="x.y", kind="number", numeric=True)


def _people() -> list[Any]:
    """Санхүү: four at level A (pay 1000 to 4000, sum 10000). Ачаа: two rows (5000 at A, 6000 at B), so its figures
    are under the minimum group of 3 and masked. Two columns, A and B."""
    rows = [
        ("Бат", "Санхүү", "A", 1000),
        ("Дорж", "Санхүү", "A", 2000),
        ("Оюу", "Санхүү", "A", 3000),
        ("Номин", "Санхүү", "A", 4000),
        ("Төмөр", "Ачаа", "A", 5000),
        ("Сараа", "Ачаа", "B", 6000),
    ]
    return [SimpleNamespace(name=n, dept=d, level=lv, pay=p, secret=SECRET_VALUE) for n, d, lv, p in rows]


@pytest.fixture
def value2_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = Report(
        key=KEY,
        title="Ажилтны тайлан",
        filters=(),
        columns=(NAME, DEPT, LEVEL, PAY, SECRET),
        default_columns=("name", "dept"),
        rows=lambda user, filters: _people(),
        group_options=("dept", "level"),
        layouts=("pivot",),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _grids(page: str) -> list[str]:
    """Each pivot grid's markup, up to its table's end (the masked note and the rest of the page are not in it)."""
    return [chunk.split("</table>")[0] for chunk in GRID.split(page)[1:]]


def _captions(page: str) -> list[str]:
    return [m.group(1) for m in CAPTION.finditer(page)]


def _row_labels(grid: str) -> list[str]:
    return [label for label in re.findall(r'<th scope="row">(?:<a [^>]*>)?([^<]*)', grid) if label != "Дүн"]


def _row_links(grid: str) -> list[str]:
    return re.findall(r'<th scope="row"><a href="([^"]*)"', grid)


def _col_heads(grid: str) -> list[str]:
    heads = re.findall(r'<th scope="col" class="text-right">(?:<a [^>]*>)?([^<]*)', grid)
    return [head for head in heads if head != "Дүн"]  # the last head is the row total column


def _layout_bar(page: str) -> str:
    """The layout bar's own form (aria-label «Харагдацын багана»), from its <form> tag to its </form>."""
    marker = page.index('aria-label="Харагдацын багана"')
    start = page.rfind("<form", 0, marker)
    return page[start : page.index("</form>", marker) + len("</form>")]


def _foot(grid: str) -> str:
    match = re.search(r"<tfoot>(.*?)</tfoot>", grid, re.S)
    assert match is not None
    return match.group(1)


def _parse(raw: str) -> Filters:
    return parse_filters(QueryDict(raw))


# ---- the pages ----


def test_second_grid_has_same_rows_and_columns(
    client: Client, login_as: Callable[..., User], value2_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lby2": "level", "lval2": "pay:sum"}).content.decode()
    first, second = _grids(page)
    assert _captions(page) == [COUNT, PAY_SUM]
    assert _row_labels(first) == ["Ачаа", "Санхүү"] == _row_labels(second)
    assert _col_heads(first) == ["A", "B"] == _col_heads(second)
    assert _row_links(first) == _row_links(second)
    assert len(_row_links(first)) == 2  # the drill links are there in both grids
    assert "<td" in second and mnt(10000) in second  # the second grid holds the money sums


def test_second_value_money_is_masked_for_small_groups(
    client: Client, login_as: Callable[..., User], value2_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lby2": "level", "lval2": "pay:sum"}).content.decode()
    second = _grids(page)[1]
    assert f">{mnt(10000)}<" in second  # Санхүү/A: four rows, shown
    for hidden in (11000, 5000, 6000):  # Ачаа's total (2 rows), and its two cells (1 row each)
        assert f">{mnt(hidden)}<" not in page  # a whole cell: 5 000 also sits inside a column total of 15 000
    assert "нуусан" in page  # the masked note under the second grid
    assert "—" in second  # the masked figures and the empty Санхүү/B cell


def test_value2_with_hidden_column_is_dropped(
    client: Client, login_as: Callable[..., User], value2_report: Report
) -> None:
    login_as(client, "HR")  # no x.y: the second value's column is hidden
    page = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lval2": "secret:sum"}).content.decode()
    assert len(_grids(page)) == 1
    assert str(SECRET_VALUE) not in page
    assert mnt(SECRET_VALUE) not in page


def test_no_value2_renders_one_grid(client: Client, login_as: Callable[..., User], value2_report: Report) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lval": "pay:sum"}).content.decode()
    assert _captions(page) == [PAY_SUM]
    assert len(_grids(page)) == 1


def test_identical_second_value_gives_no_second_grid(
    client: Client, login_as: Callable[..., User], value2_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lval": "pay:sum", "lval2": "pay:sum"}).content.decode()
    assert _captions(page) == [PAY_SUM]


def test_lval2_count_gives_a_count_grid(client: Client, login_as: Callable[..., User], value2_report: Report) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lval": "pay:sum", "lval2": "count"}).content.decode()
    assert _captions(page) == [PAY_SUM, COUNT]
    second = _grids(page)[1]
    assert ">6<" in _foot(second)  # six people in all: the count of rows, not a money sum


def test_percent_applies_to_the_first_value_only(
    client: Client, login_as: Callable[..., User], value2_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(
        PAGE, {"layout": "pivot", "lby": "dept", "lval": "count", "lshow": "pct", "lval2": "pay:sum"}
    ).content.decode()
    first_caption, second_caption = _captions(page)
    assert first_caption.endswith("(%)")
    assert "%" not in second_caption
    assert mnt(10000) in _grids(page)[1]  # the second value is the plain money sum


def test_layout_bar_has_the_second_value_select(
    client: Client, login_as: Callable[..., User], value2_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"layout": "pivot", "lby": "dept", "lval2": "pay:sum"}).content.decode()
    assert '<select name="lval2"' in page
    assert '<option value="">—</option>' in page
    assert '<option value="pay:sum" selected>' in page
    bar = _layout_bar(page)
    assert '<select name="lval2"' in bar  # the select is in the layout bar's own form
    assert 'type="hidden" name="lval2"' not in bar  # the bar does not emit lval2 as a hidden input
    # the filter form (another form on the page) carries lval2 as a hidden input: Task 8b's filter carry
    rest = page.replace(bar, "")
    assert '<input type="hidden" name="lval2" value="pay:sum">' in rest


# ---- the parameter ----


def test_resolve_keeps_a_valid_second_value_and_drops_the_rest(hr_user: User, accountant_user: User) -> None:
    report = Report(
        key=KEY,
        title="Тайлан",
        filters=(),
        columns=(NAME, DEPT, LEVEL, PAY, SECRET),
        default_columns=("name",),
        rows=lambda user, filters: [],
        group_options=("dept", "level"),
        layouts=("pivot",),
    )
    rows = _people()
    assert resolve(report, hr_user, _parse("layout=pivot&lby=dept")).value2 is None
    assert resolve(report, hr_user, _parse("layout=pivot&lby=dept&lval2=secret:sum")).value2 is None  # hidden
    assert resolve(report, hr_user, _parse("layout=pivot&lby=dept&lval2=bogus")).value2 is None
    # a column first value with count as the second: a count grid
    counted = resolve(report, accountant_user, _parse("layout=pivot&lby=dept&lval=pay:sum&lval2=count"), rows)
    assert counted.value2 == (None, "count")
    assert counted.value == (PAY, "sum")
    # identical to the first value (here both are count): no second grid
    same = resolve(report, accountant_user, _parse("layout=pivot&lby=dept&lval=count&lval2=count"), rows)
    assert same.value2 is None


def test_value2_is_written_for_the_pivot_only() -> None:
    spec = LayoutSpec(
        layout="pivot",
        by=DEPT,
        by2=None,
        value=(None, "count"),
        chart="bar",
        month=date(2026, 11, 1),
        value2=(PAY, "sum"),
    )
    assert used_params(Filters(layout="pivot"), spec).lval2 == "pay:sum"
    no_second = LayoutSpec(
        layout="pivot", by=DEPT, by2=None, value=(None, "count"), chart="bar", month=date(2026, 11, 1)
    )
    assert used_params(Filters(layout="pivot"), no_second).lval2 == ""
    chart = LayoutSpec(
        layout="chart",
        by=DEPT,
        by2=None,
        value=(None, "count"),
        chart="bar",
        month=date(2026, 11, 1),
        value2=(PAY, "sum"),
    )
    assert used_params(Filters(layout="chart"), chart).lval2 == ""
