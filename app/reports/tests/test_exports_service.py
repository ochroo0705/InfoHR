"""The export file bodies, request-free (reports.services.exports): the Excel and CSV files of the picked people, the
whole report's Excel, the copy text of the picked names, and the audit labels the views record."""

import csv
import io
from dataclasses import replace
from typing import Any

import openpyxl
import pytest
from accounts.models import AccessScope, User
from django.http import QueryDict
from django.test import RequestFactory
from django.utils import timezone
from employees.models import Employee
from employees.services import macs_writes
from employees.tests.conftest import named
from macs.models import Nationality

from reports import excel, staff_list
from reports.filters import Filters, describe, parse_filters, to_query
from reports.selection import Picked, SelectionError, pick
from reports.services import exports
from reports.summary import summary_of
from reports.table import allowed_columns, build_table
from reports.tests.conftest import _make_user, legacy

pytestmark = pytest.mark.django_db

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_TYPE = "text/csv; charset=utf-8"
NOTE_TEXT = "Тэмдэглэл: шүүлтийн тайлбар"  # a grey note the test report carries
REPORT = staff_list.REPORT
QUERY = f"{to_query(Filters(state='all'))}&cols=code&cols=name"  # every person, code and name shown
SALARY = "macs.view_salary"  # the HR role does not hold it


def _filters(query: str) -> Filters:
    return parse_filters(QueryDict(query))


def _picked(user: User, ids: list[int], query: str = QUERY, report: Any = REPORT) -> Picked:
    """The selection as a POST of the report's address and the ticked ids, checked by selection.pick."""
    request = RequestFactory().post("/selected/", {"query": query, "ids": [str(pk) for pk in ids]})
    return pick(request, user, report)


def _workbook(data: bytes) -> Any:
    return openpyxl.load_workbook(io.BytesIO(data))  # untyped: openpyxl stubs the sheet types as Optional


def _sheet_rows(data: bytes) -> list[list[Any]]:
    ws = _workbook(data).active
    return [[c.value for c in row] for row in ws.iter_rows()]


@pytest.fixture
def people(actor: User, job_values: dict[str, Any]) -> dict[str, Employee]:
    """A, B and C work in Санхүү, D in Маркетинг. A and C have emails; B and D have none."""
    marketing = macs_writes.save_department("Маркетинг")
    mongol = named(Nationality, "Монгол")
    made = {
        "A": legacy(actor, job_values, nationality=mongol),
        "B": legacy(actor, job_values, nationality=mongol),
        "C": legacy(actor, job_values, nationality=mongol),
        "D": legacy(actor, job_values, nationality=mongol, department=marketing),
    }
    Employee.objects.filter(pk=made["A"].pk).update(email="a@example.test")
    Employee.objects.filter(pk=made["C"].pk).update(email="c@example.test")
    return {k: Employee.objects.get(pk=e.pk) for k, e in made.items()}


@pytest.fixture
def scoped(people: dict[str, Employee]) -> User:
    """An HR user who may only see Санхүү: D (Маркетинг) is outside the scope."""
    user = _make_user("HR", "scoped-exports-hr")
    AccessScope.objects.create(user=user, limited=True, department_ids=[people["A"].department_id])
    return user


def test_excel_file_is_named_by_key_and_date_and_counts_its_rows(hr_user: User, people: dict[str, Employee]) -> None:
    exported = exports.excel_file(hr_user, REPORT, _filters(QUERY))
    today = timezone.localdate().isoformat()
    assert exported.filename == f"{REPORT.key}-{today}.xlsx"
    assert exported.content_type == XLSX
    assert exported.log_action == "export_report"
    assert exported.rows == build_table(REPORT, hr_user, _filters(QUERY)).count
    assert _workbook(exported.body).sheetnames == [REPORT.key]  # a table address has no summary sheet


def test_excel_file_adds_the_summary_sheet_for_a_chart_address(hr_user: User, people: dict[str, Employee]) -> None:
    filters = _filters(f"{QUERY}&layout=chart&lby=department")
    summary = summary_of(build_table(REPORT, hr_user, filters))
    assert summary is not None
    wb = _workbook(exports.excel_file(hr_user, REPORT, filters).body)
    assert wb.sheetnames == [REPORT.key, excel.SUMMARY_SHEET]
    sheet = wb[excel.SUMMARY_SHEET]
    assert sheet["A1"].value == summary.title
    heads = [sheet.cell(row=3, column=col).value for col in range(1, len(summary.head) + 1)]
    assert heads == list(summary.head)


def test_excel_file_writes_the_report_note_after_the_filter_lines(hr_user: User, people: dict[str, Employee]) -> None:
    noted = replace(REPORT, note=lambda _filters: NOTE_TEXT)
    exported = exports.excel_file(hr_user, noted, _filters(QUERY))
    line = _workbook(exported.body)[REPORT.key]["A2"].value  # row 2 holds the filter lines joined by "; "
    assert line.endswith(NOTE_TEXT)


def test_excel_file_log_label_is_the_filter_lines_for_the_log(hr_user: User, people: dict[str, Employee]) -> None:
    filters = _filters(QUERY)
    exported = exports.excel_file(hr_user, REPORT, filters)
    table = build_table(REPORT, hr_user, filters)
    labels = {c.key: c.label for c in allowed_columns(REPORT, hr_user)}
    expected = "; ".join(describe(table.filters, REPORT.filters, for_log=True, labels=labels))
    assert exported.log_label == expected


def test_selected_excel_holds_only_the_picked_people(hr_user: User, people: dict[str, Employee]) -> None:
    picked = _picked(hr_user, [people["C"].pk, people["A"].pk])
    exported = exports.selected_file(hr_user, REPORT, picked, "xlsx")
    today = timezone.localdate().isoformat()
    assert exported.filename == f"{REPORT.key}-selected-{today}.xlsx"
    assert exported.content_type == XLSX
    assert exported.log_action == "export_selected"
    assert exported.rows == 2
    assert _workbook(exported.body).sheetnames == [REPORT.key]  # one sheet, no summary
    cells = [str(r[0]) for r in _sheet_rows(exported.body)[4:] if r[0] not in (None, "")]
    assert str(people["A"].code) in cells and str(people["C"].code) in cells
    assert str(people["B"].code) not in cells and str(people["D"].code) not in cells


def test_selected_excel_has_no_totals_row_where_the_full_export_has_one(
    accountant_user: User, people: dict[str, Employee]
) -> None:
    query = f"{QUERY}&cols=salary&totals=salary:sum"
    full_table = build_table(REPORT, accountant_user, _filters(query))
    assert full_table.footer is not None  # the full export has a totals row under the people
    full = _sheet_rows(exports.excel_file(accountant_user, REPORT, _filters(query)).body)
    full_lines = [r for r in full[4:] if any(v not in (None, "") for v in r)]
    assert len(full_lines) == full_table.count + 2  # every person, the totals row, the count line

    picked = _picked(accountant_user, [people["A"].pk, people["C"].pk], query=query)
    selected = _sheet_rows(exports.selected_file(accountant_user, REPORT, picked, "xlsx").body)
    lines = [r for r in selected[4:] if any(v not in (None, "") for v in r)]
    assert len(lines) == 2 + 1  # the two people and the count line: no totals row
    assert lines[-1][0] == "Нийт: 2"


def test_selected_csv_starts_with_bom_and_has_no_footer(hr_user: User, people: dict[str, Employee]) -> None:
    picked = _picked(hr_user, [people["B"].pk])
    exported = exports.selected_file(hr_user, REPORT, picked, "csv")
    today = timezone.localdate().isoformat()
    assert exported.filename == f"{REPORT.key}-selected-{today}.csv"
    assert exported.content_type == CSV_TYPE
    assert exported.log_action == "export_selected"
    assert exported.body.startswith(b"\xef\xbb\xbf")
    text = exported.body.decode("utf-8").removeprefix("﻿")
    assert "Нийт" not in text  # the CSV has no count or totals line
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["Код", "Ажилтан"]
    assert [r[0] for r in rows[1:]] == [people["B"].code]
    assert exported.rows == 1


def test_copy_text_has_name_and_email_when_the_email_column_is_allowed(
    hr_user: User, people: dict[str, Employee]
) -> None:
    picked = _picked(hr_user, [people["A"].pk, people["C"].pk])
    result = exports.selected_copy(hr_user, REPORT, picked)
    expected = [f"{people[k].full_name}\t{people[k].email}" for k in _in_ids_order(picked, people, ("A", "C"))]
    assert result.text == "\n".join(expected)
    assert result.count == 2 and result.dropped == 0


def test_copy_text_is_names_only_when_the_email_column_is_not_allowed(
    hr_user: User, people: dict[str, Employee]
) -> None:
    report = replace(
        REPORT,
        columns=tuple(replace(c, needs=SALARY) if c.key == "email" else c for c in REPORT.columns),
    )
    picked = _picked(hr_user, [people["A"].pk, people["C"].pk], report=report)
    result = exports.selected_copy(hr_user, report, picked)
    assert result.text == "\n".join(people[k].full_name for k in _in_ids_order(picked, people, ("A", "C")))


def _in_ids_order(picked: Picked, people: dict[str, Employee], keys: tuple[str, ...]) -> list[str]:
    """The keys in the order the picked ids hold them (the report order pick returns)."""
    position = {pk: i for i, pk in enumerate(picked.ids)}
    return sorted(keys, key=lambda k: position[people[k].pk])


def test_a_name_with_spaces_tabs_and_line_breaks_stays_on_one_line(hr_user: User, people: dict[str, Employee]) -> None:
    #   (line separator) and \u0085 (next line) are breaks too; the escapes keep the source free of hidden characters
    name = "Бат\x0bX Y\x1cZ\u0085W\tQ\r\nR S"
    Employee.objects.filter(pk=people["A"].pk).update(family_name="", given_name=name)
    picked = _picked(hr_user, [people["A"].pk, people["B"].pk])
    result = exports.selected_copy(hr_user, REPORT, picked)
    lines = result.text.split("\n")
    assert len(lines) == 2  # two people, two lines
    assert lines[0].startswith("Бат X Y Z W Q  R S\t")  # every tab and line break, U+2028 included, became one space
    assert exports._one_line("a\tb\nc") == "a b c"


def test_dropped_counts_the_ids_the_user_may_not_act_on(scoped: User, people: dict[str, Employee]) -> None:
    picked = _picked(scoped, [people["A"].pk, people["D"].pk])
    result = exports.selected_copy(scoped, REPORT, picked)
    assert result.dropped == 1
    assert result.count == 1
    assert result.text == people["A"].full_name + "\t" + (people["A"].email or "")


def test_no_name_column_raises_before_anything_is_picked(hr_user: User, people: dict[str, Employee]) -> None:
    report = replace(
        REPORT,
        columns=tuple(replace(c, needs=SALARY) if c.key == "name" else c for c in REPORT.columns),
    )
    with pytest.raises(SelectionError) as raised:
        exports.copy_columns(hr_user, report)
    assert raised.value.message == exports.NO_NAME_COLUMN


def test_copy_result_count_and_log_label_match_the_subset(hr_user: User, people: dict[str, Employee]) -> None:
    picked = _picked(hr_user, [people["A"].pk, people["B"].pk])
    result = exports.selected_copy(hr_user, REPORT, picked)
    table = build_table(REPORT, hr_user, picked.table.filters)
    labels = {c.key: c.label for c in allowed_columns(REPORT, hr_user)}
    assert result.count == 2
    assert result.log_label == "; ".join(describe(table.filters, REPORT.filters, for_log=True, labels=labels))


def test_selected_file_rows_equal_the_subset_count(hr_user: User, people: dict[str, Employee]) -> None:
    picked = _picked(hr_user, [people["D"].pk])
    assert exports.selected_file(hr_user, REPORT, picked, "csv").rows == 1
    assert exports.selected_file(hr_user, REPORT, picked, "xlsx").rows == 1
