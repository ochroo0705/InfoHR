"""The filter-bar model (reports.services.filter_bar): which filters are drawn, their ✕ addresses, the picker, the
column-filter chips and the option lists behind the drawn dropdowns. The Django page and the API both read it."""

from dataclasses import replace

import pytest
from accounts.models import User
from django.db import connection
from django.http import QueryDict
from django.test.utils import CaptureQueriesContext
from employees.models import Employee
from macs.models import Branch, LeaveTypeRow, Nationality

from reports import staff_list
from reports.column_filters import COLUMN_FILTERS
from reports.filters import parse_filters
from reports.services.filter_bar import FilterBar, filter_bar
from reports.table import build_table
from reports.types import Report

from .conftest import _make_user

pytestmark = pytest.mark.django_db

PATH = "/reports/staff-list/"


def _bar(user: User, query: str = "", report: Report = staff_list.REPORT, plain: bool = False) -> FilterBar:
    get = QueryDict(query)
    table = build_table(report, user, parse_filters(get))
    return filter_bar(get, PATH, user, report, table, plain)


def test_items_hide_folded_filters_without_value_or_add(hr_user: User) -> None:
    # eight filters: the four most useful are drawn, the others fold into the picker
    bar = _bar(hr_user)
    assert [item.name for item in bar.items] == ["state", "as_of", "department", "emptype"]


def test_item_shows_folded_filter_with_value_and_its_remove_address_resets_it(hr_user: User) -> None:
    branch = Branch.objects.create(name="Төв салбар", status=1)
    bar = _bar(hr_user, f"branch={branch.pk}&gender=M")
    branch_item = next(item for item in bar.items if item.name == "branch")
    assert "branch=" not in branch_item.remove  # its ✕ resets the branch
    assert "gender=M" in branch_item.remove  # and keeps the other filters
    gender_item = next(item for item in bar.items if item.name == "gender")
    assert "gender=" not in gender_item.remove
    assert f"branch={branch.pk}" in gender_item.remove


def test_picker_lists_builtin_then_column_filters_with_headings(hr_user: User) -> None:
    bar = _bar(hr_user)
    headings = [entry.heading for entry in bar.picker if entry.heading]
    assert headings == ["Шүүлтүүр", "Баганаар"]
    column_at = [entry.heading for entry in bar.picker].index("Баганаар")
    builtin = [entry.label for entry in bar.picker[:column_at]]
    assert builtin == ["Салбар", "Албан тушаал", "Хүйс", "Нас"]  # the folded built-ins, in report order


def test_column_chip_for_code_filter_lists_rows_with_dash_for_no_name(hr_user: User) -> None:
    named_row = Nationality.objects.create(name="Монгол")
    nameless = Nationality.objects.create(name="")  # the column is NOT NULL: an empty name reads a dash
    bar = _bar(hr_user, f"nationality={named_row.pk}")
    chip = next(chip for chip in bar.column_chips if chip.name == "nationality")
    assert chip.params == ["nationality"]  # a choice or code filter has one parameter: its name
    assert chip.values == [str(named_row.pk)]
    labels = dict(chip.options)
    assert labels[str(named_row.pk)] == "Монгол"
    assert labels[str(nameless.pk)] == "—"  # a row with no name reads a dash, not None
    assert chip.remove_href.startswith(PATH)


def test_range_chip_carries_its_from_and_to_parameters(hr_user: User) -> None:
    # a range filter (date or number) has two parameters, in order: the name with _from, then with _to
    bar = _bar(hr_user, "hired_from=2020-01-01&hired_to=2020-12-31")
    chip = next(chip for chip in bar.column_chips if chip.name == "hired")
    assert chip.kind == "date"
    assert chip.params == ["hired_from", "hired_to"]
    assert chip.values == ["2020-01-01", "2020-12-31"]


def test_column_filter_the_user_may_not_use_is_absent(hr_user: User) -> None:
    # the salary column needs macs.view_salary, which the HR user lacks: its filter is neither a chip nor a pick
    bar = _bar(hr_user, "salary_from=1000&add=salary")
    assert "salary" not in [chip.name for chip in bar.column_chips]
    assert "salary" not in bar.adds
    assert COLUMN_FILTERS["salary"].label not in [entry.label for entry in bar.picker]


def _people(user: User) -> list[str]:
    report = replace(staff_list.REPORT, filters=(*staff_list.REPORT.filters, "employee"))
    return [pk for pk, _label in _bar(user, "add=employee", report=report).options.people]


def test_hidden_person_not_in_people_options(hr_user: User, hired: Employee) -> None:
    assert str(hired.pk) in _people(hr_user)
    outsider = _make_user("Employee", "filter-bar-outsider")  # sees only their own record
    assert str(hired.pk) not in _people(outsider)


def test_option_lists_read_only_when_filter_present(hr_user: User) -> None:
    # staff-list has no leave_type filter: its table is never read, and its option lists stay empty
    get = QueryDict("")
    table = build_table(staff_list.REPORT, hr_user, parse_filters(get))
    with CaptureQueriesContext(connection) as ctx:
        bar = filter_bar(get, PATH, hr_user, staff_list.REPORT, table, False)
    assert not any(LeaveTypeRow._meta.db_table in query["sql"] for query in ctx.captured_queries)
    assert bar.options.leave_types == []
    assert bar.options.absence_types == []


def test_option_lists_read_when_drawn(hr_user: User) -> None:
    branch = Branch.objects.create(name="Салбар А", status=1)
    bar = _bar(hr_user, f"branch={branch.pk}")
    assert dict(bar.options.branches)[str(branch.pk)] == "Салбар А"


def test_group_choices_empty_when_report_picks_columns(hr_user: User) -> None:
    assert staff_list.REPORT.picks_columns is True
    assert _bar(hr_user).options.group_choices == []


def test_add_with_name_not_offered_is_dropped(hr_user: User) -> None:
    bar = _bar(hr_user, "add=not_a_filter&add=salary")
    assert bar.adds == []
    assert "not_a_filter" not in [item.name for item in bar.items]


def test_clear_url_is_plain_only_when_asked(hr_user: User) -> None:
    assert _bar(hr_user, "gender=M").clear_url == PATH
    assert _bar(hr_user, "", plain=True).clear_url == f"{PATH}?view=plain"
