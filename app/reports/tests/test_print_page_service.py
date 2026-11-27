"""The print page's context, request-free: reports.services.print_page.build_print answers what the Django print view
and the React print API both draw from."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.http import QueryDict
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.helpers import next_order_number

from reports import privacy
from reports.filters import Filters, describe, parse_filters
from reports.services.print_page import PrintPage, build_print
from reports.staff_list import REPORT
from reports.summary import summary_of
from reports.table import allowed_columns, build_table

from .conftest import hire_values

pytestmark = pytest.mark.django_db

SEVEN = "cols=code&cols=name&cols=clan_name&cols=gender&cols=department&cols=position&cols=first_hire_date"
EIGHT = SEVEN + "&cols=work_phone"


def _filters(query: str) -> Filters:
    return parse_filters(QueryDict(query))


@pytest.fixture
def staff(actor: User, job_values: dict[str, Any]) -> list[Employee]:
    """Two people in Санхүү (accountant and engineer) and one in Ачаа; all working since 2026-01-05."""
    people = []
    for register_no, dept, pos in [
        ("УБ71000001", "Санхүү", "Нягтлан"),
        ("УБ71000002", "Санхүү", "Инженер"),
        ("УБ71000003", "Ачаа", "Нягтлан"),
    ]:
        job = {
            **job_values,
            "department": macs_writes.save_department(dept),
            "position": macs_writes.save_position(pos),
        }
        people.append(
            history.hire(
                hire_values(register_no=register_no),
                {},
                start=date(2026, 1, 5),
                job=job,
                salary=Decimal("2500000"),
                by=actor,
                order_number=next_order_number(),
            )
        )
    return people


def test_lines_and_note_come_from_describe_and_the_report_note(hr_user: User, staff: list[Employee]) -> None:
    filters = _filters(SEVEN)
    page = build_print(hr_user, REPORT, filters)
    table = build_table(REPORT, hr_user, filters)
    labels = {c.key: c.label for c in allowed_columns(REPORT, hr_user)}
    assert page.lines == describe(table.filters, REPORT.filters, labels=labels)
    assert page.note == (REPORT.note(table.filters) if REPORT.note is not None else "")
    assert page.title == REPORT.title


def test_seven_columns_print_portrait_and_eight_landscape(hr_user: User, staff: list[Employee]) -> None:
    seven = build_print(hr_user, REPORT, _filters(SEVEN))
    eight = build_print(hr_user, REPORT, _filters(EIGHT))
    assert len(seven.heads) == 7 and seven.landscape is False
    assert len(eight.heads) == 8 and eight.landscape is True


def test_heads_carry_label_and_class(hr_user: User, staff: list[Employee]) -> None:
    page = build_print(hr_user, REPORT, _filters("cols=code&cols=name"))
    assert [label for label, _cls in page.heads] == ["Код", "Ажилтан"]


def test_chart_address_adds_a_summary_and_a_table_address_does_not(hr_user: User, staff: list[Employee]) -> None:
    chart = build_print(hr_user, REPORT, _filters("layout=chart&lby=department"))
    expected = summary_of(build_table(REPORT, hr_user, _filters("layout=chart&lby=department")))
    assert expected is not None
    assert chart.summary is not None
    assert chart.summary.title == expected.title
    assert chart.summary.head == expected.head
    assert chart.summary.lines == expected.lines
    assert chart.summary.foot == expected.foot
    assert chart.summary.money == expected.money
    assert chart.summary.masked == expected.masked
    assert build_print(hr_user, REPORT, _filters(SEVEN)).summary is None


def test_shows_count_is_the_printed_tables_flag(hr_user: User, staff: list[Employee]) -> None:
    page = build_print(hr_user, REPORT, _filters(SEVEN))
    assert page.shows_count is True
    assert page.shows_count == build_table(REPORT, hr_user, _filters(SEVEN)).shows_count
    assert build_print(hr_user, REPORT, _filters(SEVEN), only=[staff[0].pk]).shows_count is True  # a subset keeps it


def test_a_report_without_the_count_line_prints_none(hr_user: User, staff: list[Employee]) -> None:
    quiet = replace(REPORT, shows_count=False)
    assert build_print(hr_user, quiet, _filters(SEVEN)).shows_count is False
    assert build_print(hr_user, quiet, _filters(SEVEN), only=[staff[0].pk]).shows_count is False


def test_only_keeps_that_person_and_has_no_footer(hr_user: User, staff: list[Employee]) -> None:
    chosen = staff[0]
    page = build_print(hr_user, REPORT, _filters(SEVEN), only=[chosen.pk])
    assert page.count == 1
    assert page.footer is None
    assert page.summary is None
    cells = [cell for group in page.groups for row in group.rows for cell in row]
    assert cells and all(cell.person == chosen.pk for cell in cells)


def test_only_drops_a_footer_the_full_print_has(accountant_user: User, staff: list[Employee]) -> None:
    query = "cols=code&cols=name&cols=salary&totals=salary:sum"
    full = build_print(accountant_user, REPORT, _filters(query))
    assert full.footer is not None  # the totals row exists for everyone
    part = build_print(accountant_user, REPORT, _filters(query), only=[staff[0].pk])
    assert part.footer is None
    assert part.count == 1


def test_only_drops_a_summary_the_full_chart_print_has(hr_user: User, staff: list[Employee]) -> None:
    query = "layout=chart&lby=department"
    full = build_print(hr_user, REPORT, _filters(query))
    assert full.summary is not None
    part = build_print(hr_user, REPORT, _filters(query), only=[staff[0].pk])
    assert part.summary is None


def test_empty_report_has_count_zero_and_no_rows(hr_user: User, staff: list[Employee]) -> None:
    page = build_print(hr_user, REPORT, _filters("department=999999&" + SEVEN))
    assert page.count == 0
    assert sum(len(group.rows) for group in page.groups) == 0


def test_group_heads_and_row_counts_match_the_table(hr_user: User, staff: list[Employee]) -> None:
    filters = _filters("group=department&" + SEVEN)
    page = build_print(hr_user, REPORT, filters)
    table = build_table(REPORT, hr_user, filters)
    assert page.grouped is True
    assert [group.label for group in page.groups] == [label for label, _rows in table.groups]
    assert [len(group.rows) for group in page.groups] == [len(rows) for _label, rows in table.groups]


def test_log_label_equals_the_joined_audit_lines(hr_user: User, staff: list[Employee]) -> None:
    filters = _filters(SEVEN)
    page = build_print(hr_user, REPORT, filters)
    labels = {c.key: c.label for c in allowed_columns(REPORT, hr_user)}
    table = build_table(REPORT, hr_user, filters)
    assert page.log_label == "; ".join(describe(table.filters, REPORT.filters, for_log=True, labels=labels))
    assert page.count == table.count
    assert page.min_group == privacy.min_group()


def test_page_is_a_print_page_with_a_today_iso_date(hr_user: User, staff: list[Employee]) -> None:
    page = build_print(hr_user, REPORT, _filters(SEVEN))
    assert isinstance(page, PrintPage)
    assert date.fromisoformat(page.today)
    assert page.printed_by


def test_a_given_table_gives_the_same_page_as_building_it(hr_user: User, staff: list[Employee]) -> None:
    filters = _filters(SEVEN)
    table = build_table(REPORT, hr_user, filters)
    chosen = [staff[0].pk, staff[2].pk]
    assert build_print(hr_user, REPORT, filters, only=chosen, table=table) == build_print(
        hr_user, REPORT, filters, only=chosen
    )
    assert build_print(hr_user, REPORT, filters, table=table) == build_print(hr_user, REPORT, filters)
