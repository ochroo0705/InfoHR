"""Footer totals on the table: the aggregates run over every filtered row, and show on the screen, print and Excel."""

import io
import re
from collections.abc import Callable
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import openpyxl
import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from reports.filters import Filters, parse_filters
from reports.registry import REPORTS
from reports.table import build_table
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "totals-test"
PAGE = f"/reports/{KEY}/"
ROWS = 75  # more than one batch (config/batching LIST_BATCH is 60), so paging is exercised
SCORE_RULE = '{"op":"and","items":[{"c":"score","o":"gt","v":"50"}]}'  # keeps scores 51..75: 25 rows
FOOTER = re.compile(r"<tfoot>.*?</tfoot>", re.DOTALL)


def _people() -> list[Any]:
    return [SimpleNamespace(name=f"Ажилтан {n:02d}", score=n, pay=n * 1000) for n in range(1, ROWS + 1)]


@pytest.fixture
def totals_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    report = Report(
        key=KEY,
        title="Дүнгийн тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(key="score", label="Оноо", value=lambda r: r.score, numeric=True),
            Column(key="pay", label="Цалин", value=lambda r: r.pay, needs="macs.view_salary", numeric=True, money=True),
        ),
        default_columns=("name", "score"),
        rows=lambda user, filters: _people(),
        group_options=("name",),  # one group per person, so the grouped tests stay small
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _filters(**params: str) -> Filters:
    """The address as the page reads it: `cols` is a repeated key, so a comma list is split into one key each."""
    pairs = [(key, part) for key, value in params.items() for part in (value.split(",") if key == "cols" else [value])]
    return parse_filters(QueryDict(urlencode(pairs)))


def _values(table: Any) -> list[Any]:
    assert table.footer is not None
    return [cell.value for cell in table.footer]


# ---- the aggregates over the filtered rows ----


def test_sum_uses_only_the_rows_left_by_the_rule(totals_report: Report, accountant_user: User) -> None:
    table = build_table(
        totals_report, accountant_user, _filters(rules=SCORE_RULE, cols="name,score", totals="score:sum")
    )
    assert table.count == 25
    assert _values(table) == ["Дүн", sum(range(51, 76))]  # 1575: not all 75 rows, not one batch


def test_count_min_max_and_avg_use_the_filtered_rows(totals_report: Report, accountant_user: User) -> None:
    base = {"rules": SCORE_RULE, "cols": "name,score"}
    count = build_table(totals_report, accountant_user, _filters(**base, totals="score:count"))
    low = build_table(totals_report, accountant_user, _filters(**base, totals="score:min"))
    high = build_table(totals_report, accountant_user, _filters(**base, totals="score:max"))
    mean = build_table(totals_report, accountant_user, _filters(**base, totals="score:avg"))
    assert _values(count)[1] == 25
    assert _values(low)[1] == 51
    assert _values(high)[1] == 75
    assert _values(mean)[1] == Decimal("63.00")


def test_footer_covers_every_row_not_only_the_first_batch(totals_report: Report, accountant_user: User) -> None:
    table = build_table(totals_report, accountant_user, _filters(cols="name,score", totals="score:sum"))
    assert len(table.groups[0][1]) == ROWS  # build_table keeps every row; paging happens in the view
    assert _values(table)[1] == sum(range(1, ROWS + 1))


# ---- money, shown columns, permissions ----


def test_money_flag_is_set_for_a_money_sum(totals_report: Report, accountant_user: User) -> None:
    table = build_table(totals_report, accountant_user, _filters(cols="name,pay", totals="pay:sum"))
    assert table.footer is not None
    assert table.footer[1].money is True
    assert table.footer[1].value == sum(n * 1000 for n in range(1, ROWS + 1))
    assert table.footer[1].cls == "text-right"


def test_count_is_never_money(totals_report: Report, accountant_user: User) -> None:
    table = build_table(totals_report, accountant_user, _filters(cols="name,pay", totals="pay:count"))
    assert table.footer is not None
    assert table.footer[1].money is False


def test_total_on_an_unshown_column_gives_no_footer(totals_report: Report, accountant_user: User) -> None:
    table = build_table(totals_report, accountant_user, _filters(cols="name", totals="score:sum"))
    assert table.footer is None


def test_sum_on_a_text_column_is_ignored_and_count_works(totals_report: Report, accountant_user: User) -> None:
    ignored = build_table(totals_report, accountant_user, _filters(cols="name,score", totals="name:sum"))
    assert ignored.footer is None
    counted = build_table(totals_report, accountant_user, _filters(cols="name,score", totals="name:count"))
    assert _values(counted) == [ROWS, None]  # the count sits under the name; score has no total


def test_first_column_without_a_total_shows_the_label(totals_report: Report, accountant_user: User) -> None:
    table = build_table(totals_report, accountant_user, _filters(cols="name,score", totals="score:sum"))
    assert _values(table)[0] == "Дүн"
    assert table.footer is not None and table.footer[0].cls == ""


def test_hidden_salary_total_is_dropped_for_hr(totals_report: Report, hr_user: User) -> None:
    table = build_table(totals_report, hr_user, _filters(cols="score,pay", totals="pay:sum,score:count"))
    assert _values(table) == [ROWS]  # pay is not shown to HR, so its total is gone; one footer cell only


def test_salary_total_shows_for_a_user_with_the_permission(totals_report: Report, accountant_user: User) -> None:
    table = build_table(totals_report, accountant_user, _filters(cols="score,pay", totals="pay:sum,score:count"))
    assert _values(table) == [ROWS, sum(n * 1000 for n in range(1, ROWS + 1))]


# ---- the page, print and Excel ----


def test_screen_has_a_tfoot_with_the_formatted_total(
    client: Client, login_as: Callable[..., User], totals_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"cols": ["name", "pay"], "totals": "pay:sum"}).content.decode()
    footer = FOOTER.search(page)
    assert footer is not None
    assert f"{sum(n * 1000 for n in range(1, ROWS + 1)):,}₮" in footer.group(0)
    assert "font-semibold" in footer.group(0)


def test_screen_footer_covers_rows_on_the_first_batch_page(
    client: Client, login_as: Callable[..., User], totals_report: Report
) -> None:
    login_as(client, "Accountant")
    page = client.get(PAGE, {"cols": ["name", "score"], "totals": "score:sum"}).content.decode()
    footer = FOOTER.search(page)
    assert footer is not None
    assert str(sum(range(1, ROWS + 1))) in footer.group(0)  # 2850, though only 60 rows are on the page
    assert "Ажилтан 61" not in page


def test_print_has_a_tfoot_with_the_total(client: Client, login_as: Callable[..., User], totals_report: Report) -> None:
    login_as(client, "Accountant")
    url = reverse("reports:print", args=[KEY])
    page = client.get(url, {"cols": ["name", "score"], "totals": "score:sum"}).content.decode()
    footer = FOOTER.search(page)
    assert footer is not None
    assert str(sum(range(1, ROWS + 1))) in footer.group(0)


def test_excel_footer_is_numeric_bold_and_above_the_count(
    client: Client, login_as: Callable[..., User], totals_report: Report
) -> None:
    login_as(client, "Accountant")
    url = reverse("reports:excel", args=[KEY])
    response = client.get(url, {"rules": SCORE_RULE, "cols": ["name", "score"], "totals": "score:sum"})
    sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
    assert sheet is not None
    footer_row = 4 + 25 + 1  # headers on row 4, 25 data rows, then the footer
    assert sheet.cell(row=footer_row, column=1).value == "Дүн"
    total = sheet.cell(row=footer_row, column=2)
    assert total.value == sum(range(51, 76))
    assert isinstance(total.value, int)
    assert total.font.bold
    assert sheet.cell(row=footer_row + 1, column=1).value == "Нийт: 25"


# ---- fix round 1: groups, batches, empty tables, duplicates, huge averages ----


def test_grouped_table_has_one_footer_after_all_groups(totals_report: Report, accountant_user: User) -> None:
    table = build_table(
        totals_report, accountant_user, _filters(rules=SCORE_RULE, cols="name,score", totals="score:sum", group="name")
    )
    assert len(table.groups) == 25  # one group per filtered person
    assert table.footer is not None
    assert _values(table) == ["Дүн", sum(range(51, 76))]  # a single footer list, not one per group


def test_excel_grouped_footer_sits_after_the_group_rows_and_above_the_count(
    client: Client, login_as: Callable[..., User], totals_report: Report
) -> None:
    login_as(client, "Accountant")
    url = reverse("reports:excel", args=[KEY])
    response = client.get(url, {"rules": SCORE_RULE, "cols": ["name", "score"], "totals": "score:sum", "group": "name"})
    sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
    assert sheet is not None
    assert str(sheet.cell(row=5, column=1).value).endswith(" · 1")  # first group heading after the headers
    last_data_row = 5 + 25 * 2 - 1  # 25 groups, each a heading row and a data row
    assert sheet.cell(row=last_data_row, column=1).value == "Ажилтан 75"
    footer_row = last_data_row + 1
    assert sheet.cell(row=footer_row, column=1).value == "Дүн"
    assert sheet.cell(row=footer_row, column=2).value == sum(range(51, 76))
    assert sheet.cell(row=footer_row + 1, column=1).value == "Нийт: 25"


def test_batch_fragment_has_no_footer(client: Client, login_as: Callable[..., User], totals_report: Report) -> None:
    login_as(client, "Accountant")
    params: dict[str, Any] = {"cols": ["name", "score"], "totals": "score:sum", "offset": 60}
    fragment = client.get(PAGE, params, headers={"HX-Request": "true"}).content.decode()
    assert "Ажилтан 61" in fragment  # rows only: the second batch
    assert "<tfoot>" not in fragment


def test_empty_table_has_no_footer(
    totals_report: Report, accountant_user: User, client: Client, login_as: Callable[..., User]
) -> None:
    empty = build_table(
        totals_report,
        accountant_user,
        _filters(
            rules='{"op":"and","items":[{"c":"score","o":"gt","v":"1000"}]}', cols="name,score", totals="score:sum"
        ),
    )
    assert empty.count == 0
    assert empty.footer is None
    login_as(client, "Accountant")
    page = client.get(
        PAGE,
        {
            "cols": ["name", "score"],
            "totals": "score:sum",
            "rules": '{"op":"and","items":[{"c":"score","o":"gt","v":"1000"}]}',
        },
    ).content.decode()
    assert "<tfoot>" not in page


def test_duplicate_column_in_totals_keeps_the_first_aggregate(totals_report: Report, accountant_user: User) -> None:
    table = build_table(
        totals_report, accountant_user, _filters(rules=SCORE_RULE, cols="name,score", totals="score:sum,score:count")
    )
    assert _values(table) == ["Дүн", sum(range(51, 76))]  # the sum, not the count of 25


def test_huge_float_average_does_not_raise(monkeypatch: pytest.MonkeyPatch, accountant_user: User) -> None:
    report = Report(
        key="huge-floats",
        title="Том тоо",
        filters=(),
        columns=(Column(key="v", label="Утга", value=lambda r: r.v, numeric=True),),
        default_columns=("v",),
        rows=lambda user, filters: [SimpleNamespace(v=1e30), SimpleNamespace(v=1e30)],
    )
    monkeypatch.setitem(REPORTS, "huge-floats", report)
    table = build_table(report, accountant_user, _filters(totals="v:avg"))
    assert _values(table) == [1e30]
