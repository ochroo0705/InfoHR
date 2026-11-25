"""The table layout as a request-free page (reports.services.table_page): the batch, the header cells, the cells as
text, the footer, the rules and note, and the address rules that drop what the viewer may not see."""

import json
from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from accounts.models import User
from config import batching
from django.http import QueryDict

from reports.marks import COLOURS
from reports.registry import REPORTS
from reports.services.table_page import TablePage, parse_offset, table_page
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "table-page-test"
PATH = f"/reports/{KEY}/"
AMBER = COLOURS["amber"]
PEOPLE = [
    SimpleNamespace(name="Бат", dept="Санхүү", age=25, salary=800000, since=date(2020, 1, 5)),
    SimpleNamespace(name="Дорж", dept="Санхүү", age=30, salary=900000, since=None),
    SimpleNamespace(name="Сараа", dept="Борлуулалт", age=41, salary=700000, since=date(2018, 3, 1)),
    SimpleNamespace(name="Номин", dept="Борлуулалт", age=18, salary=500000, since=date(2024, 7, 9)),
]


def _register(
    monkeypatch: pytest.MonkeyPatch,
    people: list[SimpleNamespace] = PEOPLE,
    group_options: tuple[str, ...] = ("dept",),
    column_filters: tuple[str, ...] = (),
    layouts: tuple[str, ...] = (),
) -> Report:
    report = Report(
        key=KEY,
        title="Хүснэгт",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
            Column(key="age", label="Нас", value=lambda r: r.age, numeric=True),
            Column(
                key="salary",
                label="Цалин",
                value=lambda r: r.salary,
                needs="macs.view_salary",
                numeric=True,
                money=True,
            ),
            Column(key="since", label="Огноо", value=lambda r: r.since),
        ),
        default_columns=("name", "age"),
        rows=lambda user, filters: list(people),
        group_options=group_options,
        column_filters=column_filters,
        layouts=layouts,
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


@pytest.fixture
def report(monkeypatch: pytest.MonkeyPatch) -> Report:
    return _register(monkeypatch)


def _page(report: Report, user: User, pairs: list[tuple[str, str]], offset: int = 0) -> TablePage:
    return table_page(QueryDict(urlencode(pairs)), PATH, user, report, offset)


def _names(page: TablePage) -> list[str]:
    return [row[0].text for group in page.groups for row in group.rows]


def _sort_of(address: str) -> list[str]:
    return parse_qs(urlsplit(address).query).get("sort", [""])


def _bar_text(page: TablePage) -> str:
    """The filter bar's text: its ✕ and clear addresses, the picker, the column chips and the option labels."""
    bar = page.bar
    parts = [bar.clear_url, bar.columns_query, bar.options.group_text, *bar.adds]
    parts += [item.name + item.remove for item in bar.items]
    parts += [entry.label + entry.href + entry.heading for entry in bar.picker]
    parts += [chip.name + chip.label + chip.remove_href + " ".join(chip.values) for chip in bar.column_chips]
    parts += [label for _value, label in bar.options.group_choices]
    return " ".join(parts)


def _everything(page: TablePage) -> str:
    """Every text the page would draw or link: used to look for a value that must not appear anywhere."""
    parts = [page.address, page.clear_rules_url, page.rules_text, page.query, page.note, _bar_text(page)]
    parts += [head.label + head.href + head.append_href for head in page.heads]
    parts += [cell.text + cell.css for group in page.groups for row in group.rows for cell in row]
    parts += [cell.text for cell in page.footer or []]
    return " ".join(parts)


def test_not_grouped_returns_first_batch_and_next_offset(
    monkeypatch: pytest.MonkeyPatch, report: Report, accountant_user: User
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    page = _page(report, accountant_user, [("cols", "name"), ("sort", "name")])
    assert _names(page) == ["Бат", "Дорж"]
    assert page.next_offset == 2
    assert page.count == 4
    assert [group.label for group in page.groups] == [""]


def test_second_batch_by_offset_and_none_at_end(
    monkeypatch: pytest.MonkeyPatch, report: Report, accountant_user: User
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    page = _page(report, accountant_user, [("cols", "name"), ("sort", "name")], offset=2)
    assert _names(page) == ["Номин", "Сараа"]
    assert page.next_offset is None


def test_grouped_returns_all_rows_and_no_next_offset(
    monkeypatch: pytest.MonkeyPatch, report: Report, accountant_user: User
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    page = _page(report, accountant_user, [("cols", "name"), ("group", "dept")])
    assert [group.label for group in page.groups] == ["Борлуулалт", "Санхүү"]
    assert [group.count for group in page.groups] == [2, 2]
    assert len(_names(page)) == 4
    assert page.next_offset is None


def test_empty_report_has_zero_count_and_no_rows(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    empty = _register(monkeypatch, people=[])
    page = _page(empty, accountant_user, [("cols", "name")])
    assert page.count == 0
    assert page.footer is None
    assert page.next_offset is None
    assert [(group.label, group.count, group.rows) for group in page.groups] == [("", 0, [])]


def test_heads_carry_sort_links_arrows_and_pinned_offset(report: Report, accountant_user: User) -> None:
    page = _page(report, accountant_user, [("cols", "name"), ("cols", "age"), ("sort", "-age"), ("pin", "1")])
    name_head, age_head = page.heads
    assert name_head.label == "Нэр"
    assert name_head.arrow == ""
    assert name_head.sticky_left == "left: 0rem"
    assert "sticky" in name_head.css
    assert _sort_of(name_head.href) == ["name"]
    assert age_head.arrow == "↓"
    assert age_head.sticky_left == ""
    assert _sort_of(age_head.href) == ["age"]  # a second click reverses the sort
    assert _sort_of(age_head.append_href) == ["age"]  # Shift+click flips the column in place


def test_cell_with_mark_keeps_mark_class_and_pinned_cell_drops_surface_background(
    report: Report, accountant_user: User
) -> None:
    mark = '[{"c":"age","o":"gte","v":"30","k":"amber"}]'
    page = _page(
        report,
        accountant_user,
        [("cols", "name"), ("cols", "age"), ("sort", "name"), ("pin", "1"), ("marks", mark)],
    )
    by_name = {row[0].text: row for row in page.groups[0].rows}
    dorj = by_name["Дорж"]
    assert AMBER in dorj[0].css and "sticky" in dorj[0].css and "bg-surface" not in dorj[0].css
    assert dorj[0].style == "left: 0rem"
    assert AMBER in dorj[1].css and dorj[1].style == ""
    bat = by_name["Бат"]
    assert "bg-surface" in bat[0].css and AMBER not in bat[0].css


def test_unseen_column_in_address_is_dropped_everywhere(
    monkeypatch: pytest.MonkeyPatch, report: Report, hr_user: User
) -> None:
    rules = json.dumps(
        {"op": "and", "items": [{"c": "salary", "o": "gte", "v": "1"}, {"c": "age", "o": "gte", "v": "20"}]}
    )
    page = _page(
        report,
        hr_user,
        [
            ("cols", "name"),
            ("cols", "salary"),
            ("sort", "salary"),
            ("rules", rules),
            ("totals", "salary:sum"),
            ("marks", '[{"c":"salary","o":"gte","v":"1","k":"red"}]'),
            ("pin", "2"),
        ],
    )
    assert [head.label for head in page.heads] == ["Нэр"]
    assert page.footer is None
    assert "Цалин" not in page.rules_text
    text = _everything(page)
    assert "Цалин" not in text and "800000" not in text and "900000" not in text
    assert "salary" not in page.query and "salary" not in page.address
    assert "salary" not in page.filters.sort and "salary" not in page.filters.rules

    # a column filter on the unseen column and a group naming it: no chip, no pick, no group, no value
    rich = _register(monkeypatch, group_options=("dept", "salary"), column_filters=("salary",))
    hidden = _page(
        rich,
        hr_user,
        [("cols", "name"), ("group", "salary"), ("salary_from", "1000"), ("add", "salary"), ("sort", "name")],
    )
    assert [group.label for group in hidden.groups] == [""]  # the group names no column the user sees
    assert hidden.filters.group == ""
    assert hidden.bar.column_chips == [] and "salary" not in hidden.bar.adds
    assert "salary" not in [entry.label for entry in hidden.bar.picker]
    assert "salary_from" not in hidden.query and "salary_from" not in hidden.address
    text = _everything(hidden)
    assert "Цалин" not in text and "salary" not in text and "800000" not in text


def test_junk_filters_are_cleaned(report: Report, accountant_user: User) -> None:
    page = _page(
        report,
        accountant_user,
        [("cols", "name"), ("cols", "age"), ("sort", ",,-"), ("pin", "99"), ("q", "x" * 10000)],
    )
    assert page.filters.sort == ""
    assert page.pin == 0
    assert page.count == 0
    assert page.filters.q == "x" * 200  # the search is cut to 200 characters, as the address reads it
    assert "x" * 201 not in page.query
    assert page.footer is None
    five = _page(report, accountant_user, [("cols", "name"), ("sort", "name,dept,age,since,salary")])
    assert five.filters.sort == "name,dept,age,since,salary"  # five keys: all kept, the unshown ones sort too
    assert len(_names(five)) == 4
    six = _page(report, accountant_user, [("cols", "name"), ("sort", "name,dept,age,since,salary,-name")])
    assert six.filters.sort == ""  # more than five parts: the parser drops the whole sort, nothing fails
    assert len(_names(six)) == 4


def test_money_cell_flags_money(report: Report, accountant_user: User) -> None:
    page = _page(report, accountant_user, [("cols", "name"), ("cols", "salary"), ("sort", "name")])
    bat = page.groups[0].rows[0]
    assert bat[1].money is True
    assert bat[1].value == "800000"
    assert bat[1].text == "800000"
    assert bat[0].money is False
    assert bat[0].value == "Бат"


def test_dates_are_iso_and_none_is_blank(report: Report, accountant_user: User) -> None:
    page = _page(report, accountant_user, [("cols", "name"), ("cols", "since"), ("sort", "name")])
    by_name = {row[0].text: row for row in page.groups[0].rows}
    assert by_name["Бат"][1].text == "2020-01-05"
    assert by_name["Дорж"][1].value is None
    assert by_name["Дорж"][1].text == ""


def test_footer_cells_match_table_footer(report: Report, accountant_user: User) -> None:
    page = _page(report, accountant_user, [("cols", "name"), ("cols", "salary"), ("totals", "salary:sum")])
    assert page.footer is not None
    assert [cell.text for cell in page.footer] == ["Дүн", "2900000"]
    assert page.footer[1].money is True
    assert page.footer[1].value == "2900000"
    assert page.footer[0].money is False
    no_totals = _page(report, accountant_user, [("cols", "name"), ("cols", "salary")])
    assert no_totals.footer is None


def test_bad_offset_starts_at_zero(monkeypatch: pytest.MonkeyPatch, report: Report, accountant_user: User) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    for raw in ("-5", "²", "9" * 20, ""):
        assert parse_offset(raw) == 0
    assert parse_offset("2") == 2
    for offset in (-5, 10**20):
        page = _page(report, accountant_user, [("cols", "name"), ("sort", "name")], offset=offset)
        assert _names(page) == ["Бат", "Дорж"]
        assert page.next_offset == 2


def test_non_table_layout_converts_no_rows(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    report = _register(monkeypatch, layouts=("cards",))
    page = _page(report, accountant_user, [("layout", "cards"), ("cols", "name")])
    assert page.layout == "cards"
    assert page.groups == []  # the cards page reads its own items: no cell is converted here
    assert page.footer is None
    assert page.count == 4
    assert page.heads  # the header cells are still built for the shared page
