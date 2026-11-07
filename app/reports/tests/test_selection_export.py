"""The Excel, CSV and print files of the picked rows (selected_excel, selected_csv, selected_print)."""

import csv
import io
from typing import Any

import openpyxl
import pytest
from accounts.models import AccessScope, SystemLogEntry, User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from employees.models import Employee
from employees.services import macs_writes
from employees.tests.conftest import named
from macs.models import Nationality

from reports import selection
from reports.filters import Filters, to_query
from reports.tests.conftest import _make_user, legacy

pytestmark = pytest.mark.django_db

ALL = to_query(Filters(state="all"))
QUERY = f"{ALL}&cols=code&cols=name"  # the staff list, every person, code and name shown
EXCEL = "/reports/staff-list/selected/excel/"
CSV = "/reports/staff-list/selected/csv/"
PRINT = "/reports/staff-list/selected/print/"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _remove_export_switch() -> None:
    """Take `accounts.export_lists` away from the HR group (the accounts migrations give it to HR)."""
    export = Permission.objects.get(codename="export_lists", content_type__app_label="accounts")
    Group.objects.get(name="HR").permissions.remove(export)


def _rows_of_sheet(data: bytes) -> list[list[Any]]:
    ws: Any = openpyxl.load_workbook(io.BytesIO(data)).active  # untyped: openpyxl stubs type `active` as Optional
    return [[c.value for c in row] for row in ws.iter_rows()]


def _csv_rows(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8").removeprefix("﻿")
    return list(csv.reader(io.StringIO(text)))


@pytest.fixture
def people(actor: User, job_values: dict[str, Any]) -> dict[str, Employee]:
    """A, B and C work in Санхүү, D in Маркетинг. Each has its own code, shown in the table."""
    marketing = macs_writes.save_department("Маркетинг")
    mongol = named(Nationality, "Монгол")
    return {
        "A": legacy(actor, job_values, nationality=mongol),
        "B": legacy(actor, job_values, nationality=mongol),
        "C": legacy(actor, job_values, nationality=mongol),
        "D": legacy(actor, job_values, nationality=mongol, department=marketing),
    }


@pytest.fixture
def scoped(people: dict[str, Employee]) -> User:
    """An HR user who may only see Санхүү: D (Маркетинг) is outside the scope."""
    user = _make_user("HR", "scoped-export-hr")
    AccessScope.objects.create(user=user, limited=True, department_ids=[people["A"].department_id])
    return user


def _post(client: Client, url: str, user: User, **data: Any) -> Any:
    client.force_login(user)
    return client.post(url, {"query": QUERY, **data})


def test_excel_holds_exactly_the_chosen_rows_without_footer(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    resp = _post(client, EXCEL, hr_user, ids=[str(people["C"].pk), str(people["A"].pk)])
    assert resp.status_code == 200 and resp["Content-Type"] == XLSX
    rows = _rows_of_sheet(resp.content)
    assert rows[3] == ["Код", "Ажилтан"]  # header row 4 holds the shown column labels
    body = [r for r in rows[4:] if any(v not in (None, "") for v in r)]  # the non-blank lines under the header
    assert str(body[-1][0]) == "Нийт: 2"  # the last line is the subset count, not a totals footer
    data = [str(r[0]) for r in body[:-1]]
    assert not any(str(r[0]).startswith("Нийт") for r in body[:-1])  # no other count or totals line
    assert sorted(data) == sorted(str(people[k].code) for k in ("A", "C"))  # only the chosen people


def test_csv_holds_the_chosen_rows_and_starts_with_bom(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    resp = _post(client, CSV, hr_user, ids=[str(people["B"].pk)])
    assert resp.status_code == 200
    assert resp.content.startswith(b"\xef\xbb\xbf")
    assert resp["Content-Type"].startswith("text/csv")
    rows = _csv_rows(resp.content)
    assert rows[0] == ["Код", "Ажилтан"]
    assert [r[0] for r in rows[1:]] == [people["B"].code]


def test_print_contains_chosen_people_and_not_others(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    resp = _post(client, PRINT, hr_user, ids=[str(people["A"].pk), str(people["D"].pk)])
    assert resp.status_code == 200
    page = resp.content.decode()
    assert f">{people['A'].code}</td>" in page and f">{people['D'].code}</td>" in page
    assert f">{people['B'].code}</td>" not in page and f">{people['C'].code}</td>" not in page


@pytest.mark.parametrize("url", [EXCEL, CSV, PRINT])
def test_get_is_405(client: Client, hr_user: User, url: str) -> None:
    client.force_login(hr_user)
    assert client.get(url).status_code == 405


def test_user_without_report_access_is_403_on_all_three(client: Client, people: dict[str, Employee]) -> None:
    no_access = _make_user("Employee", "no-report-access")  # the Employee role may not open reports (can_open false)
    ids = [str(people["A"].pk)]
    assert _post(client, EXCEL, no_access, ids=ids).status_code == 403
    assert _post(client, CSV, no_access, ids=ids).status_code == 403
    assert _post(client, PRINT, no_access, ids=ids).status_code == 403


def test_user_without_export_switch_is_refused_excel_and_csv_but_may_print(
    client: Client, hr_user: User, people: dict[str, Employee]
) -> None:
    _remove_export_switch()
    ids = [str(people["A"].pk)]
    assert _post(client, EXCEL, hr_user, ids=ids).status_code == 403
    assert _post(client, CSV, hr_user, ids=ids).status_code == 403
    assert _post(client, PRINT, hr_user, ids=ids).status_code == 200


def test_forged_id_outside_scope_never_appears_in_any_output(
    client: Client, scoped: User, people: dict[str, Employee]
) -> None:
    ids = [str(people["A"].pk), str(people["D"].pk)]
    excel_text = _rows_of_sheet(_post(client, EXCEL, scoped, ids=ids).content)
    csv_text = _post(client, CSV, scoped, ids=ids).content.decode("utf-8")
    page = _post(client, PRINT, scoped, ids=ids).content.decode()
    names = [r[0] for r in excel_text[4:] if r[0] not in (None, "") and not str(r[0]).startswith("Нийт")]
    assert names == [people["A"].code]
    assert people["D"].code not in csv_text and people["A"].code in csv_text
    assert f">{people['D'].code}</td>" not in page and f">{people['A'].code}</td>" in page


@pytest.mark.parametrize("url", [EXCEL, CSV, PRINT])
def test_empty_selection_is_400_with_the_message(
    client: Client, hr_user: User, people: dict[str, Employee], url: str
) -> None:
    resp = _post(client, url, hr_user)
    assert resp.status_code == 400
    assert resp["Content-Type"].startswith("text/plain")
    assert resp.content.decode() == selection.NOTHING_PICKED


def test_report_without_person_is_404(client: Client, hr_user: User, fake_report: Any) -> None:
    client.force_login(hr_user)
    assert client.post("/reports/fake/selected/print/", {"ids": ["1"]}).status_code == 404
    assert client.post("/reports/fake/selected/excel/", {"ids": ["1"]}).status_code == 404


def test_unknown_report_is_404(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)
    assert client.post("/reports/no-such-report/selected/csv/", {"ids": ["1"]}).status_code == 404


@pytest.mark.parametrize(
    ("url", "action"), [(EXCEL, "export_selected"), (CSV, "export_selected"), (PRINT, "print_selected")]
)
def test_each_export_writes_one_audit_entry(
    client: Client, hr_user: User, people: dict[str, Employee], url: str, action: str
) -> None:
    _post(client, url, hr_user, ids=[str(people["A"].pk), str(people["B"].pk)])
    [row] = list(SystemLogEntry.objects.filter(action=action))
    assert row.category == "export" and row.actor == hr_user
    assert "2 мөр" in row.message
