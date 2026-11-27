"""The layout bar's model (reports.services.layout_page): which selects a layout draws, in the template's order,
with the options and the value each shows; the drill address; the check that the template and the model offer the
same options, labels and shown values, so the two cannot drift apart; and that a column the viewer may not see is
never offered."""

import re
from collections.abc import Callable
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client

from reports.filters import Filters, parse_filters
from reports.layouts import LayoutSpec
from reports.registry import REPORTS
from reports.services import layout_page
from reports.types import Column, Report

KEY = "layout-page-bar"
PAGE = f"/reports/{KEY}/"
BAR = re.compile(r'<form[^>]*aria-label="Харагдацын багана".*?</form>', re.DOTALL)
LABELLED = re.compile(r'<label[^>]*>\s*<span[^>]*>([^<]*)</span>\s*<select name="(\w+)"[^>]*>(.*?)</select>', re.DOTALL)
OPTION = re.compile(r'<option value="([^"]*)"([^>]*)>([^<]*)</option>')
HIDDEN = ("secret_grp", "secret_hire", "secret_pay")  # the columns that need the permission «secret.view»
COUNT = (None, "count")


def _viewer(denied: str = "") -> Any:
    """A viewer who may see every column (every column but those that need `denied`): the bar only asks has_perm."""
    return SimpleNamespace(has_perm=lambda perm: perm != denied)


def _people() -> list[Any]:
    return [
        SimpleNamespace(
            name=f"Ажилтан {n:02d}",
            dept=("Санхүү", "Ачаа")[n % 2],
            start=date(2026, 11, 1) + timedelta(days=n),
            end=date(2026, 11, 1) + timedelta(days=n + 3),
            pay=1000 * n,
        )
        for n in range(1, 13)
    ]


def _report(hidden: bool = False) -> Report:
    """The fixture report. With `hidden`, three more columns (HIDDEN) that need the permission «secret.view»."""
    columns = [
        Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
        Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
        Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date"),
        Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date"),
        Column(key="pay", label="Цалин", value=lambda r: r.pay, kind="number"),
    ]
    groups = ["dept", "name"]
    if hidden:
        columns += [
            Column(key="secret_grp", label="Нууц бүлэг", value=lambda r: r.dept, kind="text", needs="secret.view"),
            Column(key="secret_hire", label="Нууц огноо", value=lambda r: r.start, kind="date", needs="secret.view"),
            Column(key="secret_pay", label="Нууц цалин", value=lambda r: r.pay, kind="number", needs="secret.view"),
        ]
        groups.append("secret_grp")
    return Report(
        key=KEY,
        title="Ажилтны тайлан",
        filters=(),
        columns=tuple(columns),
        default_columns=("name", "dept"),
        rows=lambda user, filters: _people(),
        group_options=tuple(groups),
        layouts=("board", "calendar", "timeline", "chart", "pivot"),
    )


def _cols() -> dict[str, Column]:
    return {c.key: c for c in _report().columns}


def _spec(layout: str, **fields: Any) -> LayoutSpec:
    cols = _cols()
    base: dict[str, Any] = {"by": None, "by2": None, "value": COUNT, "chart": "bar", "month": date(2026, 11, 1)}
    base.update({k: (cols[v] if isinstance(v, str) and v in cols else v) for k, v in fields.items()})
    return LayoutSpec(layout=layout, **base)


def _names(spec: LayoutSpec, dated: bool = False, sort_ok: bool = True) -> list[str]:
    bar = layout_page.layout_bar(_report(), _viewer(), spec, Filters(), [], dated, sort_ok)
    return [s.name for s in bar.selects]


@pytest.mark.parametrize(
    ("spec", "dated", "sort_ok", "expected"),
    [
        (_spec("board", by="dept", value=COUNT), False, True, ["lby", "lorder", "lval"]),
        (_spec("calendar", by="start", by2="end"), False, True, ["lby", "lby2", "lrep"]),
        (_spec("timeline", by="start", by2="end", group="dept"), False, True, ["lby", "lby2", "lgroup"]),
        (_spec("chart", by="dept"), False, True, ["lby", "lval", "lshow", "lsort", "lchart"]),
        (_spec("chart", by="start", grain="month"), True, False, ["lby", "lval", "lshow", "lgrain", "lchart"]),
        (_spec("pivot", by="dept"), False, True, ["lby", "lby2", "lval", "lval2", "lshow"]),
        (_spec("pivot", by="dept", grain="year"), True, False, ["lby", "lby2", "lval", "lval2", "lshow", "lgrain"]),
    ],
)
def test_bar_selects_per_layout_match_the_template_order(
    spec: LayoutSpec, dated: bool, sort_ok: bool, expected: list[str]
) -> None:
    assert _names(spec, dated, sort_ok) == expected


def test_calendar_end_select_has_a_blank_first_option_timeline_has_none() -> None:
    cal = layout_page.layout_bar(
        _report(), _viewer(), _spec("calendar", by="start", by2="end"), Filters(), [], False, True
    )
    tl = layout_page.layout_bar(
        _report(), _viewer(), _spec("timeline", by="start", by2="end"), Filters(), [], False, True
    )
    cal_end = next(s for s in cal.selects if s.name == "lby2")
    tl_end = next(s for s in tl.selects if s.name == "lby2")
    assert cal_end.options[0] == ("", "—")
    assert tl_end.options[0] != ("", "—")


def test_chart_split_select_only_for_stacked_with_second_category() -> None:
    def names(chart: str, by2: str | None) -> list[str]:
        spec = _spec("chart", by="dept", by2=by2, chart=chart)
        return _names(spec)

    assert "lby2" not in names("bar", "name")
    assert "lby2" not in names("stacked", None)
    stacked = layout_page.layout_bar(
        _report(), _viewer(), _spec("chart", by="dept", by2="name", chart="stacked"), Filters(), [], False, True
    )
    split = next(s for s in stacked.selects if s.name == "lby2")
    assert split.label == "Хуваах"
    assert split.selected == "name"
    assert ("dept", "Хэлтэс") not in split.options


def test_sort_select_hidden_for_a_dated_category_with_grain() -> None:
    spec = _spec("chart", by="start", grain="month")
    assert "lsort" not in _names(spec, dated=True, sort_ok=False)
    assert "lsort" in _names(_spec("chart", by="dept"), dated=False, sort_ok=True)


def test_keep_pairs_drop_the_layout_own_params_and_carry_adds() -> None:
    f = Filters(
        layout="chart", lby="dept", lval="count", lchart="bar", lshow="pct", lrep="1", lyear="2026", lweek="2026-11-09"
    )
    bar = layout_page.layout_bar(_report(), _viewer(), _spec("chart", by="dept"), f, ["dept"], False, True)
    names = [name for name, _ in bar.keep]
    assert ("lyear", "2026") in bar.keep
    assert ("lweek", "2026-11-09") in bar.keep
    assert ("add", "dept") in bar.keep
    for own in ("layout", "lby", "lval", "lchart", "lshow", "lrep"):
        assert own not in names, own


def test_drill_url_blank_key_or_missing_column_is_empty() -> None:
    dept = _cols()["dept"]
    kinds = {"dept": "text"}
    assert layout_page.drill_url("/reports/x/", Filters(), [], False, [(dept, None)], kinds, {}) == ""
    assert layout_page.drill_url("/reports/x/", Filters(), [], False, [(None, "Санхүү")], kinds, {}) == ""
    url = layout_page.drill_url("/reports/x/", Filters(), [], False, [(dept, "Санхүү")], kinds, {})
    assert url.startswith("/reports/x/?")
    assert "lby=" not in url


def _effective(options: list[tuple[str, str]], selected: str) -> str:
    """The value a select shows: the chosen option, or the first one when none is chosen (the browser default)."""
    values = [value for value, _ in options]
    return selected if selected in values else values[0]


def _template_selects(page: str) -> list[tuple[str, str, list[tuple[str, str]], str]]:
    """Each select of the bar as the template draws it: (name, label, (value, text) options, the value it shows)."""
    bar = BAR.search(page)
    assert bar is not None, "the layout bar form is not on the page"
    body = bar.group(0)
    assert body.count("<select ") == len(LABELLED.findall(body)), "a select without its label"
    found = []
    for label, name, options_html in LABELLED.findall(body):
        options = OPTION.findall(options_html)
        chosen = [value for value, attrs, _ in options if "selected" in attrs.split()]
        pairs = [(value, text) for value, _, text in options]
        found.append((name, label, pairs, chosen[0] if chosen else pairs[0][0]))
    return found


def _model_selects(bar: layout_page.LayoutBar) -> list[tuple[str, str, list[tuple[str, str]], str]]:
    return [(s.name, s.label, s.options, _effective(s.options, s.selected)) for s in bar.selects]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params",
    [
        {"layout": "board", "lby": "dept"},
        {"layout": "calendar", "lby": "start", "lby2": "end"},
        {"layout": "timeline", "lby": "start", "lby2": "end", "lgroup": "dept"},
        {"layout": "chart", "lby": "dept", "lchart": "bar"},
        {"layout": "chart", "lby": "dept", "lby2": "name", "lchart": "stacked"},
        {"layout": "chart", "lby": "start", "lgrain": "month", "lchart": "line"},
        {"layout": "pivot", "lby": "dept", "lby2": "name"},
        {"layout": "board", "lby": "dept", "lorder": "count", "lval": "pay:sum"},
        {"layout": "calendar", "lby": "start", "lby2": "end", "lrep": "1"},
        {"layout": "timeline", "lby": "start", "lby2": "end", "lgroup": "name"},
        {"layout": "chart", "lby": "dept", "lval": "pay:avg", "lshow": "pct", "lsort": "value", "lchart": "donut"},
        {"layout": "chart", "lby": "dept", "lby2": "name", "lchart": "stacked", "lval": "pay:sum"},
        {"layout": "pivot", "lby": "dept", "lby2": "name", "lval": "pay:sum", "lval2": "count", "lshow": "colpct"},
    ],
)
def test_template_and_model_offer_the_same_options(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch, params: dict[str, str]
) -> None:
    """The rendered bar and the model agree on every select: its name, label, options (value and text, in order) and
    the value it shows (the template's selected option, or the first one)."""
    monkeypatch.setitem(REPORTS, KEY, _report())
    login_as(client, "HR")
    response = client.get(PAGE, params)
    assert response.status_code == 200
    page = response.content.decode()
    spec = response.context["spec"]
    f = parse_filters(QueryDict(urlencode(params)))
    bar = layout_page.layout_bar(
        _report(),
        response.wsgi_request.user,
        spec,
        f,
        [],
        response.context["layout_dated"],
        response.context["layout_sort_ok"],
    )
    assert _template_selects(page) == _model_selects(bar)


@pytest.mark.parametrize(
    ("layout", "fields"),
    [
        ("board", {"by": "dept"}),
        ("calendar", {"by": "start", "by2": "end"}),
        ("timeline", {"by": "start", "by2": "end", "group": "dept"}),
        ("chart", {"by": "dept", "value": COUNT}),
        ("pivot", {"by": "dept", "by2": "name"}),
    ],
)
def test_hidden_columns_are_never_offered(layout: str, fields: dict[str, Any]) -> None:
    """A column the viewer may not see is in no select's options and in no hidden input (keep). The same bar offers
    it to a viewer who may see it, so the check is not vacuous."""
    report = _report(hidden=True)
    spec = _spec(layout, **fields)
    seen = layout_page.layout_bar(report, _viewer(), spec, Filters(), [], False, True)
    assert any(h in value for s in seen.selects for value, _ in s.options for h in HIDDEN)

    bar = layout_page.layout_bar(report, _viewer("secret.view"), spec, Filters(), [], False, True)
    assert bar.selects, "the layout has no selects"
    for s in bar.selects:
        for value, _ in s.options:
            assert value not in HIDDEN, (s.name, value)
        assert s.selected not in HIDDEN, (s.name, s.selected)
    for name, value in bar.keep:
        assert name not in HIDDEN and value not in HIDDEN, (name, value)
