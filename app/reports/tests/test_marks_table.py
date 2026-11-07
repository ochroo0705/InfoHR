"""Conditional colours and pinned columns on the table: the colour of each cell, the sticky headers and cells, the print
page, and the built CSS."""

import re
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from reports.filters import Filters, parse_filters
from reports.marks import COLOURS
from reports.registry import REPORTS
from reports.table import build_table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "marks-table-test"
PAGE = f"/reports/{KEY}/"
AMBER = COLOURS["amber"]  # "bg-amber-50 text-amber-800"
AMBER_OVER_30 = '[{"c":"age","o":"gte","v":"30","k":"amber"}]'
SALARY_RED = '[{"c":"salary","o":"gte","v":"800","k":"red"}]'
PEOPLE = [("Бат", 25, 800), ("Дорж", 30, 900), ("Сараа", 41, 700), ("Номин", 18, 500)]
HTMX = {"HX-Request": "true"}
TABLE = re.compile(r'<div class="ptable">.*?</table>', re.DOTALL)
CSS = Path(__file__).resolve().parents[2] / "static" / "css" / "app.css"


@pytest.fixture
def marks_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = Report(
        key=KEY,
        title="Өнгийн тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="age", label="Нас", value=lambda r: r.age, numeric=True),
            Column(
                key="salary",
                label="Цалин",
                value=lambda r: r.salary,
                needs="macs.view_salary",
                numeric=True,
                money=True,
            ),
        ),
        default_columns=("name", "age", "salary"),
        rows=lambda user, filters: [SimpleNamespace(name=n, age=a, salary=s) for n, a, s in PEOPLE],
        group_options=("name",),  # one group per person, for the grouped pin test
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _filters(cols: str = "", **params: str) -> Filters:
    """The address as the page reads it: `cols` is a comma list, one repeated key per column."""
    pairs = [("cols", c) for c in cols.split(",")] if cols else []
    pairs += list(params.items())
    return parse_filters(QueryDict(urlencode(pairs)))


def _table_html(page: str) -> str:
    match = TABLE.search(page)
    assert match is not None
    return match.group(0)


def _body_row(page: str, name: str) -> str:
    rows: list[str] = re.findall(r"<tr>.*?</tr>", _table_html(page), re.DOTALL)
    found = [row for row in rows if f">{name}</td>" in row]
    assert len(found) == 1
    return found[0]


def _td_tags(row: str) -> list[str]:
    return re.findall(r"<td[^>]*>", row)


# ---- the colour of each cell ----


def test_amber_mark_colours_only_the_matching_cells(marks_report: Report, accountant_user: User) -> None:
    table = build_table(marks_report, accountant_user, _filters("name,age", marks=AMBER_OVER_30))
    by_name = {row[0].value: row for row in table.groups[0][1]}
    assert by_name["Дорж"][1].mark == AMBER
    assert by_name["Сараа"][1].mark == AMBER
    assert by_name["Бат"][1].mark == ""
    assert by_name["Номин"][1].mark == ""
    assert by_name["Дорж"][0].mark == ""  # the name column has no mark


def test_amber_mark_puts_the_classes_on_the_matching_td_only(
    client: Client, login_as: Callable[..., User], marks_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"cols": ["name", "age"], "marks": AMBER_OVER_30}).content.decode()
    assert _td_tags(_body_row(page, "Дорж"))[1] == f'<td class="text-right {AMBER}">'
    assert _td_tags(_body_row(page, "Сараа"))[1] == f'<td class="text-right {AMBER}">'
    assert _td_tags(_body_row(page, "Бат"))[1] == '<td class="text-right">'
    assert AMBER not in _body_row(page, "Бат")


def test_mark_on_a_salary_the_user_may_not_see_never_colours(marks_report: Report, hr_user: User) -> None:
    table = build_table(marks_report, hr_user, _filters("", marks=SALARY_RED))
    assert all(cell.mark == "" for row in table.groups[0][1] for cell in row)
    assert "salary" not in table.filters.marks


def test_hidden_salary_mark_is_absent_from_the_page(
    client: Client, login_as: Callable[..., User], marks_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"cols": ["name", "salary"], "marks": SALARY_RED}).content.decode()
    assert "bg-red-50" not in _table_html(page)


def test_mark_on_an_unshown_column_colours_nothing(
    client: Client, login_as: Callable[..., User], marks_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"cols": ["name"], "marks": AMBER_OVER_30}).content.decode()
    assert "bg-amber-50" not in _table_html(page)


# ---- pinned columns ----


def test_pin_two_makes_the_first_two_columns_sticky(
    client: Client, login_as: Callable[..., User], marks_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"cols": ["name", "age", "salary"], "pin": "2"}).content.decode()
    heads = re.findall(r"<th[ >][^>]*>", _table_html(page))
    assert len(heads) == 3
    assert "sticky" in heads[0] and 'style="left: 0rem"' in heads[0]
    assert "sticky" in heads[1] and 'style="left: 12rem"' in heads[1]
    assert "sticky" not in heads[2] and "style=" not in heads[2]
    tags = _td_tags(_body_row(page, "Дорж"))
    assert "sticky" in tags[0] and 'style="left: 0rem"' in tags[0]
    assert "sticky" in tags[1] and 'style="left: 12rem"' in tags[1]
    assert "sticky" not in tags[2] and "style=" not in tags[2]


def test_pin_three_with_two_shown_columns_pins_two(
    client: Client, login_as: Callable[..., User], marks_report: Report, accountant_user: User
) -> None:
    assert build_table(marks_report, accountant_user, _filters("name,age", pin="3")).pin == 2
    login_as(client, "Accountant")
    page = client.get(PAGE, {"cols": ["name", "age"], "pin": "3"}).content.decode()
    assert len(re.findall(r"<th [^>]*sticky", _table_html(page))) == 2
    assert "left: 24rem" not in page


def test_pin_99_in_the_address_is_no_pin(
    client: Client, login_as: Callable[..., User], marks_report: Report, accountant_user: User
) -> None:
    assert build_table(marks_report, accountant_user, _filters("name,age", pin="99")).pin == 0
    login_as(client, "Accountant")
    page = client.get(PAGE, {"cols": ["name", "age"], "pin": "99"}).content.decode()
    assert "sticky" not in _table_html(page)


# ---- print and the built CSS ----


def test_print_keeps_mark_classes_and_never_pins(
    client: Client, login_as: Callable[..., User], marks_report: Report
) -> None:
    login_as(client, "Accountant")
    url = reverse("reports:print", args=[KEY])
    page = client.get(url, {"cols": ["name", "age"], "marks": AMBER_OVER_30, "pin": "2"}).content.decode()
    assert f'<td class="text-right {AMBER}">' in page
    assert "sticky" not in page
    assert "left: 0rem" not in page


def test_built_css_has_the_colour_and_sticky_classes() -> None:
    css = CSS.read_text(encoding="utf-8")
    for colour in COLOURS.values():
        for cls in colour.split():
            assert f".{cls}" in css, cls
    assert ".sticky" in css
    assert r".min-w-\[12rem\]" in css


# ---- the batch fragment, footer and grouped table keep the marks and the pinning ----


def test_batch_fragment_keeps_marks_and_sticky_styles(
    client: Client, login_as: Callable[..., User], marks_report: Report
) -> None:
    login_as(client, "Accountant")
    # offset 2 of the four people: the htmx batch fragment (_batch_rows.html, then _rows.html) with Сараа and Номин
    params = {"cols": ["name", "age"], "marks": AMBER_OVER_30, "pin": "2", "offset": "2"}
    fragment = client.get(PAGE, params, headers=HTMX).content.decode()
    rows = re.findall(r"<tr>.*?</tr>", fragment, re.DOTALL)
    saraa = [row for row in rows if ">Сараа</td>" in row]
    assert len(saraa) == 1
    tags = _td_tags(saraa[0])
    assert "sticky" in tags[0] and 'style="left: 0rem"' in tags[0]
    assert "sticky" in tags[1] and 'style="left: 12rem"' in tags[1]
    assert AMBER in tags[1]  # Сараа is 41: the amber rule passes
    assert "bg-surface" not in tags[1]  # a coloured pinned cell keeps its colour background
    nomin = [row for row in rows if ">Номин</td>" in row]
    assert len(nomin) == 1 and AMBER not in _td_tags(nomin[0])[1]


def test_pinned_footer_cells_carry_the_sticky_style(
    client: Client, login_as: Callable[..., User], marks_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"cols": ["name", "age"], "pin": "2", "totals": "age:sum"}).content.decode()
    footer = re.search(r"<tfoot>.*?</tfoot>", page, re.DOTALL)
    assert footer is not None
    tags = _td_tags(footer.group(0))
    assert len(tags) == 2
    assert "sticky" in tags[0] and 'style="left: 0rem"' in tags[0]
    assert "sticky" in tags[1] and 'style="left: 12rem"' in tags[1]


def test_footer_beyond_the_pin_is_not_sticky(
    client: Client, login_as: Callable[..., User], marks_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"cols": ["name", "age", "salary"], "pin": "1", "totals": "salary:sum"}).content.decode()
    footer = re.search(r"<tfoot>.*?</tfoot>", page, re.DOTALL)
    assert footer is not None
    tags = _td_tags(footer.group(0))
    assert "sticky" in tags[0]
    assert "sticky" not in tags[1] and "sticky" not in tags[2]


def test_pin_with_a_grouped_table_pins_the_group_rows_and_not_the_headings(
    client: Client, login_as: Callable[..., User], marks_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"cols": ["name", "age"], "pin": "2", "group": "name"}).content.decode()
    row = _body_row(page, "Дорж")
    tags = _td_tags(row)
    assert "sticky" in tags[0] and 'style="left: 0rem"' in tags[0]
    assert "sticky" in tags[1] and 'style="left: 12rem"' in tags[1]
    heading = re.search(r"<tr><td colspan[^>]*>Дорж · 1</td></tr>", _table_html(page))
    assert heading is not None  # the group heading spans the table and is not pinned
    assert "sticky" not in heading.group(0)
