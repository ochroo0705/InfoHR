"""New layout address parameters: lgrain, lshow, lsort, lorder, lrep, lweek, lyear, lgroup, lval2.

A bad value reads as the default, a column the viewer may not see is dropped, and each parameter is written only for
the layouts that use it."""

from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from reports.filters import Filters, parse_filters, to_query
from reports.layouts import LayoutSpec, clean_params, resolve, used_params
from reports.registry import REPORTS
from reports.table import restricted_filters
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

NEW = ("lgrain", "lshow", "lsort", "lorder", "lrep", "lweek", "lyear", "lgroup", "lval2")
LAYOUTS = ("table", "board", "calendar", "timeline", "cards", "chart", "pivot")

DEPT = Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text")
PAY = Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary", numeric=True, money=True)
START = Column(key="start", label="Эхлэх", value=lambda r: r.start, kind="date")
END = Column(key="end", label="Дуусах", value=lambda r: r.end, kind="date")
SECRET = Column(key="secret", label="Нууц", value=lambda r: r.secret, needs="x.y")


def _parse(raw: str) -> Filters:
    return parse_filters(QueryDict(raw))


def _report(layouts: tuple[str, ...], group_options: tuple[str, ...] = ("dept", "secret")) -> Report:
    return Report(
        key="layout-params-new",
        title="Тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
            DEPT,
            START,
            END,
            PAY,
            SECRET,
        ),
        default_columns=("name",),
        rows=lambda user, filters: [],
        group_options=group_options,
        layouts=layouts,
    )


def _spec(layout: str, **extra: Any) -> LayoutSpec:
    return LayoutSpec(
        layout=layout, by=None, by2=None, value=(None, "count"), chart="bar", month=date(2026, 11, 1), **extra
    )


def test_new_params_default_to_empty() -> None:
    f = Filters()
    for name in NEW:
        assert getattr(f, name) == "", name


def test_bad_values_read_as_empty() -> None:
    f = _parse("lgrain=week&lshow=x&lweek=2026-13-40&lyear=99999&lrep=2")
    assert (f.lgrain, f.lshow, f.lweek, f.lyear, f.lrep) == ("", "", "", "", "")


@pytest.mark.parametrize(
    "raw",
    [
        "lsort=desc",
        "lorder=name",
        "lgroup=" + "a" * 5000,
        "lval2=pay:median",
        "lweek=2026-02-30",
        "lyear=1899",
        "lyear=2026.5",
    ],
)
def test_more_bad_values_read_as_empty(raw: str) -> None:
    f = _parse(raw)
    assert all(getattr(f, name) == "" for name in NEW)


def test_roundtrip() -> None:
    f = Filters(
        lgrain="quarter",
        lshow="pct",
        lsort="value",
        lorder="count",
        lrep="0",
        lweek="2026-11-09",
        lyear="2026",
        lgroup="dept",
        lval2="pay:sum",
    )
    assert _parse(to_query(f)) == f


def test_hidden_column_dropped(accountant_user: User) -> None:
    report = _report(("timeline", "pivot"))
    cleaned = clean_params(report, accountant_user, _parse("layout=timeline&lgroup=secret&lval2=secret:sum"))
    assert cleaned["lgroup"] == ""
    assert cleaned["lval2"] == ""


def test_visible_columns_are_kept(accountant_user: User) -> None:
    report = _report(("timeline", "pivot"))
    cleaned = clean_params(report, accountant_user, _parse("layout=pivot&lgroup=dept&lval2=pay:sum"))
    assert cleaned["lgroup"] == "dept"
    assert cleaned["lval2"] == "pay:sum"


def test_clean_params_returns_the_new_keys(accountant_user: User) -> None:
    cleaned = clean_params(_report(("timeline",)), accountant_user, _parse("layout=timeline&lyear=2026"))
    assert set(cleaned) == {"layout", "lby", "lby2", "lval", "lchart", "lmonth", *NEW}
    assert cleaned["lyear"] == "2026"


def test_old_address_unchanged(accountant_user: User) -> None:
    report = _report(("board",))
    f = _parse("layout=board&lby=dept")
    spec = resolve(report, accountant_user, f)
    assert used_params(f, spec) == Filters(layout="board", lby="dept")


def test_table_writes_none_of_the_new_parameters() -> None:
    f = _parse(
        "lgrain=quarter&lshow=pct&lsort=value&lorder=count&lrep=1&lweek=2026-11-09&lyear=2026&lgroup=dept&lval2=pay:sum"
    )
    used = used_params(f, _spec("table"))
    for name in NEW:
        assert getattr(used, name) == "", name


USES: dict[str, tuple[str, ...]] = {
    "lgrain": ("chart", "pivot"),
    "lshow": ("chart", "pivot"),
    "lsort": ("chart",),
    "lval2": ("pivot",),
    "lrep": ("calendar",),
    "lweek": ("calendar",),
    "lyear": ("timeline",),
    "lgroup": ("timeline",),
    "lorder": ("board",),
}
WRITTEN = {
    "lgrain": "quarter",
    "lshow": "pct",
    "lsort": "value",
    "lval2": "pay:sum",
    "lrep": "1",
    "lweek": "2026-11-09",
    "lyear": "2026",
    "lgroup": "dept",
    "lorder": "count",
}


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("name", list(USES))
def test_each_parameter_is_written_only_for_its_layouts(name: str, layout: str) -> None:
    spec = _spec(
        layout,
        grain="quarter",
        show="pct",
        sort="value",
        order="count",
        rep=True,
        week=date(2026, 11, 9),
        year=2026,
        group=DEPT,
        value2=(PAY, "sum"),
    )
    # lrep and lgrain are written from the request's filters ("1" or "0", a grain), not from the spec, so the request
    # carries them here (lgrain since 2026-11-11: an auto-chosen grain is never written)
    # lyear is written from the request too (since 2026-11-11: digits or "all"), so the request carries it here
    used = used_params(Filters(layout=layout, lrep="1", lgrain="quarter", lyear=WRITTEN["lyear"]), spec)
    expected = WRITTEN[name] if layout in USES[name] else ""
    assert getattr(used, name) == expected


def test_defaults_are_not_written() -> None:
    used = used_params(Filters(layout="chart"), _spec("chart", grain="month", sort="", show=""))
    assert used.lgrain == ""
    assert used.lsort == ""
    used = used_params(Filters(layout="calendar"), _spec("calendar", rep=False, week=None))
    assert used.lrep == ""
    assert used.lweek == ""


def test_resolve_reads_the_new_parameters_for_their_layout(accountant_user: User) -> None:
    report = _report(("board", "chart"))
    chart = resolve(report, accountant_user, _parse("layout=chart&lgrain=quarter&lshow=pct&lsort=value"))
    assert (chart.grain, chart.show, chart.sort) == ("quarter", "pct", "value")
    board = resolve(report, accountant_user, _parse("layout=board&lgrain=quarter&lsort=value"))
    assert (board.grain, board.sort) == ("", "")


def test_restricted_filters_drops_hidden_lgroup_and_lval2(accountant_user: User) -> None:
    """A viewer without x.y: the raw address's lgroup and lval2 naming the hidden column never reach the filters."""
    report = _report(("timeline", "pivot"))
    timeline = restricted_filters(report, accountant_user, _parse("layout=timeline&lgroup=secret"))
    pivot = restricted_filters(report, accountant_user, _parse("layout=pivot&lval2=secret:sum"))
    assert timeline.lgroup == ""
    assert pivot.lval2 == ""


def test_restricted_filters_keeps_lgroup_and_lval2_for_a_viewer_with_the_permission(
    accountant_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same call for a viewer who holds x.y: the columns are kept (the viewer may see them)."""
    monkeypatch.setattr(User, "has_perm", lambda self, perm, obj=None: perm == "x.y")
    report = _report(("timeline", "pivot"))
    timeline = restricted_filters(report, accountant_user, _parse("layout=timeline&lgroup=secret"))
    pivot = restricted_filters(report, accountant_user, _parse("layout=pivot&lval2=secret:sum"))
    assert timeline.lgroup == "secret"
    assert pivot.lval2 == "secret:sum"


@pytest.mark.parametrize("value", ["0", "1"])
def test_lrep_is_written_and_read_back_for_the_calendar(accountant_user: User, value: str) -> None:
    report = _report(("calendar",))
    f = _parse(f"layout=calendar&lrep={value}")
    query = to_query(used_params(f, resolve(report, accountant_user, f)))
    assert QueryDict(query).get("lrep") == value
    assert _parse(query).lrep == value


def test_lrep_empty_writes_nothing_for_the_calendar(accountant_user: User) -> None:
    report = _report(("calendar",))
    f = _parse("layout=calendar")
    assert "lrep" not in to_query(used_params(f, resolve(report, accountant_user, f)))


@pytest.mark.parametrize("layout", ["board", "timeline", "chart", "pivot", "cards"])
def test_lrep_is_not_written_for_other_layouts(accountant_user: User, layout: str) -> None:
    report = _report(("board", "timeline", "chart", "pivot", "cards", "calendar"))
    f = _parse(f"layout={layout}&lrep=1&lyear=all")
    assert "lrep" not in to_query(used_params(f, resolve(report, accountant_user, f)))


def test_layout_switch_links_carry_none_of_the_new_parameters(
    client: Client, login_hr: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _report(("board", "timeline", "chart", "pivot", "calendar"), group_options=("dept",))
    monkeypatch.setitem(REPORTS, report.key, report)
    response = client.get(
        reverse("reports:report", args=[report.key]),
        {
            "layout": "chart",
            "lby": "dept",
            "lgrain": "quarter",
            "lshow": "pct",
            "lsort": "value",
            "lorder": "count",
            "lrep": "1",
            "lweek": "2026-11-09",
            "lyear": "2026",
            "lgroup": "dept",
            "lval2": "count",
        },
    )
    assert response.status_code == 200
    urls = response.context["layout_urls"]
    assert len(urls) > 1
    for url in urls.values():
        for name in NEW:
            assert f"{name}=" not in url, (name, url)
