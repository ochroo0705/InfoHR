"""The date grain of a category: month, quarter or year buckets (date_bucket), the grain argument of _key, and a date
column as a chart or pivot category (Task 3)."""

from collections.abc import Callable
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client

from reports import layouts as layouts_mod
from reports.filters import Filters
from reports.layouts import LayoutSpec
from reports.registry import REPORTS
from reports.table import Table
from reports.types import Column, Report

START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
NAME = Column(key="name", label="Нэр", value=lambda r: r.name, kind="text")


def _row(name: str, start: object = None) -> Any:
    return SimpleNamespace(name=name, start=start)


def test_month_quarter_year() -> None:
    day = date(2026, 3, 15)
    assert layouts_mod.date_bucket(day, "month") == "2026-03"
    assert layouts_mod.date_bucket(day, "quarter") == "2026-Q1"
    assert layouts_mod.date_bucket(day, "year") == "2026"
    assert layouts_mod.date_bucket(date(2026, 11, 1), "quarter") == "2026-Q4"


def test_datetime_and_none() -> None:
    assert layouts_mod.date_bucket(datetime(2026, 3, 15, 23, 59), "month") == "2026-03"
    assert layouts_mod.date_bucket(datetime(2026, 3, 15, 23, 59), "year") == "2026"
    assert layouts_mod.date_bucket(None, "month") == ""
    assert layouts_mod.date_bucket("not a date", "quarter") == ""


def test_unknown_grain_gives_iso_day() -> None:
    assert layouts_mod.date_bucket(date(2026, 3, 5), "week") == "2026-03-05"


def test_key_without_grain_is_unchanged() -> None:
    row = _row("Бат", start=date(2026, 3, 15))
    assert layouts_mod._key(START, row) == "2026-03-15"
    assert layouts_mod._key(None, row) == ""


def test_key_with_grain_on_a_date_column_buckets_it() -> None:
    row = _row("Бат", start=date(2026, 3, 15))
    assert layouts_mod._key(START, row, "month") == "2026-03"
    assert layouts_mod._key(START, _row("Бат", start=None), "quarter") == ""


def test_key_with_grain_on_a_text_column_is_unchanged() -> None:
    row = _row("2026-03-15", start=date(2026, 3, 15))
    assert layouts_mod._key(NAME, row, "month") == "2026-03-15"


# ---- a date column as a chart or pivot category (Task 3) ----

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 7)
DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
PAY_DATE = Column(
    key="pay_date", label="Цалингийн огноо", value=lambda r: r.pay_date, kind="date", needs="macs.view_salary"
)
KEY = "layout-grain-test"
PAGE = f"/reports/{KEY}/"


def _dated(start: object, dept: str = "X", pay_date: object = None) -> Any:
    return SimpleNamespace(name="Нэр", dept=dept, start=start, pay_date=pay_date)


def _chart_spec(by: Column, grain: str, layout: str = "chart") -> LayoutSpec:
    return LayoutSpec(
        layout=layout, by=by, by2=None, value=(None, "count"), chart="bar", month=date(2026, 11, 1), grain=grain
    )


def _chart(rows: list[Any], grain: str) -> layouts_mod.Chart:
    spec = _chart_spec(START, grain)
    table = Table(columns=[NAME, DEPT, START], groups=[], count=len(rows), filters=Filters(), rows=rows, spec=spec)
    return layouts_mod.build_chart(table, spec)


def _date_report(layouts: tuple[str, ...], columns: tuple[Column, ...] | None = None) -> Report:
    return Report(
        key="grain-offer",
        title="Тайлан",
        filters=(),
        columns=columns or (NAME, START, Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date")),
        default_columns=("name",),
        rows=lambda user, filters: [],
        layouts=layouts,
    )


def test_chart_by_a_date_column_groups_by_month() -> None:
    rows = [_dated(date(2026, 1, 5)), _dated(date(2026, 1, 20)), _dated(date(2026, 2, 3))]
    chart = _chart(rows, "month")
    assert [p.label for p in chart.points] == ["2026-01", "2026-02"]
    assert [p.value for p in chart.points] == [2, 1]


def test_quarter_and_year_grain() -> None:
    rows = [_dated(date(2025, 12, 31)), _dated(date(2026, 4, 2)), _dated(date(2026, 5, 9))]
    # Task 4 fills the empty quarter between the first and last bucket, so 2026-Q1 is drawn with 0.
    assert [p.label for p in _chart(rows, "quarter").points] == ["2025-Q4", "2026-Q1", "2026-Q2"]
    assert [p.value for p in _chart(rows, "quarter").points] == [1, 0, 2]
    assert [p.label for p in _chart(rows, "year").points] == ["2025", "2026"]
    assert [p.value for p in _chart(rows, "year").points] == [1, 2]


def test_blank_dates_are_the_dash_bucket() -> None:
    rows = [_dated(date(2026, 1, 5)), _dated(None), _dated("")]
    chart = _chart(rows, "month")
    assert [p.label for p in chart.points] == ["2026-01", "—"]
    assert [p.value for p in chart.points] == [1, 2]


def test_all_blank_dates_give_only_the_dash_bucket() -> None:
    chart = _chart([_dated(None), _dated(None)], "month")
    assert [p.label for p in chart.points] == ["—"]
    assert [p.value for p in chart.points] == [2]


def test_report_with_only_dates_offers_chart_and_pivot(accountant_user: User) -> None:
    """Chart and pivot may group by a date column, so a report with only dates offers them; board needs a category.
    Before Task 3 chart and pivot needed a category column too, so this report offered only the table."""
    report = _date_report(("board", "chart", "pivot", "calendar"))
    assert layouts_mod.offered_layouts(report, accountant_user) == ["table", "calendar", "chart", "pivot"]
    spec = layouts_mod.resolve(report, accountant_user, Filters(layout="chart"))
    assert spec.by is not None and spec.by.key == "start"
    assert spec.grain == "month"


def test_resolve_grain_defaults_to_month_and_honours_a_valid_grain(accountant_user: User) -> None:
    report = _date_report(("chart",))
    assert layouts_mod.resolve(report, accountant_user, Filters(layout="chart")).grain == "month"
    assert layouts_mod.resolve(report, accountant_user, Filters(layout="chart", lgrain="year")).grain == "year"
    # an unknown grain (not from the address parser) is ignored, as the default month
    assert layouts_mod.resolve(report, accountant_user, Filters(layout="chart", lgrain="week")).grain == "month"


def test_grain_is_empty_without_a_date_category(accountant_user: User) -> None:
    report = Report(
        key="grain-text",
        title="Тайлан",
        filters=(),
        columns=(DEPT,),
        default_columns=("dept",),
        rows=lambda user, filters: [],
        group_options=("dept",),
        layouts=("chart",),
    )
    assert layouts_mod.resolve(report, accountant_user, Filters(layout="chart")).grain == ""


def test_used_params_writes_lgrain_only_from_the_request() -> None:
    """lgrain is written from the request's own value: an explicit «Сар» stays in the address, and a grain that was only
    chosen automatically (the spec's grain, not the request's) is never written (2026-11-11)."""
    assert layouts_mod.used_params(Filters(lgrain="quarter"), _chart_spec(START, "quarter")).lgrain == "quarter"
    assert layouts_mod.used_params(Filters(lgrain="month"), _chart_spec(START, "month")).lgrain == "month"
    assert layouts_mod.used_params(Filters(), _chart_spec(START, "quarter")).lgrain == ""
    assert layouts_mod.used_params(Filters(), _chart_spec(START, "month")).lgrain == ""


# ---- the automatic grain follows the span of the dates (2026-11-11) ----


def _rows_with_dates(starts: list[object], ends: list[object] | None = None) -> list[Any]:
    """Rows with a start and an end date; ends default to blank."""
    ends = ends if ends is not None else [None] * len(starts)
    return [
        SimpleNamespace(name="Нэр", dept="X", start=s, end=e, pay_date=None) for s, e in zip(starts, ends, strict=True)
    ]


def test_auto_grain_is_year_for_a_long_span(accountant_user: User) -> None:
    rows = _rows_with_dates([date(2008, 5, 1), date(2026, 3, 1)])
    spec = layouts_mod.resolve(_date_report(("chart",)), accountant_user, Filters(layout="chart"), rows)
    assert spec.grain == "year"


def test_auto_grain_is_month_for_a_short_span(accountant_user: User) -> None:
    rows = _rows_with_dates([date(2026, 1, 1), date(2027, 12, 1)])  # 23 months
    spec = layouts_mod.resolve(_date_report(("chart",)), accountant_user, Filters(layout="chart"), rows)
    assert spec.grain == "month"


def test_span_boundary(accountant_user: User) -> None:
    report = _date_report(("chart",))
    exactly_36 = _rows_with_dates([date(2026, 1, 1), date(2029, 1, 31)])  # 36 whole months
    assert layouts_mod.resolve(report, accountant_user, Filters(layout="chart"), exactly_36).grain == "month"
    just_over = _rows_with_dates([date(2026, 1, 1), date(2029, 2, 1)])  # 37 whole months
    assert layouts_mod.resolve(report, accountant_user, Filters(layout="chart"), just_over).grain == "year"


def test_explicit_lgrain_wins_over_auto(accountant_user: User) -> None:
    rows = _rows_with_dates([date(2008, 5, 1), date(2026, 3, 1)])
    filters = Filters(layout="chart", lgrain="month")
    spec = layouts_mod.resolve(_date_report(("chart",)), accountant_user, filters, rows)
    assert spec.grain == "month"
    assert layouts_mod.used_params(filters, spec).lgrain == "month"


def test_auto_grain_not_written_to_the_address(accountant_user: User) -> None:
    rows = _rows_with_dates([date(2008, 5, 1), date(2026, 3, 1)])
    filters = Filters(layout="chart", lby="start")
    spec = layouts_mod.resolve(_date_report(("chart",)), accountant_user, filters, rows)
    assert spec.grain == "year"
    assert layouts_mod.used_params(filters, spec).lgrain == ""


def test_two_date_columns_use_the_larger_span(accountant_user: User) -> None:
    """start spans 2 months, end spans 18 years: the pivot's grain is the year, the larger span."""
    rows = _rows_with_dates([date(2026, 1, 1), date(2026, 3, 1)], [date(2008, 5, 1), date(2026, 3, 1)])
    filters = Filters(layout="pivot", lby="start", lby2="end")
    spec = layouts_mod.resolve(_date_report(("pivot",)), accountant_user, filters, rows)
    assert spec.by is not None and spec.by.key == "start"
    assert spec.by2 is not None and spec.by2.key == "end"
    assert spec.grain == "year"


def test_blank_dates_do_not_break_the_span(accountant_user: User) -> None:
    report = _date_report(("chart",))
    all_blank = _rows_with_dates([None, "", None])
    assert layouts_mod.resolve(report, accountant_user, Filters(layout="chart"), all_blank).grain == "month"
    mixed = _rows_with_dates([None, date(2026, 1, 1), None, date(2027, 1, 1)])  # 12 months between the dates
    assert layouts_mod.resolve(report, accountant_user, Filters(layout="chart"), mixed).grain == "month"


def test_long_span_chart_page_selects_year(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chart by a start date spanning 18 years: «Хуваалт» shows «Жил» and the data table has year labels."""
    _use_dated_rows(monkeypatch, [_dated(date(2008, 5, 1), dept="Санхүү"), _dated(date(2026, 3, 1), dept="Санхүү")])
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "chart", "lby": "start"})
    assert response.status_code == 200
    assert '<option value="year" selected>Жил</option>' in response.content.decode()
    labels = [point.label for point, _, _ in response.context["chart_lines"]]
    assert labels[0] == "2008"
    assert labels[-1] == "2026"
    assert len(labels) == 19


def test_hidden_date_column_is_never_the_category(hr_user: User) -> None:
    """pay_date needs macs.view_salary: HR may not group by it, so it is not offered and a request for it falls back."""
    report = _date_report(("chart",), columns=(NAME, START, PAY_DATE))
    assert layouts_mod.offered_layouts(report, hr_user) == ["table", "chart"]
    spec = layouts_mod.resolve(report, hr_user, Filters(layout="chart", lby="pay_date"))
    assert spec.by is not None and spec.by.key == "start"
    choices = layouts_mod.layout_choices(report, hr_user, "chart")
    assert [key for key, _ in choices.by] == ["start"]


def _use_dated_rows(monkeypatch: pytest.MonkeyPatch, rows: list[Any]) -> None:
    report = Report(
        key=KEY,
        title="Цагийн тайлан",
        filters=(),
        columns=(NAME, DEPT, START, PAY_DATE),
        default_columns=("name", "dept"),
        rows=lambda user, filters: rows,
        group_options=("dept",),
        layouts=("chart", "pivot"),
    )
    monkeypatch.setitem(REPORTS, KEY, report)


def test_layout_bar_shows_grain_select_only_for_a_date_category(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_dated_rows(monkeypatch, [_dated(date(2026, 3, 1), dept="Санхүү")])
    login_as(client, "HR")
    by_date = client.get(PAGE, {"layout": "chart", "lby": "start"}).content.decode()
    assert 'name="lgrain"' in by_date
    by_text = client.get(PAGE, {"layout": "chart", "lby": "dept"}).content.decode()
    assert 'name="lgrain"' not in by_text
    pivot_by_date = client.get(PAGE, {"layout": "pivot", "lby": "start"}).content.decode()
    assert 'name="lgrain"' in pivot_by_date


def test_chart_of_dates_links_its_buckets_by_a_between_rule(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task 5 replaced Task 3's «no link» on a date bucket: «2026-03» now links by a «between» rule over its month
    (test_drill_bucket.py covers the rule itself)."""
    _use_dated_rows(monkeypatch, [_dated(date(2026, 3, 1)), _dated(date(2026, 3, 9))])
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "chart", "lby": "start", "lgrain": "month"})
    assert response.status_code == 200
    lines = response.context["chart_lines"]
    assert [point.label for point, _, _ in lines] == ["2026-03"]
    assert [href.count("rules=") for _, _, href in lines] == [1]


def _pivot_report(group_options: tuple[str, ...] = ("dept",)) -> Report:
    return Report(
        key="grain-pivot",
        title="Тайлан",
        filters=(),
        columns=(NAME, DEPT, START),
        default_columns=("name",),
        rows=lambda user, filters: [],
        group_options=group_options,
        layouts=("pivot",),
    )


def test_explicit_lby2_date_still_resolves(accountant_user: User) -> None:
    """A pivot's second column may still be a date when the address asks for it by lby2."""
    spec = layouts_mod.resolve(_pivot_report(), accountant_user, Filters(layout="pivot", lby2="start"))
    assert spec.by2 is not None and spec.by2.key == "start"


def test_pivot_default_second_column_ignores_dates(accountant_user: User) -> None:
    """One category and one date column: the default second column stays «Нийт» (none), as before Task 3."""
    spec = layouts_mod.resolve(_pivot_report(), accountant_user, Filters(layout="pivot"))
    assert spec.by is not None and spec.by.key == "dept"
    assert spec.by2 is None


# ---- gap fill, oldest-first fold and the blank bucket last (Task 4) ----

AGE = Column(key="age", label="Нас", value=lambda r: r.age, kind="number", numeric=True)


def _dated_age(start: object, age: object) -> Any:
    return SimpleNamespace(name="Нэр", dept="X", start=start, age=age, pay_date=None)


def _months(first: date, count: int) -> list[date]:
    """The first day of count consecutive months from first (a Jan-first start keeps the arithmetic obvious)."""
    out = []
    year, month = first.year, first.month
    for _ in range(count):
        out.append(date(year, month, 1))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return out


def test_filled_months() -> None:
    rows = [_dated(date(2026, 1, 5)), _dated(date(2026, 1, 9)), _dated(date(2026, 4, 2))]
    chart = _chart(rows, "month")
    assert [p.label for p in chart.points] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert [p.value for p in chart.points] == [2, 0, 0, 1]
    assert chart.keys == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert chart.folded is False


def test_no_fill_above_the_limit() -> None:
    rows = [_dated(date(1900, 1, 1)), _dated(date(2100, 1, 1))]
    chart = _chart(rows, "month")
    assert [p.label for p in chart.points] == ["1900-01", "2100-01"]
    assert [p.value for p in chart.points] == [1, 1]
    assert chart.folded is False


def test_oldest_fold_first() -> None:
    rows = [_dated(day) for day in _months(date(2023, 1, 1), 40)]
    chart = _chart(rows, "month")
    assert len(chart.points) == 30
    assert chart.points[0].label == "Бусад"
    assert chart.points[0].value == 11  # 2023-01 .. 2023-11 folded
    assert chart.keys[0] is None
    assert chart.points[1].label == "2023-12"
    assert chart.points[-1].label == "2026-04"
    assert len(chart.points) - 1 == 29
    assert sum(p.value for p in chart.points) == 40
    assert chart.folded is True


def test_blank_bucket_stays_last() -> None:
    rows = [_dated(date(2026, 1, 5)), _dated(date(2026, 3, 1)), _dated(None)]
    chart = _chart(rows, "month")
    assert [p.label for p in chart.points] == ["2026-01", "2026-02", "2026-03", "—"]
    assert [p.value for p in chart.points] == [1, 0, 1, 1]
    assert chart.keys == ["2026-01", "2026-02", "2026-03", ""]


def test_blank_bucket_stays_last_after_a_fold() -> None:
    rows = [_dated(day) for day in _months(date(2023, 1, 1), 40)] + [_dated(None)]
    chart = _chart(rows, "month")
    assert chart.points[0].label == "Бусад"
    assert chart.points[-1].label == "—"
    assert chart.points[-1].value == 1
    assert sum(p.value for p in chart.points) == 41


def test_avg_of_an_empty_bucket_is_none() -> None:
    assert layouts_mod._measure([], (AGE, "avg")) is None
    assert layouts_mod._measure([], (AGE, "count")) == 0
    rows = [_dated_age(date(2026, 1, 5), 30), _dated_age(date(2026, 3, 5), 40)]
    spec = LayoutSpec(
        layout="chart", by=START, by2=None, value=(AGE, "avg"), chart="bar", month=date(2026, 11, 1), grain="month"
    )
    table = Table(columns=[NAME, START], groups=[], count=2, filters=Filters(), rows=rows, spec=spec)
    chart = layouts_mod.build_chart(table, spec)
    assert [p.label for p in chart.points] == ["2026-01", "2026-02", "2026-03"]
    assert [p.value for p in chart.points] == [30, None, 40]


def test_quarter_and_year_fill_step_by_one_bucket() -> None:
    rows = [_dated(date(2025, 11, 1)), _dated(date(2026, 5, 1))]
    assert [p.label for p in _chart(rows, "quarter").points] == ["2025-Q4", "2026-Q1", "2026-Q2"]
    assert [p.value for p in _chart(rows, "quarter").points] == [1, 0, 1]
    rows = [_dated(date(2019, 6, 1)), _dated(date(2022, 6, 1))]
    assert [p.label for p in _chart(rows, "year").points] == ["2019", "2020", "2021", "2022"]
    assert [p.value for p in _chart(rows, "year").points] == [1, 0, 0, 1]


def test_pivot_rows_fill_gaps_and_keep_keys() -> None:
    rows = [_dated(date(2026, 1, 5), dept="A"), _dated(date(2026, 3, 5), dept="A")]
    spec = LayoutSpec(
        layout="pivot", by=START, by2=None, value=(None, "count"), chart="bar", month=date(2026, 11, 1), grain="month"
    )
    table = Table(columns=[NAME, START], groups=[], count=2, filters=Filters(), rows=rows, spec=spec)
    pivot = layouts_mod.build_pivot(table, spec)
    assert pivot.row_labels == ["2026-01", "2026-02", "2026-03"]
    assert pivot.row_keys == ["2026-01", "2026-02", "2026-03"]
    assert pivot.cells == [[1], [0], [1]]
    assert pivot.row_totals == [1, 0, 1]
    assert pivot.grand == 2


def test_non_bucket_key_is_plain_text_order() -> None:
    """A key that is not a bucket of the grain (an ISO day when the grain is unknown) must not crash: text order."""
    labels, index, folded = layouts_mod._time_plan(["2026-03-05", "2026-01-02", ""], 30, "week")
    assert labels == ["2026-01-02", "2026-03-05", "—"]
    assert index == {"2026-01-02": 0, "2026-03-05": 1, "": 2}
    assert folded is False
    assert layouts_mod._time_drawn_keys(["2026-03-05", "2026-01-02", ""], 30, "week") == [
        "2026-01-02",
        "2026-03-05",
        "",
    ]
