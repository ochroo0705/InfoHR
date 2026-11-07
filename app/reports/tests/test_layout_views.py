"""The layout pages: switcher, layout bar address, board and cards, the stubs, and the per-viewer rules."""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees.templatetags.hr import mnt

from reports.filters import parse_filters, to_query
from reports.registry import REPORTS
from reports.table import restricted_filters
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "layout-views-test"
PAGE = f"/reports/{KEY}/"
ROWS = 75  # more than one cards batch (config/batching LIST_BATCH is 60)
DEPTS = ("Санхүү", "Ачаа", None)
SALARY = 8765432  # the value a viewer without macs.view_salary must never see


def _people() -> list[Any]:
    return [
        SimpleNamespace(
            name=f"Ажилтан {n:02d}",
            dept=DEPTS[n % 3],
            start=date(2026, 1 + n % 12, 1),
            pay=SALARY + n,
        )
        for n in range(1, ROWS + 1)
    ]


@pytest.fixture
def views_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = Report(
        key=KEY,
        title="Ажилтны тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),
            Column(key="dept", label="Хэлтэс", value=lambda r: r.dept, kind="text"),
            Column(key="start", label="Эхэлсэн", value=lambda r: r.start, kind="date"),
            Column(
                key="pay",
                label="Цалин",
                value=lambda r: r.pay,
                needs="macs.view_salary",
                numeric=True,
                money=True,
                kind="number",
            ),
        ),
        default_columns=("name", "dept"),
        rows=lambda user, filters: _people(),
        group_options=("dept",),
        layouts=("board", "cards", "calendar", "timeline", "chart", "pivot"),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


@pytest.fixture
def plain_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """A report that offers no layouts: ?layout=board must still show the table."""
    report = Report(
        key=KEY,
        title="Ажилтны тайлан",
        filters=(),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name, kind="text"),),
        default_columns=("name",),
        rows=lambda user, filters: _people(),
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _titles(html: str) -> list[str]:
    return re.findall(r"Ажилтан \d\d", html)


def _with_layouts(report: Report, layouts: tuple[str, ...]) -> Report:
    return replace(report, layouts=layouts)


def _assert_no_pay(page: str) -> None:
    """No salary of any row shows in the page, raw or as the mnt filter formats it, and no «Цалин» label."""
    for person in _people():
        assert str(person.pay) not in page
        assert mnt(person.pay) not in page
    assert "Цалин" not in page


# ---- the board ----


def test_board_lists_lane_labels_and_card_titles(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "board", "lby": "dept"}).content.decode()
    assert "Санхүү · 25" in page  # every 3rd person: 25 of 75 per lane
    assert "Ачаа · 25" in page
    assert "Ажилтан 01" in page


def test_board_with_no_rows_shows_the_empty_text(
    client: Client, login_as: Callable[..., User], views_report: Report, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(REPORTS, KEY, replace(views_report, rows=lambda user, filters: []))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "board", "lby": "dept"}).content.decode()
    assert "Өгөгдөл олдсонгүй" in page


# ---- the cards ----


def test_cards_page_shows_titles_and_the_more_pill(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "cards"}).content.decode()
    assert "Ажилтан 01" in page
    assert "Ажилтан 60" in page
    assert "Ажилтан 61" not in page  # the first batch is 60 cards
    assert "Цааш харуулах" in page


def test_cards_batch_fragment_returns_the_rest_without_a_pill(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    fragment = client.get(PAGE, {"layout": "cards", "offset": "60"}, headers={"HX-Request": "true"}).content.decode()
    assert _titles(fragment) == [f"Ажилтан {n:02d}" for n in range(61, 76)]
    assert "Цааш харуулах" not in fragment


def test_cards_show_extra_columns_as_label_value_lines(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "cards", "cols": ["name", "dept", "start"]}).content.decode()
    assert "Эхэлсэн:" in page


# ---- the switcher ----


def test_switcher_lists_only_the_offered_layouts_with_the_current_marked(
    client: Client, login_as: Callable[..., User], monkeypatch: pytest.MonkeyPatch, views_report: Report
) -> None:
    monkeypatch.setitem(REPORTS, KEY, _with_layouts(views_report, ("board", "cards", "chart")))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "board", "lby": "dept"}).content.decode()
    assert "Самбар" in page
    assert "Карт" in page
    assert "Диаграм" in page
    assert "Хуанли" not in page
    assert "Цагийн шугам" not in page
    assert "Хөрвүүлэлт" not in page
    assert page.count('aria-current="true"') == 1


def test_switcher_is_hidden_when_the_report_offers_no_layout(
    client: Client, login_as: Callable[..., User], plain_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "board"}).content.decode()
    assert 'aria-current="true"' not in page
    assert "Самбар" not in page
    assert "<table" in page  # the table shows instead
    assert "Нэр" in page


# ---- the stubs: every layout answers 200 ----


@pytest.mark.parametrize("layout", ["calendar", "timeline", "chart", "pivot"])
def test_stub_layouts_answer_200(
    client: Client, login_as: Callable[..., User], views_report: Report, layout: str
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": layout})
    assert response.status_code == 200
    assert "Нийт: 75" in response.content.decode()


# ---- the address ----


def test_htmx_response_pushes_an_address_with_the_layout(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "board", "lby": "dept"}, headers={"HX-Request": "true"})
    push = unquote(response["HX-Push-Url"])
    assert "layout=board" in push
    assert "lby=dept" in push


def test_table_layout_is_not_written_to_the_address(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "table", "lby": "dept"}, headers={"HX-Request": "true"})
    assert "layout=" not in response["HX-Push-Url"]
    assert "lby=" not in response["HX-Push-Url"]


def test_resolved_layout_values_are_written_to_the_address(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "board"}, headers={"HX-Request": "true"})
    push = unquote(response["HX-Push-Url"])
    assert "layout=board" in push
    assert "lby=dept" in push  # the first category column, chosen by the layout


def test_layout_survives_a_filter_bar_change(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "board", "lby": "dept"}).content.decode()
    assert '<input type="hidden" name="layout" value="board">' in page


# ---- the per-viewer rules ----


def test_salary_layout_keys_give_no_salary_to_a_viewer_without_the_permission(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "chart", "lval": "pay:sum", "lby": "pay"})
    assert response.status_code == 200
    _assert_no_pay(response.content.decode())


def test_salary_as_board_lane_gives_no_salary_to_a_viewer_without_the_permission(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": "board", "lby": "pay"})
    assert response.status_code == 200
    _assert_no_pay(response.content.decode())


@pytest.mark.parametrize("layout", ["board", "cards", "calendar", "chart"])
def test_hidden_salary_in_every_layout_key_gives_no_salary(
    client: Client, login_as: Callable[..., User], views_report: Report, layout: str
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, {"layout": layout, "lby": "pay", "lby2": "pay", "lval": "pay:sum"})
    assert response.status_code == 200
    _assert_no_pay(response.content.decode())


def test_format_pop_up_keeps_no_hidden_column_key_for_a_viewer_without_the_permission(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    url = reverse("reports:format", args=[KEY])
    response = client.get(url, {"layout": "chart", "lby": "pay", "lval": "pay:sum"})
    assert response.status_code == 200
    page = response.content.decode()
    assert not re.search(r"\bpay\b", page)
    assert "Цалин" not in page


def test_layout_key_of_a_layout_not_offered_is_cleared_for_the_viewer(hr_user: User, plain_report: Report) -> None:
    query = to_query(restricted_filters(plain_report, hr_user, parse_filters(QueryDict("layout=board&lby=name"))))
    assert "layout" not in query
    assert "lby" not in query


def test_salary_column_is_offered_to_the_accountant_on_a_chart(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "Accountant")
    response = client.get(PAGE, {"layout": "chart", "lval": "pay:sum", "lby": "dept"})
    assert response.status_code == 200
    assert "Цалин" in response.content.decode()


# ---- hostile addresses ----


@pytest.mark.parametrize(
    "params",
    [
        {"layout": "board", "lby": '"><script>alert(1)</script>'},
        {"layout": "calendar", "lmonth": "9999-99", "lby": "start"},
        {"layout": "chart", "lval": "a:b:c", "lby": "dept"},
        {"layout": "board", "lby": "x" * 5000},
    ],
)
def test_hostile_layout_addresses_do_not_500(
    client: Client, login_as: Callable[..., User], views_report: Report, params: dict[str, str]
) -> None:
    login_as(client, "HR")
    response = client.get(PAGE, params)
    assert response.status_code == 200
    assert "<script>alert" not in response.content.decode()


HX = {"HX-Request": "true"}


def test_calendar_month_is_left_out_of_the_address_unless_asked_for(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    push = unquote(client.get(PAGE, {"layout": "calendar"}, headers=HX)["HX-Push-Url"])
    assert "layout=calendar" in push
    assert "lmonth=" not in push


def test_calendar_month_asked_for_is_kept_in_the_address(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    push = unquote(client.get(PAGE, {"layout": "calendar", "lmonth": "2026-03"}, headers=HX)["HX-Push-Url"])
    assert "lmonth=2026-03" in push


def test_this_month_asked_for_is_left_out_of_the_address(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    this_month = f"{timezone.localdate():%Y-%m}"
    push = unquote(client.get(PAGE, {"layout": "calendar", "lmonth": this_month}, headers=HX)["HX-Push-Url"])
    assert "lmonth=" not in push


def test_default_bar_chart_is_left_out_and_another_kind_is_kept(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    bar = unquote(client.get(PAGE, {"layout": "chart", "lby": "dept"}, headers=HX)["HX-Push-Url"])
    assert "lchart=" not in bar
    donut = unquote(client.get(PAGE, {"layout": "chart", "lby": "dept", "lchart": "donut"}, headers=HX)["HX-Push-Url"])
    assert "lchart=donut" in donut


def test_board_over_the_cap_shows_the_note_and_the_full_count(
    client: Client, login_as: Callable[..., User], views_report: Report, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [SimpleNamespace(name=f"Ажилтан {n:03d}", dept="Санхүү", start=None, pay=0) for n in range(1, 251)]
    monkeypatch.setitem(REPORTS, KEY, replace(views_report, rows=lambda user, filters: rows))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "board", "lby": "dept"}).content.decode()
    assert "Эхний 200-г харууллаа. Шүүлтүүрээр нарийвчилна уу." in page
    assert "Нийт: 250" in page
    assert "Санхүү · 250" in page


def test_lane_with_rows_past_the_cap_shows_an_ellipsis_not_a_zero(
    client: Client, login_as: Callable[..., User], views_report: Report, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [SimpleNamespace(name=f"А {n:03d}", dept="Санхүү", start=None, pay=0) for n in range(200)]
    rows += [SimpleNamespace(name=f"Б {n:03d}", dept="Ачаа", start=None, pay=0) for n in range(50)]
    monkeypatch.setitem(REPORTS, KEY, replace(views_report, rows=lambda user, filters: rows))
    login_as(client, "HR")
    page = client.get(PAGE, {"layout": "board", "lby": "dept"}).content.decode()
    lane = page.split('aria-label="Ачаа"', 1)[1].split("</section>", 1)[0]
    assert "Ачаа · 50" in lane
    assert "…" in lane
    assert "· 0" not in page


def test_positive_control_the_accountant_sees_the_same_salary_format(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    # the same check as _assert_no_pay, run where the salary is shown: proves the check looks for the real text
    login_as(client, "Accountant")
    page = client.get(PAGE, {"layout": "cards", "cols": ["name", "dept", "pay"]}).content.decode()
    assert mnt(Decimal(SALARY + 1)) in page
    assert "Цалин:" in page


@pytest.mark.parametrize("layout", ["table", "board", "calendar", "timeline", "cards", "chart", "pivot"])
def test_no_django_comment_text_leaks_into_any_layout_page(
    client: Client, login_as: Callable[..., User], views_report: Report, layout: str
) -> None:
    # a multi-line {# ... #} is printed as text; every layout's page must be free of comment markers
    login_as(client, "HR")
    text = client.get(PAGE, {"layout": layout, "lby": "dept"}).content.decode()
    assert "{#" not in text
    assert "#}" not in text


class _Tree(HTMLParser):
    """Records every start tag with the attributes of its open ancestors (void tags never stay open)."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.seen: list[tuple[dict[str, str], list[dict[str, str]]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        self.seen.append((attributes, [attrs_ for _, attrs_ in self.stack]))
        if tag not in self.VOID:
            self.stack.append((tag, attributes))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def test_switcher_is_its_own_row_outside_the_tool_group_and_title_row(
    client: Client, login_as: Callable[..., User], views_report: Report
) -> None:
    login_as(client, "HR")
    html = client.get(PAGE, {"layout": "board", "lby": "dept"}).content.decode()
    tree = _Tree()
    tree.feed(html)
    switcher = [ancestors for attrs, ancestors in tree.seen if attrs.get("aria-label") == "Харагдац"]
    assert len(switcher) == 1
    ancestors = switcher[0]
    assert not any("divide-x" in attrs.get("class", "") for attrs in ancestors)
    assert not any("ml-auto" in attrs.get("class", "") for attrs in ancestors)
    wrapper = ancestors[-1]
    assert "max-w-full" in wrapper.get("class", "") and "overflow-x-auto" in wrapper.get("class", "")
    tool_groups = [
        attrs for attrs, _ in tree.seen if "divide-x" in attrs.get("class", "") and attrs.get("role") != "group"
    ]
    assert tool_groups, "the tool group is on the page"
    assert all("max-w-full" in g["class"] and "overflow-x-auto" in g["class"] for g in tool_groups)
