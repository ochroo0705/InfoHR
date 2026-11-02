"""The report page shows its rows in batches; print and Excel keep every row (UI_RULES §4 batches)."""

import io
import re
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from accounts.models import User
from config import batching
from django.test import Client
from django.urls import reverse
from openpyxl import load_workbook

from reports.registry import REPORTS
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

ROWS = 12
PAGE = "/reports/many/"
HTMX = {"HX-Request": "true"}
PILL = "Цааш харуулах"


def _names(html: str) -> list[str]:
    """The person names in the page or fragment, in order."""
    return re.findall(r"Ажилтан \d\d", html)


def _expected(first: int, last: int) -> list[str]:
    return [f"Ажилтан {n:02d}" for n in range(first, last + 1)]


@pytest.fixture
def many_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """A report of 12 people in two departments, registered as «many»."""
    people = [
        SimpleNamespace(name=f"Ажилтан {n:02d}", dept="Санхүү" if n % 2 else "Борлуулалт") for n in range(1, ROWS + 1)
    ]
    report = Report(
        key="many",
        title="Олон мөр",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept),
        ),
        default_columns=("name",),
        rows=lambda user, filters: people,
        group_options=("dept",),
    )
    monkeypatch.setitem(REPORTS, "many", report)
    return report


@pytest.fixture
def small_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 5)


@pytest.fixture
def hr_client(client: Client, login_as: Callable[..., User], many_report: Report, small_batches: None) -> Client:
    login_as(client, "HR")  # view_reports and export_lists
    return client


def test_report_page_shows_first_batch_only(hr_client: Client) -> None:
    page = hr_client.get(PAGE).content.decode()
    assert _names(page) == _expected(1, 5)
    assert PILL in page
    assert f"{PAGE}?offset=5" in page


def test_next_batch_returns_rows_6_to_10(hr_client: Client) -> None:
    response = hr_client.get(f"{PAGE}?offset=5", headers=HTMX)
    fragment = response.content.decode()
    assert _names(fragment) == _expected(6, 10)
    assert f"{PAGE}?offset=10" in fragment
    assert "HX-Push-Url" not in response
    assert "<html" not in fragment  # rows only, no page around them


def test_last_batch_has_no_load_more_trigger(hr_client: Client) -> None:
    fragment = hr_client.get(f"{PAGE}?offset=10", headers=HTMX).content.decode()
    assert _names(fragment) == _expected(11, 12)
    assert PILL not in fragment


def test_pasted_offset_link_opens_first_batch(hr_client: Client) -> None:
    page = hr_client.get(f"{PAGE}?offset=5").content.decode()  # not an htmx request
    assert _names(page) == _expected(1, 5)


def test_load_more_keeps_sort(hr_client: Client) -> None:
    page = hr_client.get(f"{PAGE}?sort=-name").content.decode()
    assert "sort=-name&amp;offset=5" in page  # the pill carries the same query string plus the offset


def test_grouped_report_shows_every_row(hr_client: Client) -> None:
    page = hr_client.get(f"{PAGE}?group=dept").content.decode()
    assert len(_names(page)) == ROWS
    assert PILL not in page


def test_print_and_excel_keep_every_row(hr_client: Client) -> None:
    printed = hr_client.get(reverse("reports:print", args=["many"])).content.decode()
    assert _names(printed) == _expected(1, ROWS)

    response = hr_client.get(reverse("reports:excel", args=["many"]))
    sheet = load_workbook(io.BytesIO(response.content)).active
    assert sheet is not None
    names = [sheet.cell(row=r, column=1).value for r in range(1, sheet.max_row + 1)]
    assert [n for n in names if isinstance(n, str) and n.startswith("Ажилтан")] == _expected(1, ROWS)
