"""Click-through from a date bucket («2026-03», «2026-Q1», «2026») to the table: the «between» rule that keeps exactly
the bucket's rows, and the chart page's links on its buckets."""

from collections.abc import Callable
from datetime import date
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from accounts.models import User
from django.test import Client

from reports import drill as drill_mod
from reports import rules as rules_mod
from reports.registry import REPORTS
from reports.rules import Group, Rule
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")
TODAY = date(2026, 11, 11)
KEY = "drill-bucket-test"
PAGE = f"/reports/{KEY}/"


def _dated(start: object) -> Any:
    return SimpleNamespace(name="Нэр", start=start)


def test_month_bucket_rule_keeps_exactly_its_rows() -> None:
    rule = drill_mod.bucket_condition("start", "month", "2026-03")
    assert rule == Rule(column="start", op="between", value="2026-03-01..2026-03-31")
    # the day before the first, the first, the last and the day after the last, plus a blank date
    days = [date(2026, 2, 28), date(2026, 3, 1), date(2026, 3, 15), date(2026, 3, 31), date(2026, 4, 1)]
    rows = [_dated(day) for day in days] + [_dated(None)]
    kept = rules_mod.keep_rows(rows, Group(op="and", items=(rule,)), {"start": START}, {"start": "date"}, TODAY)
    assert [row.start for row in kept] == [date(2026, 3, 1), date(2026, 3, 15), date(2026, 3, 31)]


def test_quarter_and_year() -> None:
    assert drill_mod.bucket_condition("start", "quarter", "2026-Q1") == Rule(
        "start", "between", "2026-01-01..2026-03-31"
    )
    assert drill_mod.bucket_condition("start", "quarter", "2026-Q4") == Rule(
        "start", "between", "2026-10-01..2026-12-31"
    )
    assert drill_mod.bucket_condition("start", "year", "2026") == Rule("start", "between", "2026-01-01..2026-12-31")
    # the last day of a month follows the calendar, leap years included
    assert drill_mod.bucket_condition("start", "month", "2026-02") == Rule("start", "between", "2026-02-01..2026-02-28")
    assert drill_mod.bucket_condition("start", "month", "2028-02") == Rule("start", "between", "2028-02-01..2028-02-29")
    # the blank bucket keeps the «empty» rule
    assert drill_mod.bucket_condition("start", "month", "") == Rule("start", "empty", "")


def test_unreadable_key_gives_none() -> None:
    cases = [
        ("month", "2026-13"),
        ("month", "2026-3"),
        ("month", "2026"),
        ("month", "2026-Q1"),
        ("month", "2026-03 "),
        ("quarter", "2026-Q5"),
        ("quarter", "2026-03"),
        ("year", "2026-03"),
        ("year", "26"),
        ("year", "0000"),
        ("week", "2026-03"),
    ]
    for grain, key in cases:
        assert drill_mod.bucket_condition("start", grain, key) is None, (grain, key)


def _use_dated_rows(monkeypatch: pytest.MonkeyPatch, rows: list[Any]) -> None:
    report = Report(
        key=KEY,
        title="Цагийн тайлан",
        filters=(),
        columns=(NAME, START),
        default_columns=("name",),
        rows=lambda user, filters: rows,
        layouts=("chart", "pivot"),
    )
    monkeypatch.setitem(REPORTS, KEY, report)


def _rule_items(href: str) -> tuple[Any, ...]:
    """The rules of a table address, as the rule tree reads them back."""
    tree = rules_mod.parse_rules(parse_qs(urlsplit(href).query)["rules"][0])
    assert tree is not None
    return tree.items


def test_chart_month_buckets_link_to_their_rows(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [_dated(date(2026, 3, 1)), _dated(date(2026, 3, 9)), _dated(date(2026, 4, 2)), _dated(None)]
    _use_dated_rows(monkeypatch, rows)
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "chart", "lby": "start", "lgrain": "month"})
    assert response.status_code == 200
    hrefs = {point.label: href for point, _, href in response.context["chart_lines"]}
    assert set(hrefs) == {"2026-03", "2026-04", "—"}
    assert Rule("start", "between", "2026-03-01..2026-03-31") in _rule_items(hrefs["2026-03"])
    assert Rule("start", "between", "2026-04-01..2026-04-30") in _rule_items(hrefs["2026-04"])
    assert hrefs["—"] == ""  # the blank bucket gets no link


def test_chart_folded_bucket_has_no_link(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 36 months: beyond the chart's cap the oldest fold into «Бусад», which has no key and so no link
    rows = [_dated(date(2023 + m // 12, m % 12 + 1, 1)) for m in range(36)]
    _use_dated_rows(monkeypatch, rows)
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "chart", "lby": "start", "lgrain": "month"})
    hrefs = {point.label: href for point, _, href in response.context["chart_lines"]}
    assert hrefs["Бусад"] == ""
    assert Rule("start", "between", "2025-12-01..2025-12-31") in _rule_items(hrefs["2025-12"])
