"""Tests for the chart's Excel export: a native chart object, the same numbers as the screen, and the same rules."""

from collections.abc import Callable
from io import BytesIO

import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse
from openpyxl import load_workbook

from assistant.chart_data import ChartData
from assistant.chart_xlsx import chart_workbook
from assistant.tests.helpers import hire_one

pytestmark = pytest.mark.django_db

URL = reverse("assistant:chart_xlsx")


def _open(content: bytes):  # type: ignore[no-untyped-def]
    return load_workbook(BytesIO(content))


@pytest.mark.parametrize("kind", ["bar", "pie"])
def test_export_has_a_native_chart_and_the_numbers(client: Client, role_user: Callable[[str], User], kind: str) -> None:
    hire_one(role_user("hr"))
    client.force_login(role_user("hr"))
    response = client.get(URL, {"kind": kind, "by": "department", "query": ""})
    assert response.status_code == 200
    assert "spreadsheetml" in response["Content-Type"]
    ws = _open(response.content).active
    assert len(ws._charts) == 1
    assert type(ws._charts[0]).__name__ == ("PieChart" if kind == "pie" else "BarChart")
    assert ws["B2"].value == 1
    assert ws.cell(row=ws.max_row, column=1).value == "Нийт"


def test_label_starting_with_equals_is_text() -> None:
    data = ChartData(kind="bar", by="department", by_label="Хэлтэс", labels=("=1+1",), counts=(2,), total=2)
    ws = _open(chart_workbook(data)).active
    assert ws["A2"].data_type == "s"
    assert ws["A2"].value == "=1+1"


def test_export_rules(client: Client, role_user: Callable[[str], User]) -> None:
    assert client.get(URL, {"kind": "bar", "by": "department"}).status_code == 302  # login
    client.force_login(role_user("hr"))
    assert client.get(URL, {"kind": "line", "by": "department"}).status_code == 400
    assert client.get(URL, {"kind": "bar", "by": "nope"}).status_code == 400
    client.force_login(role_user("staff"))
    assert client.get(URL, {"kind": "bar", "by": "department"}).status_code == 403


def test_pane_offers_the_excel_link(client: Client, role_user: Callable[[str], User]) -> None:
    hire_one(role_user("hr"))
    client.force_login(role_user("hr"))
    body = client.get(reverse("assistant:chart"), {"kind": "bar", "by": "department", "query": ""}).content.decode()
    assert "Excel татах" in body and URL in body
