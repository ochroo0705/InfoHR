"""The report search («q»): the pure matcher, the address and the staff list rows, the page, print and Excel."""

import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import openpyxl
import pytest
from accounts.models import User
from django.http import QueryDict
from django.test import Client
from django.urls import reverse
from employees.tests.helpers import next_order_number
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values

from reports.filters import Filters, describe, parse_filters, to_query
from reports.staff_list import REPORT
from reports.table import build_table, search_rows
from reports.types import Column

pytestmark = pytest.mark.django_db


@dataclass
class Person:
    """A fake row for the pure matcher."""

    name: str
    department: str | None
    salary: Any
    hired: date | None


PEOPLE = [
    Person("Батын Сараа", "Санхүү", Decimal("2500000"), date(2026, 1, 5)),
    Person("Дорж Болд", "Борлуулалт", Decimal("1800000"), date(2026, 2, 1)),
    Person("Өлзий Наран", None, None, None),
]


def col(key: str, money: bool = False) -> Column:
    return Column(key=key, label=key, value=lambda row: getattr(row, key), money=money)


NAME, DEPT, SALARY, HIRED = col("name"), col("department"), col("salary", money=True), col("hired")
ALL = [NAME, DEPT, SALARY, HIRED]


def names(rows: list[Any]) -> list[str]:
    return [row.name for row in rows]


def test_empty_or_blank_search_keeps_every_row_in_order() -> None:
    assert search_rows(PEOPLE, ALL, "") == PEOPLE
    assert search_rows(PEOPLE, ALL, "   ") == PEOPLE


def test_search_is_case_insensitive() -> None:
    assert names(search_rows(PEOPLE, ALL, "сараа")) == ["Батын Сараа"]
    assert names(search_rows(PEOPLE, ALL, "сараам")) == []
    assert names(search_rows(PEOPLE, ALL, "БОРЛУУЛАЛТ")) == ["Дорж Болд"]


def test_mongolian_variants_match_each_other() -> None:
    # ө reads as о and ү as у on both sides: «Өлзий» is found by «олзий», and «Санхүү» by «санхуу»
    assert names(search_rows(PEOPLE, ALL, "олзий")) == ["Өлзий Наран"]
    assert names(search_rows(PEOPLE, ALL, "өлзий")) == ["Өлзий Наран"]
    assert names(search_rows(PEOPLE, ALL, "санхуу")) == ["Батын Сараа"]


def test_every_word_must_be_found_and_each_in_some_column() -> None:
    assert names(search_rows(PEOPLE, ALL, "Батын Сараа")) == ["Батын Сараа"]  # both in the name
    assert names(search_rows(PEOPLE, ALL, "Сараа Санхүү")) == ["Батын Сараа"]  # one in name, one in department
    assert names(search_rows(PEOPLE, ALL, "Сараа Борлуулалт")) == []  # the words are in different people
    assert names(search_rows(PEOPLE, ALL, "Сараа zzz")) == []  # a word found nowhere: no row


def test_a_hidden_column_is_never_searched() -> None:
    assert names(search_rows(PEOPLE, [NAME], "Санхүү")) == []  # the department is not one of the shown columns
    assert names(search_rows(PEOPLE, [NAME, DEPT], "Санхүү")) == ["Батын Сараа"]


def test_money_matches_the_screen_text_and_the_plain_digits() -> None:
    assert names(search_rows(PEOPLE, [SALARY], "2,500,000")) == ["Батын Сараа"]  # 2,500,000₮ on the screen
    assert names(search_rows(PEOPLE, [SALARY], "2500000")) == ["Батын Сараа"]  # the digits
    assert names(search_rows(PEOPLE, [SALARY], "1,800")) == ["Дорж Болд"]


def test_a_plain_number_matches_its_digits() -> None:
    assert names(search_rows(PEOPLE, [SALARY], "1800000")) == ["Дорж Болд"]


def test_dates_match_their_screen_text() -> None:
    assert names(search_rows(PEOPLE, [HIRED], "2026-02-01")) == ["Дорж Болд"]
    assert names(search_rows(PEOPLE, [HIRED], "2026-01")) == ["Батын Сараа"]


def test_blank_values_never_match_and_never_raise() -> None:
    assert names(search_rows(PEOPLE, ALL, "None")) == []  # a blank cell is not the text «None»
    assert names(search_rows(PEOPLE, ALL, "наран")) == ["Өлзий Наран"]


def test_search_returns_a_new_list_and_keeps_the_input() -> None:
    kept = search_rows(PEOPLE, ALL, "Болд")
    assert kept is not PEOPLE and len(PEOPLE) == 3


def test_the_word_is_cut_and_stripped_in_the_address() -> None:
    assert parse_filters(QueryDict("q=%20%20Сараа%20%20")).q == "Сараа"
    assert parse_filters(QueryDict(f"q={'а' * 300}")).q == "а" * 200
    assert parse_filters(QueryDict("")).q == ""


def test_search_is_kept_in_the_address_round_trip() -> None:
    query = to_query(Filters(q="Батын Сараа"))
    assert parse_filters(QueryDict(query)).q == "Батын Сараа"
    assert to_query(Filters()) == ""  # an empty search is not written


def test_search_is_listed_in_print_and_log_lines() -> None:
    assert describe(Filters(q="Сараа"), shown=()) == ["Хайлт: Сараа"]
    assert describe(Filters(q="Сараа"), shown=(), for_log=True) == ["Хайлт: ашигласан"]  # the log names no typed text
    assert describe(Filters(), shown=()) == []


# the staff list: real employees, through build_table


@pytest.fixture
def two_people(actor: User, job_values: dict[str, Any]) -> tuple[Employee, Employee]:
    first = history.hire(
        hire_values(register_no="УБ55500010"),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=actor,
        order_number=next_order_number(),
    )
    sales = {**job_values, "department": macs_writes.save_department("Борлуулалт")}
    second_values = {**hire_values(register_no="УБ55500011"), "family_name": "Дорж", "given_name": "Болд"}
    second = history.hire(second_values, {}, start=date(2026, 1, 5), job=sales, salary=Decimal("1800000"), by=actor, order_number=next_order_number())
    return first, second


def _rows(user: User, f: Filters) -> list[Any]:
    return build_table(REPORT, user, f).rows


def _codes(rows: list[Any]) -> set[str]:
    return {row.row.employee.code for row in rows}


def test_search_narrows_the_staff_list_by_name(hr_user: User, two_people: tuple[Employee, Employee]) -> None:
    first, second = two_people
    assert _codes(_rows(hr_user, Filters(state="all", q="Сараа"))) == {first.code}
    assert _codes(_rows(hr_user, Filters(state="all", q="Болд"))) == {second.code}


def test_search_matches_department_text(hr_user: User, two_people: tuple[Employee, Employee]) -> None:
    _, second = two_people
    assert _codes(_rows(hr_user, Filters(state="all", q="Борлуулалт"))) == {second.code}


def test_two_words_must_both_match(hr_user: User, two_people: tuple[Employee, Employee]) -> None:
    first, _ = two_people
    assert _codes(_rows(hr_user, Filters(state="all", q="Батын Санхүү"))) == {first.code}
    assert _codes(_rows(hr_user, Filters(state="all", q="Батын Борлуулалт"))) == set()


def test_empty_search_changes_nothing(hr_user: User, two_people: tuple[Employee, Employee]) -> None:
    f = Filters(state="all")
    assert _codes(_rows(hr_user, f)) == _codes(_rows(hr_user, Filters(state="all", q="")))
    assert len(_rows(hr_user, f)) == 2


def test_count_and_totals_follow_the_search(hr_user: User, two_people: tuple[Employee, Employee]) -> None:
    table = build_table(REPORT, hr_user, Filters(state="all", q="Болд", columns=("code", "name", "department")))
    assert table.count == 1 and len(table.rows) == 1
    assert [len(rows) for _, rows in table.groups] == [1]


def test_search_skips_a_column_the_viewer_may_not_see(
    accountant_user: User, two_people: tuple[Employee, Employee]
) -> None:
    """The register number is a personal column: the accountant never sees it, so it is never searched."""
    first, _ = two_people
    register = Employee.objects.get(pk=first.pk).register_no
    assert build_table(REPORT, accountant_user, Filters(state="all", q=register)).count == 0


def test_search_finds_a_personal_column_for_a_viewer_who_sees_it(
    hr_user: User, two_people: tuple[Employee, Employee]
) -> None:
    first, _ = two_people
    register = Employee.objects.get(pk=first.pk).register_no
    table = build_table(REPORT, hr_user, Filters(state="all", q=register, columns=("code", "register_no")))
    assert _codes(table.rows) == {first.code}


def test_search_applies_to_the_salary_column_for_an_accountant(
    accountant_user: User, two_people: tuple[Employee, Employee]
) -> None:
    first, _ = two_people
    table = build_table(REPORT, accountant_user, Filters(state="all", q="2500000", columns=("code", "salary")))
    assert _codes(table.rows) == {first.code}


def test_page_shows_the_matching_rows_and_the_empty_text(
    client: Client, login_hr: User, two_people: tuple[Employee, Employee]
) -> None:
    _, second = two_people
    page = client.get(reverse("reports:report", args=["staff-list"]), {"state": "all", "q": "Болд"}).content.decode()
    assert "Нийт: 1" in page and "Батын" not in page
    assert second.code in page
    empty = client.get(reverse("reports:report", args=["staff-list"]), {"state": "all", "q": "zzzqqq"}).content.decode()
    assert "Өгөгдөл олдсонгүй" in empty


def test_print_lists_the_search(client: Client, login_hr: User, two_people: tuple[Employee, Employee]) -> None:
    page = client.get(reverse("reports:print", args=["staff-list"]), {"state": "all", "q": "Болд"}).content.decode()
    assert "Хайлт: Болд" in page
    assert "Батын" not in page


def test_excel_has_only_the_matching_rows(
    client: Client, login_hr: User, two_people: tuple[Employee, Employee]
) -> None:
    _, second = two_people
    resp = client.get(
        reverse("reports:excel", args=["staff-list"]),
        {"state": "all", "q": "Болд", "cols": ["code", "name"]},
    )
    ws = openpyxl.load_workbook(io.BytesIO(resp.content)).active
    values = [[cell.value for cell in row] for row in ws.iter_rows(min_row=5)]
    data = [row for row in values if row[0] is not None and not str(row[0]).startswith("Нийт")]
    assert [row[0] for row in data] == [second.code]
    assert any(str(cell) == "Нийт: 1" for row in values for cell in row if cell is not None)


# the page: the search box in the filter bar, its trigger, the sort links and «Цэвэрлэх»


def test_the_search_box_is_the_first_control_of_the_filter_bar(
    client: Client, login_hr: User, two_people: tuple[Employee, Employee]
) -> None:
    page = client.get(reverse("reports:report", args=["staff-list"]), {"state": "all", "q": "Болд"}).content.decode()
    form = page.index('id="report-filters"')
    box = page.index('name="q"')
    assert form < box < page.index('data-filter="state"')
    assert 'aria-label="Тайлангаас хайх"' in page and 'maxlength="200"' in page


def test_the_search_box_renders_the_current_value_and_is_lit(
    client: Client, login_hr: User, two_people: tuple[Employee, Employee]
) -> None:
    page = client.get(reverse("reports:report", args=["staff-list"]), {"state": "all", "q": "Болд"}).content.decode()
    assert re.search(r'<input type="search" name="q" value="Болд"[^>]*data-applied', page)


def test_an_empty_search_box_is_not_lit(client: Client, login_hr: User, two_people: tuple[Employee, Employee]) -> None:
    page = client.get(reverse("reports:report", args=["staff-list"]), {"state": "all"}).content.decode()
    assert re.search(r'<input type="search" name="q" value=""[^>]*>', page)
    assert "data-applied" not in re.search(r'<input type="search" name="q"[^>]*>', page).group(0)


def test_the_search_box_asks_after_a_pause_or_on_enter_and_not_when_unchanged(
    client: Client, login_hr: User, two_people: tuple[Employee, Employee]
) -> None:
    page = client.get(reverse("reports:report", args=["staff-list"]), {"state": "all", "q": "Болд"}).content.decode()
    box = re.search(r'<input type="search" name="q"[^>]*>', page).group(0)
    assert 'hx-trigger="input[this.value!=this.defaultValue] changed delay:300ms, search[this.value!=this.defaultValue]"' in box
    assert 'hx-include="#report-filters"' in box and 'hx-target="#report-page"' in box
    # the filter form ignores the box's own change, so the box is the only thing that asks for it
    assert "hx-trigger=\"change[event.target.name!='q'], submit\"" in page


def test_a_sort_link_on_a_searched_page_keeps_the_search(
    client: Client, login_hr: User, two_people: tuple[Employee, Employee]
) -> None:
    page = client.get(reverse("reports:report", args=["staff-list"]), {"state": "all", "q": "Болд"}).content.decode()
    hrefs = re.findall(r'href="([^"]*sort=[^"]*)"', page.replace("&amp;", "&"))
    assert hrefs, "the table has sort links"
    assert all("q=" in href for href in hrefs)


def test_the_clear_link_is_drawn_for_a_searched_page(
    client: Client, login_hr: User, two_people: tuple[Employee, Employee]
) -> None:
    """«Цэвэрлэх» is shown by report_filters.js while something is applied; the search counts as applied, so its box is
    lit (the script reads data-applied) and the link is there to show."""
    page = client.get(reverse("reports:report", args=["staff-list"]), {"state": "all", "q": "Болд"}).content.decode()
    assert "data-filters-clear" in page
    assert re.search(r'<input type="search" name="q"[^>]*data-applied', page)
