"""The Django view and the request-free service share one drill: the view has no drill helper of its own, and a chart
page's category links are the links the service gives for the same address."""

import inspect
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client

from reports import views
from reports.registry import REPORTS
from reports.services import layout_page
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "layout-view-shares-drill-test"
PAGE = f"/reports/{KEY}/"
DEPTS = ("Санхүү", "Ачаа", None)


def _people() -> list[Any]:
    return [SimpleNamespace(name=f"Ажилтан {n:02d}", dept=DEPTS[n % 3]) for n in range(1, 31)]


@pytest.fixture
def chart_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = Report(
        key=KEY,
        title="Ажилтны тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
        ),
        default_columns=("name", "dept"),
        rows=lambda user, filters: _people(),
        group_options=("dept",),
        layouts=("chart",),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def test_views_has_no_drill_helper_of_its_own() -> None:
    assert "def _drill_url" not in inspect.getsource(views)
    assert not hasattr(views, "_drill_url")


def test_chart_page_hrefs_are_the_service_hrefs(
    client: Client, login_as: Callable[..., User], chart_report: Report
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "chart", "lby": "dept"})
    assert response.status_code == 200
    chart_json = response.context["chart_json"]
    assert any(chart_json["hrefs"]), "the chart should link at least one category"

    request = response.wsgi_request
    user = request.user
    assert isinstance(user, User)
    table = response.context["table"]
    service = layout_page.layout_page(
        QueryDict(),
        PAGE,
        user,
        chart_report,
        table,
        [],
        plain=bool(chart_report.saved_views),
    )
    assert service is not None and service.chart is not None
    assert chart_json["hrefs"] == service.chart.hrefs
