from collections.abc import Callable

import pytest
from accounts.models import User
from django.test import Client

from reports.catalogue import CATALOGUE, GROUPS
from reports.models import SavedView
from reports.registry import REPORTS
from reports.types import Report

pytestmark = pytest.mark.django_db


def test_catalogue_has_33_unique_entries_in_known_groups() -> None:
    keys = [e.key for e in CATALOGUE]
    assert len(keys) == 33 and len(set(keys)) == 33
    assert {e.group for e in CATALOGUE} == {code for code, _ in GROUPS}


@pytest.mark.parametrize("role, allowed", [("Admin", True), ("HR", True), ("Accountant", True), ("Employee", False)])
def test_view_reports_granted_by_role(client: Client, login_as: Callable[..., User], role: str, allowed: bool) -> None:
    user = login_as(client, role)
    assert user.has_perm("reports.view_reports") is allowed
    assert user.has_perm("reports.manage_saved_views") is (role == "Admin")


def test_catalogue_lists_every_report_greyed_until_built(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get("/reports/").content.decode()
    assert "Ээлжийн амралтын тайлан" in page and "frmVacReport" in page
    assert page.count("удахгүй") == 33 - len(REPORTS)  # stays true as later tasks register reports
    assert 'href="/reports/performance/"' in page  # built (phase 5, task 8): a link, not greyed


def test_menu_link_only_with_view_reports(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    assert 'href="/reports/"' in client.get("/employees/").content.decode()
    client.logout()
    login_as(client, "Employee", name="emp")
    assert client.get("/reports/").status_code == 403


def test_built_report_is_a_link_and_marks_empty_source(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A built report is a link; its source table (SavedView) has no rows here, so the grey marker shows.
    report = Report(
        key="annual-leave",
        title="Ээлжийн амралт",
        filters=(),
        columns=(),
        default_columns=(),
        rows=lambda user, filters: [],
        source=SavedView,
    )
    monkeypatch.setitem(REPORTS, "annual-leave", report)
    login_as(client, "HR")
    page = client.get("/reports/").content.decode()
    assert 'href="/reports/annual-leave/"' in page
    assert "бүртгэл алга" in page
