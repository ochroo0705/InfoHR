"""Several sort keys and up to three group keys: the table orders and groups by allowed columns only."""

from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.http import QueryDict

from reports.filters import Filters, parse_filters
from reports.registry import REPORTS
from reports.table import EMPTY_DEPARTMENT, EMPTY_GROUP, build_table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db


def _people() -> list[Any]:
    return [
        SimpleNamespace(name="Бат", dept="Санхүү", pos="Нягтлан", grade="A", pay=1000),
        SimpleNamespace(name="Дорж", dept="Санхүү", pos="Нягтлан", grade=None, pay=None),
        SimpleNamespace(name="Сараа", dept="Санхүү", pos="Нярав", grade="A", pay=2000),
        SimpleNamespace(name="Болд", dept="Борлуулалт", pos="Менежер", grade="B", pay=500),
        SimpleNamespace(name="Чулуун", dept=None, pos="Менежер", grade="B", pay=800),
        SimpleNamespace(name="Очир", dept="Борлуулалт", pos=None, grade=None, pay=300),
        SimpleNamespace(name="Номин", dept="Санхүү", pos="Нягтлан", grade="A", pay=1000),
        SimpleNamespace(name="Ганаа", dept=None, pos=None, grade=None, pay=None),
    ]


def _report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """Shows only the name by default; pay needs the salary permission, so a restricted user cannot sort by it."""
    report = Report(
        key="multisort-test",
        title="Олон түлхүүр",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
            Column(key="pos", label="Албан тушаал", value=lambda r: r.pos),
            Column(key="grade", label="Зэрэг", value=lambda r: r.grade),
            Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary", numeric=True),
        ),
        default_columns=("name",),
        rows=lambda user, filters: _people(),
        group_options=("dept", "pos", "grade"),
    )
    monkeypatch.setitem(REPORTS, "multisort-test", report)
    return report


def _filters(**params: str) -> Filters:
    """The filters as the address gives them (parse_filters), so the tests use the same path as the page."""
    return parse_filters(QueryDict(urlencode(params)))


def _names(table: Any) -> list[str]:
    return [cell[0].value for _, rows in table.groups for cell in rows]


def _labels(table: Any) -> list[str]:
    return [label for label, _ in table.groups]


def test_two_sort_keys_blank_last_in_both_directions(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    report = _report(monkeypatch)
    table = build_table(report, accountant_user, Filters(columns=("name",), sort="dept,-pay"))
    # dept ascending, blank dept last; within a dept pay descending, blank pay last; ties keep the row order
    assert _names(table) == ["Болд", "Очир", "Сараа", "Бат", "Номин", "Дорж", "Чулуун", "Ганаа"]


def test_two_sort_keys_descending_first_key_keeps_blanks_last(
    monkeypatch: pytest.MonkeyPatch, accountant_user: User
) -> None:
    report = _report(monkeypatch)
    table = build_table(report, accountant_user, Filters(columns=("name",), sort="-dept,pay"))
    # dept descending (Санхүү, Борлуулалт, then blank); within a dept pay ascending, blank pay last
    assert _names(table) == ["Бат", "Номин", "Сараа", "Дорж", "Очир", "Болд", "Чулуун", "Ганаа"]


def test_sort_by_a_column_that_is_not_shown(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    report = _report(monkeypatch)
    table = build_table(report, accountant_user, _filters(sort="-pay"))
    assert [c.key for c in table.columns] == ["name"]  # pay is allowed but not shown
    assert _names(table) == ["Сараа", "Бат", "Номин", "Чулуун", "Болд", "Очир", "Дорж", "Ганаа"]
    assert table.filters.sort == "-pay"


def test_sort_naming_a_hidden_column_is_dropped(monkeypatch: pytest.MonkeyPatch, hr_user: User) -> None:
    report = _report(monkeypatch)
    plain = build_table(report, hr_user, Filters(columns=("name",), sort="dept"))
    hidden = build_table(report, hr_user, _filters(sort="pay,-dept"))
    assert hidden.filters.sort == "-dept"  # the hidden pay key is dropped, the allowed key stays
    assert _names(hidden) == _names(build_table(report, hr_user, Filters(columns=("name",), sort="-dept")))
    only_hidden = build_table(report, hr_user, _filters(sort="pay,-pay"))
    assert only_hidden.filters.sort == ""
    assert _names(only_hidden) == _names(build_table(report, hr_user, Filters(columns=("name",))))
    assert plain.filters.sort == "dept"


def test_three_level_group_labels_order_and_empty_group_last(
    monkeypatch: pytest.MonkeyPatch, accountant_user: User
) -> None:
    report = _report(monkeypatch)
    table = build_table(report, accountant_user, Filters(columns=("name",), group="dept,pos,grade"))
    all_blank = EMPTY_DEPARTMENT + " › " + EMPTY_GROUP + " › " + EMPTY_GROUP
    assert _labels(table) == [
        "Борлуулалт › Менежер › B",
        "Борлуулалт › " + EMPTY_GROUP + " › " + EMPTY_GROUP,
        "Санхүү › Нягтлан › A",
        "Санхүү › Нягтлан › " + EMPTY_GROUP,
        "Санхүү › Нярав › A",
        EMPTY_DEPARTMENT + " › Менежер › B",
        all_blank,
    ]
    members = {label: [cell[0].value for cell in rows] for label, rows in table.groups}
    assert members["Санхүү › Нягтлан › A"] == ["Бат", "Номин"]
    assert members["Санхүү › Нягтлан › " + EMPTY_GROUP] == ["Дорж"]
    assert members[all_blank] == ["Ганаа"]
    assert table.groups[-1][0] == all_blank


def test_group_key_not_in_group_options_is_dropped(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    report = _report(monkeypatch)
    table = build_table(report, accountant_user, Filters(columns=("name",), group="dept,name,pos"))
    assert table.filters.group == "dept,pos"  # name is not a group option of this report
    assert _labels(table)[0] == "Борлуулалт › Менежер"
    assert len(table.groups) == 6  # dept and pos only: 5 non-empty + the all-blank group


def test_single_sort_and_group_are_unchanged(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    report = _report(monkeypatch)
    table = build_table(report, accountant_user, Filters(columns=("name",), sort="-name", group="dept"))
    assert _labels(table) == ["Борлуулалт", "Санхүү", EMPTY_DEPARTMENT]
    assert _names(table) == ["Очир", "Болд", "Сараа", "Номин", "Дорж", "Бат", "Чулуун", "Ганаа"]
    assert table.filters.sort == "-name"
    assert table.filters.group == "dept"
    assert table.count == 8


def test_count_is_unaffected_by_grouping(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    report = _report(monkeypatch)
    grouped = build_table(report, accountant_user, Filters(columns=("name",), group="dept,pos,grade"))
    flat = build_table(report, accountant_user, Filters(columns=("name",)))
    assert grouped.count == flat.count == 8
    assert sum(len(rows) for _, rows in grouped.groups) == 8


def test_used_strings_keep_only_the_cleaned_keys(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    report = _report(monkeypatch)
    table = build_table(
        report,
        accountant_user,
        Filters(columns=("name",), sort="-pay,nope,name,-pay", group="dept,bogus,pos"),
    )
    assert table.filters.sort == "-pay,name"
    assert table.filters.group == "dept,pos"


def test_used_strings_drop_hidden_keys_for_a_restricted_user(monkeypatch: pytest.MonkeyPatch, hr_user: User) -> None:
    report = _report(monkeypatch)
    table = build_table(report, hr_user, Filters(columns=("name",), sort="-pay,name", group="pay,pos"))
    assert table.filters.sort == "name"
    assert table.filters.group == "pos"


def _addresses(monkeypatch: pytest.MonkeyPatch) -> Report:
    """Addresses, some missing as an empty text or only spaces (the staff list gives "" for a missing address)."""
    rows = [
        SimpleNamespace(name="Бат", addr="Ub", dept="Санхүү"),
        SimpleNamespace(name="Дорж", addr="", dept="Санхүү"),
        SimpleNamespace(name="Сараа", addr="Dar", dept="Борлуулалт"),
        SimpleNamespace(name="Болд", addr="  ", dept="Борлуулалт"),
        SimpleNamespace(name="Номин", addr="", dept="Борлуулалт"),
        SimpleNamespace(name="Очир", addr="Dar", dept="Санхүү"),
    ]
    report = Report(
        key="multisort-addr",
        title="Хаяг",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="addr", label="Хаяг", value=lambda r: r.addr),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
        ),
        default_columns=("name",),
        rows=lambda user, filters: rows,
        group_options=("dept",),
    )
    monkeypatch.setitem(REPORTS, "multisort-addr", report)
    return report


def test_empty_text_sorts_last_in_both_directions(monkeypatch: pytest.MonkeyPatch, hr_user: User) -> None:
    report = _addresses(monkeypatch)
    asc = build_table(report, hr_user, Filters(columns=("name",), sort="addr"))
    # "Dar" before "Ub"; the blank addresses (empty or spaces) last, in their row order
    assert _names(asc) == ["Сараа", "Очир", "Бат", "Дорж", "Болд", "Номин"]
    desc = build_table(report, hr_user, Filters(columns=("name",), sort="-addr"))
    assert _names(desc) == ["Бат", "Сараа", "Очир", "Дорж", "Болд", "Номин"]


def test_blank_text_stays_last_within_each_first_key_level(monkeypatch: pytest.MonkeyPatch, hr_user: User) -> None:
    report = _addresses(monkeypatch)
    table = build_table(report, hr_user, Filters(columns=("name",), sort="dept,addr"))
    # dept ascending; inside each dept the address ascending, blank addresses last
    assert _names(table) == ["Сараа", "Болд", "Номин", "Очир", "Бат", "Дорж"]


def test_two_key_group_with_a_blank_first_part_keeps_blanks_last(
    monkeypatch: pytest.MonkeyPatch, accountant_user: User
) -> None:
    report = _report(monkeypatch)
    table = build_table(report, accountant_user, Filters(columns=("name",), group="grade,dept"))
    assert _labels(table) == [
        "A › Санхүү",
        "B › Борлуулалт",
        "B › " + EMPTY_DEPARTMENT,
        EMPTY_GROUP + " › Борлуулалт",
        EMPTY_GROUP + " › Санхүү",
        EMPTY_GROUP + " › " + EMPTY_DEPARTMENT,  # every part blank: last
    ]
    members = {label: [cell[0].value for cell in rows] for label, rows in table.groups}
    assert members["A › Санхүү"] == ["Бат", "Сараа", "Номин"]
    assert members[EMPTY_GROUP + " › Санхүү"] == ["Дорж"]
