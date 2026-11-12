"""Every report keeps saved views and the view switcher (registry._with_tools); statistic reports stay tables."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

from reports.layouts import offered_layouts
from reports.models import SavedView
from reports.registry import ALL_LAYOUTS, REPORTS

pytestmark = pytest.mark.django_db


def test_every_report_keeps_saved_views() -> None:
    assert all(r.saved_views for r in REPORTS.values())


def test_declared_layouts_are_kept() -> None:
    assert REPORTS["movements"].layouts == ("calendar", "timeline", "chart")
    assert REPORTS["orders"].layouts == ("board", "calendar", "cards", "chart", "pivot")


def test_row_reports_without_layouts_get_them_all() -> None:
    assert REPORTS["absences"].layouts == ALL_LAYOUTS


def test_statistic_reports_stay_tables() -> None:
    assert REPORTS["accidents"].layouts == ()
    assert REPORTS["poisoning"].layouts == ()


@pytest.fixture
def staff(hired: Any, actor: User, job_values: dict[str, Any]) -> None:
    """A second person in another department, hired in February, so the staff-based reports and their layouts have
    rows (the sweep would otherwise only run the builders on empty tables)."""
    other = {**job_values, "department": macs_writes.save_department("Борлуулалт")}
    history.hire(hire_values("УБ99112255"), {}, start=date(2026, 2, 3), job=other, salary=Decimal("1800000"), by=actor)


@pytest.mark.parametrize("key", sorted(REPORTS))
def test_every_offered_layout_of_every_report_opens(key: str, client: Client, login_as, staff: None) -> None:
    user: User = login_as(client, "Admin")
    report = REPORTS[key]
    for layout in offered_layouts(report, user)[1:]:
        response = client.get(f"/reports/{key}/?layout={layout}")
        assert response.status_code == 200, f"{key} {layout}"
        response = client.get(f"/reports/{key}/print/?layout={layout}")
        assert response.status_code == 200, f"{key} {layout} print"


def test_row_reports_with_a_suitable_column_offer_a_view(client: Client, login_as) -> None:
    """The sweep above is only meaningful if non-table layouts are offered: every row report that has a category or a
    date column the Admin may see must offer more than the table."""
    user: User = login_as(client, "Admin")
    checked: list[str] = []
    missing: list[str] = []
    for key, report in REPORTS.items():
        if not report.shows_count:
            continue
        allowed = [c for c in report.columns if not c.needs or user.has_perm(c.needs)]
        if not any(c.key in report.group_options or c.kind == "date" for c in allowed):
            continue
        checked.append(key)
        if len(offered_layouts(report, user)) <= 1:
            missing.append(key)
    assert checked, "no report to check: the test would prove nothing"
    assert missing == []


def test_save_view_pop_up_opens_on_another_report(client: Client, login_as) -> None:
    login_as(client, "Admin")
    response = client.get("/reports/absences/views/new/")
    assert response.status_code == 200


def test_default_view_redirect_works_on_another_report(client: Client, login_as) -> None:
    user: User = login_as(client, "Admin")
    SavedView.objects.create(
        report="orders", name="x", query="sort=-date", visibility="shared", is_default=True, author=user
    )
    response = client.get("/reports/orders/")
    assert response.status_code == 302
    assert "sort=-date" in response["Location"]
    assert client.get("/reports/orders/?view=plain").status_code == 200
