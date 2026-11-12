"""The opted-in reports offer the views they declare and answer 200 on each; hostile addresses never give a 500 or echo
raw markup; a saved view's layout column is cleaned for a viewer without its permission; a table-only report ignores
?layout=board."""

from collections.abc import Callable
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.test import Client

from reports.layouts import offered_layouts
from reports.models import SavedView
from reports.registry import REPORTS
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

# The views each opted-in report offers, for an Admin (who holds every report permission). A report not listed here
# offers the table only.
EXPECTED: dict[str, list[str]] = {
    "staff-list": ["table", "board", "calendar", "timeline", "cards", "chart", "pivot"],
    "leave-requests": ["table", "board", "calendar", "timeline", "cards", "chart", "pivot"],
    "orders": ["table", "board", "calendar", "cards", "chart", "pivot"],
    "movements": ["table", "calendar", "timeline", "chart"],
}

LAYOUTS = ("board", "calendar", "timeline", "cards", "chart", "pivot")
# base.html's inline theme script contains a bare <script> tag, so the test checks for this payload, not for the tag
PAYLOAD = "<script>alert(1)</script>"
PARAMS = ("layout", "lby", "lby2", "lval", "lchart", "lmonth")
VALUES = ['"', PAYLOAD, "x" * 5000, "Ажилтан ✓ ü", "%00%FF"]
SPECIAL = (
    "lmonth=9999-99",
    "lval=a:b:c",
    "layout=pivot&lby2=lby",
    "lby=pay",
    "lby=department&lby=name",
    "layout=board&layout=chart",
    "lmonth=0000-01",
    "lby2=department&lby2=position",
    "lval=pay:median",
    "lval=count&lval=salary:sum",
)
# 6 parameters x 5 values, plus 10 repeated or malformed addresses: 40 in all
HOSTILE: list[str] = [urlencode({param: value}) for param in PARAMS for value in VALUES] + list(SPECIAL)
assert len(HOSTILE) == 40


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_opted_in_report_offers_its_views_and_each_answers_200(
    client: Client, login_as: Callable[..., User], key: str
) -> None:
    user = login_as(client, "Admin", "layout-admin")
    offered = offered_layouts(REPORTS[key], user)
    assert offered == EXPECTED[key]
    for name in offered[1:]:
        resp = client.get(f"/reports/{key}/", {"layout": name, "lyear": "all"})
        assert resp.status_code == 200, name


def test_only_the_planned_reports_opt_in() -> None:
    # every row report offers the views (registry._with_tools); a statistic report stays a table, except
    # headcount-trend, which is statistic (one row per month) but declares its own chart
    assert {key for key, report in REPORTS.items() if report.layouts} == {
        key for key, report in REPORTS.items() if report.shows_count or key == "headcount-trend"
    }


@pytest.mark.parametrize("probe", HOSTILE, ids=[str(n) for n in range(len(HOSTILE))])
def test_hostile_address_on_the_staff_list_gives_no_500_and_no_raw_markup(
    client: Client, login_as: Callable[..., User], hired: object, left_employee: object, probe: str
) -> None:
    login_as(client, "Admin", "hostile-admin")
    for name in LAYOUTS:
        resp = client.get(f"/reports/staff-list/?layout={name}&lyear=all&{probe}")
        assert resp.status_code == 200, (name, probe[:80])
        html = resp.content.decode()
        assert PAYLOAD not in html, (name, probe[:80])
        assert "<script>alert" not in html, (name, probe[:80])


def test_saved_view_drops_a_salary_value_for_a_viewer_without_the_permission(
    client: Client, login_as: Callable[..., User]
) -> None:
    SavedView.objects.create(
        report="staff-list",
        name="Цалингийн диаграм",
        query="layout=chart&lby=department&lval=salary:sum",
        is_default=True,
    )
    login_as(client, "HR", "hostile-hr")  # HR holds view_employees but not macs.view_salary
    resp = client.get("/reports/staff-list/")
    assert resp.status_code == 302
    location = resp["Location"]
    assert "layout=chart" in location and "lby=department" in location
    assert "lval" not in location and "salary" not in location
    page = Client()
    login_as(page, "HR", "hostile-hr-page")
    html = page.get("/reports/staff-list/?layout=chart&lby=department").content.decode()
    # lval=count is the chart's own default and stays; the salary aggregate must not appear anywhere on the page
    assert "salary:sum" not in html and "salary%3Asum" not in html and "lval=salary" not in html


def test_saved_view_keeps_its_salary_value_for_a_viewer_with_the_permission(
    client: Client, login_as: Callable[..., User]
) -> None:
    SavedView.objects.create(
        report="staff-list",
        name="Цалингийн диаграм",
        query="layout=chart&lby=department&lval=salary:sum",
        is_default=True,
    )
    login_as(client, "Admin", "hostile-admin-view")
    resp = client.get("/reports/staff-list/")
    assert resp.status_code == 302 and "salary" in resp["Location"]


@pytest.fixture
def plain_only(monkeypatch: pytest.MonkeyPatch) -> Report:
    """A report that declares no layouts: ?layout=board must show the table, with no switcher."""
    report = Report(
        key="hostile-plain",
        title="Энгийн тайлан",
        filters=(),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),),
        default_columns=("name",),
        rows=lambda user, filters: [SimpleNamespace(name=f"Ажилтан {n:02d}") for n in range(1, 4)],
    )
    monkeypatch.setitem(REPORTS, "hostile-plain", report)
    return report


def test_table_only_report_shows_the_table_for_a_board_address(
    client: Client, login_as: Callable[..., User], plain_only: Report
) -> None:
    login_as(client, "Admin", "hostile-plain-admin")
    page = client.get("/reports/hostile-plain/?layout=board").content.decode()
    assert "Ажилтан 01" in page
    assert 'aria-current="true"' not in page
