"""The final review's fixes: the bar keeps the rule tree, totals, colours and pins; a multi-key grouping survives; the
plain-view address; one rule-columns helper; only shown columns are loaded for footers and colours; the log line for
rules; print colours with a hex fallback."""

import dataclasses
import html
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client

from reports import marks as marks_mod
from reports.filters import Filters, describe, parse_filters
from reports.models import SavedView
from reports.registry import REPORTS
from reports.table import build_table
from reports.types import Column, Report
from reports.views import HeaderCell

pytestmark = pytest.mark.django_db

NAME_RULE = '{"op":"and","items":[{"c":"name","o":"neq","v":"zzz"}]}'
COLOUR_MARKS = marks_mod.dump_marks([marks_mod.Mark(column="name", rule_op="neq", value="zzz", colour="red")])
STAFF = "/reports/staff-list/"
HIDDEN = re.compile(r'<input type="hidden" name="(\w+)" value="([^"]*)">')


def _hidden_inputs(page: str) -> dict[str, str]:
    return {name: html.unescape(value) for name, value in HIDDEN.findall(page)}


@pytest.fixture
def grouped_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """A report with no column picker, so its grouping is the bar's «Бүлэглэх» select; two keys may group it."""
    data = [{"dept": "A", "kind": "x", "name": "p"}, {"dept": "B", "kind": "y", "name": "q"}]
    columns = (
        Column(key="dept", label="Хэлтэс", value=lambda r: r["dept"]),
        Column(key="kind", label="Төрөл", value=lambda r: r["kind"]),
        Column(key="name", label="Нэр", value=lambda r: r["name"]),
    )
    report = Report(
        key="grouped",
        title="Бүлэглэх тайлан",
        filters=(),
        columns=columns,
        default_columns=("dept", "kind", "name"),
        rows=lambda user, filters: data,
        group_options=("dept", "kind"),
    )
    monkeypatch.setitem(REPORTS, "grouped", report)
    return report


# ---- 1. the bar form keeps the rules, totals, colours and pins ----


def test_bar_form_carries_rules_totals_marks_and_pin(client: Client, login_hr: User) -> None:
    page = client.get(
        STAFF,
        {"cols": ["name", "code"], "rules": NAME_RULE, "totals": "code:count", "marks": COLOUR_MARKS, "pin": "1"},
    ).content.decode()
    hidden = _hidden_inputs(page)
    assert hidden["rules"] == NAME_RULE
    assert hidden["totals"] == "code:count"
    assert hidden["marks"] == COLOUR_MARKS
    assert hidden["pin"] == "1"


def test_changed_bar_filter_keeps_rules_totals_marks_and_pin(client: Client, login_hr: User) -> None:
    page = client.get(
        STAFF,
        {"cols": ["name", "code"], "rules": NAME_RULE, "totals": "code:count", "marks": COLOUR_MARKS, "pin": "1"},
    ).content.decode()
    # the form submits its hidden inputs and the changed filter (state), as the browser would
    params: dict[str, Any] = {name: value for name, value in _hidden_inputs(page).items() if name != "pin"}
    params["pin"] = _hidden_inputs(page)["pin"]
    params["state"] = "all"
    response = client.get(STAFF, params, HTTP_HX_REQUEST="true")
    pushed = parse_qs(urlsplit(response["HX-Push-Url"]).query)
    assert pushed["state"] == ["all"]
    assert pushed["rules"] == [NAME_RULE]
    assert pushed["totals"] == ["code:count"]
    assert pushed["marks"] == [COLOUR_MARKS]
    assert pushed["pin"] == ["1"]
    table_filters = response.context["table"].filters
    assert table_filters.rules and table_filters.totals and table_filters.marks and table_filters.pin == 1


# ---- 2. a multi-key grouping survives the bar ----


def test_multi_key_group_is_the_selected_option(client: Client, login_hr: User, grouped_report: Report) -> None:
    page = client.get("/reports/grouped/", {"group": "dept,kind"}).content.decode()
    assert '<option value="dept,kind" selected>Хэлтэс · Төрөл</option>' in page
    assert response_table_group(client, "/reports/grouped/", {"group": "dept,kind"}) == "dept,kind"


def test_multi_key_group_pushed_on_a_bar_change(client: Client, login_hr: User, grouped_report: Report) -> None:
    page = client.get("/reports/grouped/", {"group": "dept,kind"}).content.decode()
    params: dict[str, Any] = {"group": "dept,kind", "state": "all"}
    response = client.get("/reports/grouped/", params, HTTP_HX_REQUEST="true")
    assert parse_qs(urlsplit(response["HX-Push-Url"]).query)["group"] == ["dept,kind"]
    assert 'name="group"' in page


def response_table_group(client: Client, url: str, params: dict[str, str]) -> str:
    return str(client.get(url, params).context["table"].filters.group)


# ---- 3. the plain-view address with a default view ----


@pytest.fixture
def default_view(hr_user: User) -> SavedView:
    return SavedView.objects.create(
        report="staff-list", name="Үндсэн", query="cols=name", author=hr_user, is_default=True
    )


def test_bar_clear_link_says_view_plain_with_a_default_view(
    client: Client, login_hr: User, default_view: SavedView
) -> None:
    page = client.get(STAFF, {"rules": NAME_RULE}).content.decode()
    assert f'href="{STAFF}?view=plain"' in page  # the filter bar's «Цэвэрлэх»


def test_reset_all_button_opens_the_plain_address_and_drops_everything(
    client: Client, login_hr: User, default_view: SavedView
) -> None:
    page = client.get(STAFF, {"rules": NAME_RULE, "sort": "-name", "totals": "count"}).content.decode()
    assert re.search(rf'href="{re.escape(STAFF)}\?view=plain"[^>]*data-reset-all[^>]*aria-label="Бүгдийг арилгах"', page)
    reset = client.get(f"{STAFF}?view=plain")
    assert reset.status_code == 200 and not reset.has_header("Location")  # the default view does not reopen
    assert "Нөхцөл:" not in reset.content.decode()  # no rule line


def test_clear_links_open_without_redirect(client: Client, login_hr: User, default_view: SavedView) -> None:
    page = client.get(STAFF, {"rules": NAME_RULE}).content.decode()
    # the rules line's «Цэвэрлэх» (clear_rules_url) is the address without the rules: it must not be the bare path
    rules_clear = re.search(r'href="([^"]*)"[^>]*>Цэвэрлэх</a></p>', page)
    assert rules_clear is not None
    target = html.unescape(rules_clear.group(1))
    assert target != STAFF
    assert client.get(target).status_code == 200
    bar_clear = client.get(f"{STAFF}?view=plain")
    assert bar_clear.status_code == 200 and not bar_clear.has_header("Location")


def test_push_url_for_a_return_to_defaults_is_not_the_bare_path(
    client: Client, login_hr: User, default_view: SavedView
) -> None:
    response = client.get(STAFF, {"state": "working"}, HTTP_HX_REQUEST="true")
    assert response["HX-Push-Url"] != STAFF
    assert "cols=" in response["HX-Push-Url"]  # the columns are part of every address, so it is never bare


# ---- 4. the sort arrow is the only sort mark on a header ----


def test_header_cell_has_no_order_field() -> None:
    assert "order" not in {field.name for field in dataclasses.fields(HeaderCell)}


# ---- 5. only shown columns load for totals and colours ----


def test_total_and_colour_on_an_unshown_column_do_not_load_it(hr_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[tuple[str, ...]] = []
    data = [{"name": "p", "score": 3}]
    columns = (
        Column(key="name", label="Нэр", value=lambda r: r["name"]),
        Column(key="score", label="Оноо", value=lambda r: r["score"], numeric=True),
    )

    def rows(user: Any, filters: Any) -> list[dict[str, Any]]:
        recorded.append(filters.columns)
        return data

    report = Report(key="loads", title="Ачаалал", filters=(), columns=columns, default_columns=("name",), rows=rows)
    monkeypatch.setitem(REPORTS, "loads", report)
    mark = marks_mod.dump_marks([marks_mod.Mark(column="score", rule_op="gt", value="1", colour="red")])
    build_table(report, hr_user, parse_filters(QueryDict(f"cols=name&totals=score:sum&marks={mark}")))
    assert recorded and "score" not in recorded[0]
    assert "name" in recorded[0]


# ---- 6. the system log's rules line names no values ----


def test_log_line_names_only_the_rule_columns_and_print_keeps_the_values() -> None:
    labels = {"name": "Нэр"}
    f = Filters(rules=NAME_RULE)
    logged = describe(f, (), for_log=True, labels=labels)
    assert "Нөхцөл: Нэр" in logged
    assert not any("zzz" in line for line in logged)
    printed = describe(f, (), for_log=False, labels=labels)
    assert any("zzz" in line for line in printed)


# ---- 7. print colours carry a hex fallback before each oklch value ----


@pytest.mark.parametrize(
    ("cls", "hex_value"),
    [
        (".bg-red-50", "#fef2f2"),
        (".text-red-700", "#b91c1c"),
        (".bg-amber-50", "#fffbeb"),
        (".text-amber-800", "#92400e"),
        (".bg-green-50", "#f0fdf4"),
        (".text-green-700", "#15803d"),
        (".bg-blue-50", "#eff6ff"),
        (".text-blue-700", "#1d4ed8"),
    ],
)
def test_print_colours_have_hex_then_oklch(client: Client, login_hr: User, cls: str, hex_value: str) -> None:
    page = client.get("/reports/staff-list/print/").content.decode()
    rule = re.search(re.escape(cls) + r" \{([^}]*)\}", page)
    assert rule is not None
    body = rule.group(1)
    assert hex_value in body
    assert body.index(hex_value) < body.index("oklch(")
