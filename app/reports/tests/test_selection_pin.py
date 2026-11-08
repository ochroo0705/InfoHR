"""Pinned columns on a selectable report: the checkbox column is sticky at the far left and the pinned columns sit after
it (Task B of the selection UI). Without pins, and on other reports or layouts, nothing changes."""

from collections.abc import Callable
from dataclasses import replace
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee

from reports.filters import Filters
from reports.registry import REPORTS
from reports.staff_list import REPORT as STAFF
from reports.table import build_table, pin_style
from reports.tests.conftest import legacy
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

PAGE = "/reports/staff-list/"
# cols is a repeated key; two shown columns, the first two pinned, one totals rule for the footer
TOTALS_QUERY = "?cols=name&cols=years_worked&totals=years_worked%3Asum"
PINNED = TOTALS_QUERY + "&pin=2"
CHECK_LEFT = "left: 0rem"
FIRST_LEFT = "left: 2.5rem"  # the checkbox column is 2.5rem wide
SECOND_LEFT = "left: 14.5rem"  # one pinned column is 12rem


class _Cells(HTMLParser):
    """Every td and th of the first table section asked for, with its attributes, in page order."""

    def __init__(self) -> None:
        super().__init__()
        self.cells: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("td", "th"):
            self.cells.append(dict(attrs))


def _section(html: str, name: str) -> str:
    return html.split(f"<{name}>")[1].split(f"</{name}>")[0]


def _cells(html: str, name: str, count: int) -> list[dict[str, str | None]]:
    parser = _Cells()
    parser.feed(_section(html, name))
    return parser.cells[:count]


def _style(cell: dict[str, str | None]) -> str:
    return cell.get("style") or ""


def _is_sticky(cell: dict[str, str | None]) -> bool:
    return "sticky" in (cell.get("class") or "").split()


@pytest.fixture
def staff(actor: User, job_values: dict[str, Any]) -> list[Employee]:
    return [legacy(actor, job_values) for _ in range(2)]


def _check_offsets(html: str, name: str) -> None:
    """The checkbox cell is sticky at 0, the two pinned cells after it."""
    check, first, second = _cells(html, name, 3)
    assert _is_sticky(check) and _style(check) == CHECK_LEFT
    assert _style(first) == FIRST_LEFT and _style(second) == SECOND_LEFT


def test_header_body_and_footer_offsets_after_the_checkbox(
    client: Client, login_hr: User, staff: list[Employee]
) -> None:
    html = client.get(PAGE + PINNED).content.decode()
    _check_offsets(html, "thead")
    _check_offsets(html, "tbody")
    _check_offsets(html, "tfoot")


def test_checkbox_cells_are_not_pinned_without_pins(client: Client, login_hr: User, staff: list[Employee]) -> None:
    html = client.get(PAGE, {"cols": ["name", "years_worked"]}).content.decode()
    header_check = _cells(html, "thead", 1)[0]
    body_check = _cells(html, "tbody", 1)[0]
    for cell in (header_check, body_check):
        assert cell.get("class") == "w-10"  # exactly the plain width class, no sticky classes
        assert "style" not in cell  # and no inline offset
        assert "sticky" not in (cell.get("class") or "").split()


def test_footer_checkbox_cell_is_plain_without_pins(client: Client, login_hr: User, staff: list[Employee]) -> None:
    html = client.get(PAGE + TOTALS_QUERY).content.decode()  # selectable, a totals rule, no pin
    assert "data-select-all" in html and "<tfoot>" in html
    leading = _cells(html, "tfoot", 1)[0]
    assert "class" not in leading and "style" not in leading
    assert "left: 0rem" not in _section(html, "tfoot")


def test_non_selectable_report_keeps_its_pin_offsets(
    client: Client, monkeypatch: pytest.MonkeyPatch, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    monkeypatch.setitem(REPORTS, "staff-plain", replace(STAFF, key="staff-plain", person=None))
    login_as(client, "HR", "plain-pin-viewer")
    html = client.get("/reports/staff-plain/" + PINNED).content.decode()
    first, second = _cells(html, "thead", 2)
    assert _style(first) == "left: 0rem" and _style(second) == "left: 12rem"
    assert "data-select-all" not in html and "2.5rem" not in html


@pytest.mark.parametrize("layout", ["cards", "board"])
def test_other_layouts_are_unaffected(client: Client, login_hr: User, staff: list[Employee], layout: str) -> None:
    html = client.get(PAGE + "?pin=2&layout=" + layout).content.decode()
    assert "data-select-all" not in html and "left: 2.5rem" not in html


def test_pin_style_offsets_each_pinned_column() -> None:
    assert pin_style(0, 2) == "left: 0rem"
    assert pin_style(1, 2) == "left: 12rem"
    assert pin_style(2, 2) == ""  # not pinned: at or past the pin count
    assert pin_style(0, 0) == ""


def test_pin_style_adds_the_base_before_the_pinned_columns() -> None:
    assert pin_style(0, 2, 2.5) == "left: 2.5rem"
    assert pin_style(1, 2, 2.5) == "left: 14.5rem"  # 2.5rem checkbox plus one 12rem column
    assert pin_style(0, 0, 2.5) == ""  # no pin, no offset, even with a base


def test_clamp_to_the_shown_columns_keeps_the_offsets_consistent(
    client: Client, login_hr: User, staff: list[Employee]
) -> None:
    html = client.get(PAGE + TOTALS_QUERY + "&pin=3").content.decode()  # two columns shown
    cells = _cells(html, "thead", 10)
    assert len(cells) == 3  # the checkbox column and the two shown columns, nothing more
    check, first, second = cells
    assert _style(check) == CHECK_LEFT
    assert _style(first) == FIRST_LEFT and _style(second) == SECOND_LEFT  # the pin of 3 stops at the two shown columns


def test_no_shown_columns_means_no_pin_and_no_base(hr_user: User) -> None:
    """A pin on a table with no visible column is clamped to 0, so the checkbox offset is not applied either."""
    report = Report(
        key="clamp-test",
        title="Туршилт",
        filters=(),
        columns=(Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary"),),
        default_columns=("pay",),
        rows=lambda user, filters: [SimpleNamespace(id=7, pay=1)],
        person=lambda r: r.id,
    )
    table = build_table(report, hr_user, Filters(pin=3))  # the HR user may not see the salary column
    assert table.columns == []
    assert table.pin == 0 and table.pin_base == 0
