"""Ties in a sorted report table come out in employee-id order, whatever order the source query returned them in.

A report with a person function (Report.person, or Report.edit_person) sorts its ties by the employee id, ascending, in
both directions: the rows are first put in id order, then the user's sort keys are applied (each pass is stable). Blank
values still go last, a row with no id goes after the rows that have one, and a report without a person function, or a
table with no sort, keeps the order the source query gave.
"""

from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.http import QueryDict

from reports.filters import Filters, parse_filters
from reports.registry import REPORTS
from reports.table import build_table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db


def _person(name: str, pk: int) -> Any:
    return SimpleNamespace(name=name, code=f"E{pk:03d}", pk=pk)


# two employees called «Бат» (ids 3 and 7) and a blank name (id 5); the rows are given in this order, or reversed
TIES_ASC = [
    _person("Сараа", 9),
    _person("Бат", 7),
    _person("Бат", 3),
    _person("", 5),
    _person("Болд", 2),
]


def _report(monkeypatch: pytest.MonkeyPatch, order: list[Any], person: bool = True) -> Report:
    """A report whose source query returns `order`, as given, so the tests can choose the incoming order."""
    report = Report(
        key="sort-ties-test",
        title="Ижил утга",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="code", label="Код", value=lambda r: r.code),
        ),
        default_columns=("name", "code"),
        rows=lambda user, filters: list(order),
        group_options=(),
        person=(lambda r: r.pk) if person else None,
    )
    monkeypatch.setitem(REPORTS, "sort-ties-test", report)
    return report


def _filters(**params: str) -> Filters:
    return parse_filters(QueryDict(urlencode(params)))


def _codes_flat(table: Any) -> list[str]:
    return [cell[1].value for _, rows in table.groups for cell in rows]


def _names(table: Any) -> list[str]:
    return [cell[0].value for _, rows in table.groups for cell in rows]


def test_ties_come_out_in_id_order_whatever_the_incoming_order(
    monkeypatch: pytest.MonkeyPatch, accountant_user: User
) -> None:
    forward = _report(monkeypatch, TIES_ASC)
    a = build_table(forward, accountant_user, _filters(sort="name"))
    reverse = _report(monkeypatch, list(reversed(TIES_ASC)))
    b = build_table(reverse, accountant_user, _filters(sort="name"))
    assert _codes_flat(a) == _codes_flat(b)
    # the two «Бат» rows are in id order (3 before 7) in both loads
    assert _names(a)[0:2] == ["Бат", "Бат"]
    assert _codes_flat(a)[0:2] == ["E003", "E007"]


def test_descending_ties_stay_in_ascending_id_order(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    # decided: a tie is ascending by id in both directions; only the named values change order
    report = _report(monkeypatch, TIES_ASC)  # the source gives id 7 before id 3
    table = build_table(report, accountant_user, _filters(sort="-name"))
    # Сараа, Болд, then the two «Бат» (ids 3 and 7), then the blank name last
    assert _names(table)[2:4] == ["Бат", "Бат"]
    assert _codes_flat(table)[2:4] == ["E003", "E007"]


def test_blank_values_still_go_last_in_both_directions(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    for sort in ("name", "-name"):
        report = _report(monkeypatch, list(reversed(TIES_ASC)))
        table = build_table(report, accountant_user, _filters(sort=sort))
        assert _codes_flat(table)[-1] == "E005"  # the blank name, whose id is 5, is the last row


def test_no_sort_keeps_the_incoming_order(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    report = _report(monkeypatch, list(reversed(TIES_ASC)))
    table = build_table(report, accountant_user, Filters(columns=("name", "code")))
    assert _codes_flat(table) == [p.code for p in reversed(TIES_ASC)]


def test_report_without_a_person_function_keeps_the_incoming_order_of_ties(
    monkeypatch: pytest.MonkeyPatch, accountant_user: User
) -> None:
    report = _report(monkeypatch, list(reversed(TIES_ASC)), person=False)
    table = build_table(report, accountant_user, _filters(sort="name"))
    # the two «Бат» rows keep the order the source gave them (3 then 7): the source was reversed, so 3 came first
    assert _codes_flat(table)[0:2] == ["E003", "E007"]


def test_row_with_no_id_goes_after_the_rows_with_one(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    no_id = _person("Бат", 0)  # pk 0 means no employee id
    report = _report(monkeypatch, [no_id, _person("Бат", 7), _person("Бат", 3)])
    table = build_table(report, accountant_user, _filters(sort="name"))
    assert _codes_flat(table) == ["E003", "E007", "E000"]
