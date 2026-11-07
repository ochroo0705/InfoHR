"""The selection markup of a report page: checkboxes, data-person on the rows, the bar and its URLs (Task 6a)."""

import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

import pytest
from accounts.models import User
from config import batching
from django.contrib.auth.models import Group, Permission
from django.test import Client, RequestFactory
from employees.models import Employee
from employees.services.macs_writes import save_department

from reports import selection
from reports.selection import pick
from reports.staff_list import REPORT as STAFF
from reports.tests.conftest import legacy

pytestmark = pytest.mark.django_db

PAGE = "/reports/staff-list/"
TOTALS_QUERY = "?cols=name&cols=years_worked&totals=years_worked%3Asum"  # cols is a repeated key
BAR_URLS = {
    "excel": "/reports/staff-list/selected/excel/",
    "csv": "/reports/staff-list/selected/csv/",
    "print": "/reports/staff-list/selected/print/",
    "copy": "/reports/staff-list/selected/copy/",
    "checklist": "/reports/staff-list/selected/checklist/",
}


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.found.append((tag, dict(attrs)))


def _tags(html: str) -> list[tuple[str, dict[str, str | None]]]:
    parser = _Tags()
    parser.feed(html)
    return parser.found


def _data_rows(html: str) -> list[dict[str, str | None]]:
    """The attributes of every <tr> that holds a row checkbox (a data row of a selectable table)."""
    rows: list[dict[str, str | None]] = []
    for tag, attrs in _tags(html):
        if tag == "tr" and "data-person" in attrs:
            rows.append(attrs)
    return rows


def _checkboxes(html: str, attr: str) -> list[dict[str, str | None]]:
    return [attrs for tag, attrs in _tags(html) if tag == "input" and attr in attrs]


def _bar(html: str) -> dict[str, str | None]:
    bars = [attrs for tag, attrs in _tags(html) if tag == "div" and attrs.get("id") == "selection-bar"]
    assert len(bars) == 1
    return bars[0]


def _action_buttons(html: str) -> dict[str, str | None]:
    """The bar's action buttons by their data-action, with their data-url."""
    return {
        attrs["data-action"] or "": attrs.get("data-url")
        for tag, attrs in _tags(html)
        if tag == "button" and attrs.get("data-action")
    }


def _without_export(group_name: str) -> None:
    """Take `accounts.export_lists` away from a role group (the accounts migrations give it to HR and Accountant)."""
    export = Permission.objects.get(codename="export_lists", content_type__app_label="accounts")
    Group.objects.get(name=group_name).permissions.remove(export)


@pytest.fixture
def staff(actor: User, job_values: dict[str, Any]) -> list[Employee]:
    """Four people on the staff list, so a batch of three leaves one for the next batch."""
    return [legacy(actor, job_values) for _ in range(4)]


def test_staff_list_offers_selection_to_hr(client: Client, login_hr: User, staff: list[Employee]) -> None:
    html = client.get(PAGE).content.decode()
    rows = _data_rows(html)
    assert {r["data-person"] for r in rows} == {str(e.pk) for e in staff}
    assert len(_checkboxes(html, "data-select-row")) == len(rows) == len(staff)
    assert len(_checkboxes(html, "data-select-all")) == 1
    bar = _bar(html)
    assert "hidden" in bar
    assert "flex-wrap" in (bar.get("class") or "").split()
    assert bar["data-query"] is not None
    assert "data-select-matching" in html and f"Бүх {len(staff)} мөрийг сонгох" in html
    assert "data-count" in html and "data-select-cancel" in html


def test_bar_carries_the_four_urls_and_the_checklist_button(
    client: Client, login_hr: User, staff: list[Employee]
) -> None:
    buttons = _action_buttons(client.get(PAGE).content.decode())
    assert buttons == BAR_URLS


def test_bar_carries_the_report_query(client: Client, login_hr: User, staff: list[Employee]) -> None:
    html = client.get(PAGE, {"state": "left"}).content.decode()
    assert "state=left" in (_bar(html)["data-query"] or "")


def test_report_that_does_not_opt_in_has_no_selection(
    client: Client, monkeypatch: pytest.MonkeyPatch, login_as: Callable[..., User]
) -> None:
    from dataclasses import replace

    from reports.registry import REPORTS

    plain = replace(STAFF, key="staff-plain", person=None)
    monkeypatch.setitem(REPORTS, "staff-plain", plain)
    login_as(client, "HR", "plain-viewer")
    html = client.get("/reports/staff-plain/").content.decode()
    assert "selection-bar" not in html
    assert "data-select-row" not in html and "data-select-all" not in html
    assert "data-person" not in html


@pytest.mark.parametrize("layout", ["cards", "board"])
def test_other_layouts_have_no_selection(client: Client, login_hr: User, staff: list[Employee], layout: str) -> None:
    html = client.get(PAGE, {"layout": layout}).content.decode()
    assert "selection-bar" not in html
    assert "data-select-row" not in html and "data-select-all" not in html
    assert "data-person" not in html


def test_user_without_export_permission_has_no_excel_or_csv(
    client: Client, login_hr: User, staff: list[Employee]
) -> None:
    _without_export("HR")
    buttons = _action_buttons(client.get(PAGE).content.decode())
    assert "excel" not in buttons and "csv" not in buttons
    assert buttons["print"] == BAR_URLS["print"] and buttons["copy"] == BAR_URLS["copy"]


def test_user_without_can_start_has_no_checklist_button(
    client: Client, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    login_as(client, "Accountant", "no-start-viewer")  # the accountant may open the report but not start a termination
    buttons = _action_buttons(client.get(PAGE).content.decode())
    assert "checklist" not in buttons
    assert buttons["excel"] == BAR_URLS["excel"] and buttons["print"] == BAR_URLS["print"]


def test_grouped_rows_carry_person(client: Client, login_hr: User, staff: list[Employee]) -> None:
    html = client.get(PAGE, {"group": "department"}).content.decode()
    rows = _data_rows(html)
    assert {r["data-person"] for r in rows} == {str(e.pk) for e in staff}
    assert len(_checkboxes(html, "data-select-row")) == len(staff)


def test_batch_rows_carry_person(
    client: Client, login_hr: User, staff: list[Employee], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 3)
    first = client.get(PAGE).content.decode()
    assert len(_data_rows(first)) == 3
    assert "data-more-batch" in first  # the «Цааш харуулах» pill is there
    second = client.get(PAGE, {"offset": 3}, HTTP_HX_REQUEST="true").content.decode()
    rows = _data_rows(second)
    assert len(rows) == 1 and rows[0]["data-person"] is not None
    assert len(_checkboxes(second, "data-select-row")) == 1
    assert "data-select-all" not in second  # the header checkbox belongs to the first batch's table


def test_batch_pill_span_counts_the_checkbox(
    client: Client, login_hr: User, staff: list[Employee], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 3)
    html = client.get(PAGE).content.decode()
    spans = [int(m) for m in re.findall(r'data-more-row><td colspan="(\d+)"', html)]
    head = html.split("<thead>")[1].split("</thead>")[0]
    assert spans == [head.count("<th")]  # the pill spans every column, the checkbox one included


def test_bar_query_and_row_ids_post_back_to_the_same_people(
    client: Client, login_hr: User, staff: list[Employee]
) -> None:
    html = client.get(PAGE, {"state": "all"}).content.decode()
    query = _bar(html)["data-query"] or ""
    ids = [r["data-person"] or "" for r in _data_rows(html)]
    resp = client.post(BAR_URLS["copy"], {"query": query, "ids": ids})
    assert resp.status_code == 200
    assert resp.json()["count"] == len(staff) and resp.json()["dropped"] == 0


class _Groups(HTMLParser):
    """The person ids of each group of a grouped table, in page order (a group heading cell starts a group)."""

    def __init__(self) -> None:
        super().__init__()
        self.groups: list[list[int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "td" and "font-semibold" in (values.get("class") or ""):
            self.groups.append([])
        if tag == "tr" and "data-person" in values:
            self.groups[-1].append(int(values["data-person"] or 0))


def _section_count(html: str, section: str, tag: str) -> int:
    """How many <tag> cells a table section holds."""
    part = html.split(f"<{section}>")[1].split(f"</{section}>")[0]
    return part.count(f"<{tag}")


def _button(html: str, attr: str) -> dict[str, str | None]:
    found = [attrs for tag, attrs in _tags(html) if tag in ("button", "span") and attr in attrs]
    assert len(found) == 1, f"expected one element with {attr}"
    return found[0]


def test_footer_lines_up_under_the_header_when_selectable(
    client: Client, login_hr: User, staff: list[Employee]
) -> None:
    html = client.get(PAGE + TOTALS_QUERY).content.decode()
    assert "<tfoot>" in html
    assert _section_count(html, "tfoot", "td") == _section_count(html, "thead", "th")


def test_footer_unchanged_when_not_selectable(
    client: Client, monkeypatch: pytest.MonkeyPatch, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    from dataclasses import replace

    from reports.registry import REPORTS

    monkeypatch.setitem(REPORTS, "staff-plain", replace(STAFF, key="staff-plain", person=None))
    login_as(client, "HR", "plain-footer-viewer")
    html = client.get("/reports/staff-plain/" + TOTALS_QUERY).content.decode()
    assert "<tfoot>" in html
    assert _section_count(html, "tfoot", "td") == _section_count(html, "thead", "th")
    assert "data-select-all" not in html


def test_empty_and_group_rows_span_the_checkbox_column(client: Client, login_hr: User, staff: list[Employee]) -> None:
    empty = client.get(PAGE, {"state": "left"}).content.decode()
    assert "Өгөгдөл олдсонгүй" in empty
    head = _section_count(empty, "thead", "th")
    assert f'colspan="{head}"' in empty
    grouped = client.get(PAGE, {"group": "department"}).content.decode()
    spans = re.findall(r'<td colspan="(\d+)" class="font-semibold', grouped)
    assert spans and {int(s) for s in spans} == {_section_count(grouped, "thead", "th")}


def test_select_matching_is_hidden_and_shows_the_total(
    client: Client, login_hr: User, staff: list[Employee], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selection, "MAX_PEOPLE", 10)
    html = client.get(PAGE).content.decode()
    button = _button(html, "data-select-matching")
    assert "hidden" in button
    assert f"Бүх {len(staff)} мөрийг сонгох" in html  # selection_total is the table count
    assert "data-over-cap" not in html
    assert "hidden" in _bar(html)


def test_over_cap_shows_a_note_instead_of_select_matching(
    client: Client, login_hr: User, staff: list[Employee], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selection, "MAX_PEOPLE", 2)
    html = client.get(PAGE).content.decode()
    assert "data-select-matching" not in html
    note = _button(html, "data-over-cap")
    assert "hidden" in note
    assert "2-аас олон мөр сонгох боломжгүй" in html


def test_bar_query_keeps_sort_and_group_in_the_same_order(
    client: Client, login_hr: User, actor: User, job_values: dict[str, Any], staff: list[Employee]
) -> None:
    other = save_department("Ачаа")
    for _ in range(2):
        legacy(actor, job_values, department=other)
    html = client.get(PAGE, {"group": "department", "sort": "-code"}).content.decode()
    parser = _Groups()
    parser.feed(html)
    page_groups = parser.groups
    assert len(page_groups) == 2
    ids = [pk for group in page_groups for pk in group]
    request = RequestFactory().post("/x/", {"query": _bar(html)["data-query"] or "", "ids": [str(i) for i in ids]})
    request.user = login_hr
    picked = pick(request, login_hr, STAFF)
    assert sorted(picked.ids) == sorted(ids) and picked.dropped == 0
    for group in page_groups:
        assert [pk for pk in picked.ids if pk in group] == group  # the sort holds inside each group


def test_report_page_loads_the_selection_script(client: Client, login_hr: User, staff: list[Employee]) -> None:
    body = client.get(PAGE).content.decode()
    assert body.count("js/report_select.js") == 1  # loaded once, for signed-in pages (base.html)


def test_toolbar_has_the_select_toggle_on_the_opted_in_staff_list(
    client: Client, login_hr: User, staff: list[Employee]
) -> None:
    html = client.get(PAGE).content.decode()
    toggles = [attrs for tag, attrs in _tags(html) if tag == "button" and "data-select-toggle" in attrs]
    assert len(toggles) == 1
    assert toggles[0]["aria-pressed"] == "false"


def test_report_that_does_not_opt_in_has_no_select_toggle(
    client: Client, monkeypatch: pytest.MonkeyPatch, login_as: Callable[..., User], staff: list[Employee]
) -> None:
    from dataclasses import replace

    from reports.registry import REPORTS

    monkeypatch.setitem(REPORTS, "staff-plain", replace(STAFF, key="staff-plain", person=None))
    login_as(client, "HR", "toggle-plain-viewer")
    html = client.get("/reports/staff-plain/").content.decode()
    assert "data-select-toggle" not in html


@pytest.mark.parametrize("layout", ["cards", "board"])
def test_other_layouts_have_no_select_toggle(
    client: Client, login_hr: User, staff: list[Employee], layout: str
) -> None:
    html = client.get(PAGE, {"layout": layout}).content.decode()
    assert "data-select-toggle" not in html


def test_selection_checkboxes_never_restore_their_state_on_back(
    client: Client, login_hr: User, staff: list[Employee]
) -> None:
    html = client.get(PAGE).content.decode()
    boxes = _checkboxes(html, "data-select-row") + _checkboxes(html, "data-select-all")
    assert len(boxes) == len(staff) + 1
    assert all(attrs.get("autocomplete") == "off" for attrs in boxes)
