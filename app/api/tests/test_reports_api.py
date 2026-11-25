"""GET /api/v1/reports/catalogue: the report catalogue's sections as the React page reads them. The rules come from
reports.services.catalogue_page; these tests pin the API's shape, its rights (401 without a login, 403 without
reports.view_reports) and that each card's search text is the text the Django catalogue template puts in data-search."""

import html
import re
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from reports.catalogue import CATALOGUE, Entry
from reports.registry import REPORTS
from reports.services import catalogue_page
from reports.types import Report

from api.tests.logs_support import FORBIDDEN, NOT_LOGGED_IN

pytestmark = pytest.mark.django_db

URL = "/api/v1/reports/catalogue"


def _client(role: str | None) -> Client:
    client = Client()
    if role is not None:
        user = User.objects.create_user(f"reports_api_{role.lower()}", password="x-long-pass-123")  # noqa: S106
        user.groups.add(Group.objects.get(name=role))
        client.force_login(User.objects.get(pk=user.pk))
    return client


def _get(client: Client) -> dict[str, Any]:
    response = client.get(URL)
    assert response.status_code == 200, response.content.decode()
    assert response.json().keys() == {"sections"}
    body: dict[str, Any] = response.json()
    return body


def _cards(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [card for section in body["sections"] for card in section["rows"]]


def test_catalogue_api_requires_login() -> None:
    response = _client(None).get(URL)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_catalogue_api_403_without_view_reports() -> None:
    response = _client("Employee").get(URL)
    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_catalogue_api_card_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every catalogue entry is built by now, so an unbuilt one is added for this test only.
    later = Entry("not-built-yet", "other", "Хийгдээгүй тайлан", "", "Удахгүй", ())
    monkeypatch.setattr(catalogue_page, "CATALOGUE", (*CATALOGUE, later))
    cards = {card["key"]: card for card in _cards(_get(_client("HR")))}
    assert set(cards["performance"]) == {"key", "title", "description", "search", "link", "empty", "path"}
    assert cards["performance"]["link"] is True
    assert cards["performance"]["path"] == "/reports/performance/"
    assert cards["not-built-yet"]["link"] is False
    assert cards["not-built-yet"]["path"] == ""


def test_catalogue_api_card_shape_matches_template_search_text() -> None:
    # The template writes data-search from title, old form, description and each alias (space-joined); the API's
    # search must be the same text card for card, in the same order.
    client = _client("HR")
    page = client.get("/reports/").content.decode()
    template_search = [html.unescape(text) for text in re.findall(r'data-search="([^"]*)"', page)]
    api_search = [card["search"] for card in _cards(_get(client))]
    assert api_search == template_search
    assert len(api_search) > 0


def test_catalogue_api_omits_group_with_no_visible_row(monkeypatch: pytest.MonkeyPatch) -> None:
    hidden = Report(
        key="staff-list",
        title="Жагсаалт",
        filters=(),
        columns=(),
        default_columns=(),
        rows=lambda user, filters: [],
        needs=("reports.manage_saved_views",),
    )
    monkeypatch.setitem(REPORTS, "staff-list", hidden)
    monkeypatch.setattr(catalogue_page, "CATALOGUE", (Entry("staff-list", "staff", "Жагсаалт", "", "", ()),))
    assert _get(_client("HR")) == {"sections": []}
