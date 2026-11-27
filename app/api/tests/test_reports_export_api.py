"""The report print page, its Excel file, and the picked people's Excel, CSV, print ticket and copy (api/reports.py).

The rules live in reports.services (print_page, exports) and reports.selection and have their own tests; these tests pin
the routes: their shapes, their rights (401 without a login, 403 without the right, 404 for a missing or person-less
report), the refusals (400 with the message in form_errors), the one audit line per call, the file headers, and a second
report key working with no route of its own.
"""

import io
import json
import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import openpyxl
import pytest
from accounts.models import SystemLogEntry, User
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.models import Employee
from employees.services import macs_writes
from reports.registry import REPORTS
from reports.selection import NOTHING_PICKED, not_allowed, too_many
from reports.services.exports import NO_NAME_COLUMN, TICKET_INVALID
from reports.summary import Summary
from reports.tests.conftest import legacy
from reports.types import Column, Report

from api.tests.logs_support import FORBIDDEN, NOT_LOGGED_IN, take_export_switch

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
KEY = "api-export-test"
HELD_OUT = "api-export-held-out"  # a second report with a person, registered the same way; no route knows it
NO_PERSON = "api-export-no-person"
STAFF = "staff-list"  # the real registry report with a person (chart layouts)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV = "text/csv; charset=utf-8"
PRINT_KEYS = {
    "title",
    "company",
    "today",
    "printed_by",
    "lines",
    "note",
    "landscape",
    "heads",
    "groups",
    "footer",
    "count",
    "shows_count",
    "grouped",
    "summary",
    "min_group",
}
SUMMARY_KEYS = {"title", "head", "lines", "foot", "money", "masked"}
NAMES = ("Бат", "Ганаа", "Дорж")


SECRET_SALARY = 731415  # the salary column's value; it must never reach a user without macs.view_salary (HR lacks it)


def _rows(user: User, f: Any) -> list[Any]:
    return [
        SimpleNamespace(pk=i, name=name, code=f"K{i}", email=f"u{i}@example.test")
        for i, name in enumerate(NAMES, start=1)
    ]


def _report(
    key: str,
    *,
    person: bool = True,
    name_column: bool = True,
    email_needs: str | None = None,
    secret: bool = False,
) -> Report:
    """The test report. `email_needs` adds an email column with that permission ("" = open to everyone); `secret`
    adds a salary column the HR role may not see."""
    columns: tuple[Column, ...] = (Column(key="code", label="Код", value=lambda r: r.code),)
    if name_column:
        columns += (Column(key="name", label="Нэр", value=lambda r: r.name),)
    if email_needs is not None:
        columns += (Column(key="email", label="Имэйл", value=lambda r: r.email, needs=email_needs),)
    if secret:
        columns += (
            Column(key="salary", label="Цалин", value=lambda r: SECRET_SALARY, needs="macs.view_salary", money=True),
        )
    return Report(
        key=key,
        title="Тестийн тайлан",
        filters=(),
        columns=columns,
        default_columns=tuple(c.key for c in columns),
        rows=_rows,
        saved_views=True,
        layouts=(),
        person=(lambda r: r.pk) if person else None,
    )


@pytest.fixture
def register(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Report]:
    """Registers a test report under its key for this test only."""

    def _add(key: str = KEY, **options: Any) -> Report:
        report = _report(key, **options)
        monkeypatch.setitem(REPORTS, key, report)
        return report

    return _add


def _user(role: str, name: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _as(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _post(client: Client, path: str, body: dict[str, Any] | None = None) -> Any:
    return client.post(path, data=json.dumps(body or {}), content_type="application/json")


def _base(key: str = KEY) -> str:
    return f"/api/v1/reports/{key}"


def _export_count(action: str | None = None) -> int:
    rows = SystemLogEntry.objects.filter(category="export")
    return rows.filter(action=action).count() if action else rows.count()


def _texts(groups: list[dict[str, Any]]) -> list[str]:
    return [cell["text"] for group in groups for row in group["rows"] for cell in row]


@pytest.fixture
def hr() -> User:
    return _user("HR", "api_export_hr")


@pytest.fixture
def auditor() -> User:
    return _user("Auditor", "api_export_auditor")  # sees the system log only: no report may be opened


@pytest.fixture
def staff() -> list[Employee]:
    """Two people in Санхүү and one in Маркетинг, for the real staff list's chart address."""
    by = User.objects.create_user("api_export_actor", password=PASSWORD)  # noqa: S106
    jobs = {"position": macs_writes.save_position("Нягтлан"), "department": macs_writes.save_department("Санхүү")}
    marketing = macs_writes.save_department("Маркетинг")
    return [legacy(by, jobs), legacy(by, jobs), legacy(by, jobs, department=marketing)]


# --- rights and refusals ----------------------------------------------------------------------------------------------


def test_no_login_is_401(register: Callable[..., Report]) -> None:
    register()
    client = Client()
    response = client.get(f"{_base()}/print")
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN
    assert client.get(f"{_base()}/excel").status_code == 401
    for path in ("selected/excel", "selected/csv", "selected/print", "selected/copy"):
        assert _post(client, f"{_base()}/{path}", {"ids": ["1"]}).status_code == 401


def test_no_open_right_is_403_on_every_route(register: Callable[..., Report], auditor: User) -> None:
    register()
    client = _as(auditor)  # the Auditor role may not open reports
    for response in (
        client.get(f"{_base()}/print"),
        client.get(f"{_base()}/excel"),
        _post(client, f"{_base()}/selected/excel", {"ids": ["1"]}),
        _post(client, f"{_base()}/selected/csv", {"ids": ["1"]}),
        _post(client, f"{_base()}/selected/print", {"ids": ["1"]}),
        _post(client, f"{_base()}/selected/copy", {"ids": ["1"]}),
    ):
        assert response.status_code == 403
        assert response.json() == FORBIDDEN


def test_without_the_export_switch_the_files_are_403_and_print_and_copy_pass(
    register: Callable[..., Report], hr: User
) -> None:
    register()
    take_export_switch("HR")
    client = _as(hr)
    ids = {"ids": ["1"]}
    assert client.get(f"{_base()}/excel").status_code == 403
    assert _post(client, f"{_base()}/selected/excel", ids).status_code == 403
    assert _post(client, f"{_base()}/selected/csv", ids).status_code == 403
    assert client.get(f"{_base()}/print").status_code == 200
    assert _post(client, f"{_base()}/selected/print", ids).status_code == 200
    assert _post(client, f"{_base()}/selected/copy", ids).status_code == 200


def test_unknown_report_is_404_and_a_person_less_report_has_no_selection(
    register: Callable[..., Report], hr: User
) -> None:
    register(NO_PERSON, person=False)
    client = _as(hr)
    assert client.get("/api/v1/reports/no-such-report/print").status_code == 404
    assert _post(client, "/api/v1/reports/no-such-report/selected/excel", {"ids": ["1"]}).status_code == 404
    assert _post(client, f"{_base(NO_PERSON)}/selected/excel", {"ids": ["1"]}).status_code == 404
    assert _post(client, f"{_base(NO_PERSON)}/selected/copy", {"ids": ["1"]}).status_code == 404
    assert _post(client, f"{_base(NO_PERSON)}/selected/print", {"ids": ["1"]}).status_code == 404
    # the whole-report print and Excel need no person
    assert client.get(f"{_base(NO_PERSON)}/print").status_code == 200
    assert client.get(f"{_base(NO_PERSON)}/excel").status_code == 200


@pytest.mark.parametrize("path", ["selected/excel", "selected/csv", "selected/print", "selected/copy"])
def test_a_refused_selection_is_400_with_its_message(register: Callable[..., Report], hr: User, path: str) -> None:
    register()
    client = _as(hr)
    url = f"{_base()}/{path}"
    response = _post(client, url, {"ids": []})
    assert response.status_code == 400
    assert response.json()["form_errors"] == [NOTHING_PICKED]
    response = _post(client, url, {"ids": ["999"]})
    assert response.status_code == 400
    assert response.json()["form_errors"] == [not_allowed(1)]
    response = _post(client, url, {"ids": [str(i) for i in range(1, 502)]})
    assert response.status_code == 400
    assert response.json()["form_errors"] == [too_many()]


def test_copy_without_a_name_column_is_400_and_writes_no_line(register: Callable[..., Report], hr: User) -> None:
    register(name_column=False)
    before = _export_count("copy_selected")
    response = _post(_as(hr), f"{_base()}/selected/copy", {"ids": ["1"]})
    assert response.status_code == 400
    assert response.json()["form_errors"] == [NO_NAME_COLUMN]
    assert _export_count("copy_selected") == before


def test_a_ticket_of_another_user_or_a_forged_one_is_400(register: Callable[..., Report], hr: User) -> None:
    register()
    ticket = _post(_as(hr), f"{_base()}/selected/print", {"ids": ["1", "2"]}).json()["ticket"]
    other = _user("HR", "api-export-other-hr")
    response = _as(other).get(f"{_base()}/print", {"sel": ticket})
    assert response.status_code == 400
    assert response.json()["form_errors"] == [TICKET_INVALID]
    response = _as(hr).get(f"{_base()}/print", {"sel": "not-a-ticket"})
    assert response.status_code == 400
    assert response.json()["form_errors"] == [TICKET_INVALID]


# --- the audit line: once per call, with the right action -------------------------------------------------------------


def test_each_call_writes_one_audit_line_with_its_action(register: Callable[..., Report], hr: User) -> None:
    register()
    client = _as(hr)
    base = _base()
    ticket = _post(client, f"{base}/selected/print", {"ids": ["1", "3"]}).json()["ticket"]
    calls = [
        ("print_page", lambda: client.get(f"{base}/print")),
        ("export_report", lambda: client.get(f"{base}/excel")),
        ("export_selected", lambda: _post(client, f"{base}/selected/excel", {"ids": ["1"]})),
        ("export_selected", lambda: _post(client, f"{base}/selected/csv", {"ids": ["1"]})),
        ("print_selected", lambda: client.get(f"{base}/print", {"sel": ticket})),
        ("copy_selected", lambda: _post(client, f"{base}/selected/copy", {"ids": ["1"]})),
    ]
    for action, call in calls:
        before, total = _export_count(action), _export_count()
        assert call().status_code == 200
        assert _export_count(action) == before + 1, action
        assert _export_count() == total + 1, action
        assert SystemLogEntry.objects.filter(category="export").order_by("-pk").first().action == action


def test_a_ticket_is_made_without_a_line(register: Callable[..., Report], hr: User) -> None:
    register()
    total = _export_count()
    assert _post(_as(hr), f"{_base()}/selected/print", {"ids": ["1"]}).status_code == 200
    assert _export_count() == total


# --- the print page--------------------------------------------------------------------------------------------------


def test_print_page_has_the_mirror_shape_and_no_store(register: Callable[..., Report], hr: User) -> None:
    register()
    response = _as(hr).get(f"{_base()}/print")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == PRINT_KEYS
    assert date.fromisoformat(body["today"])  # an ISO date text
    assert body["title"] == "Тестийн тайлан"
    assert [head["label"] for head in body["heads"]] == ["Код", "Нэр"]
    assert set(body["heads"][0]) == {"label", "css"}
    assert body["count"] == len(NAMES)
    assert body["shows_count"] is True  # the test report keeps its «Нийт» line
    assert body["grouped"] is False
    assert body["footer"] is None
    assert body["summary"] is None
    assert body["groups"][0]["label"] == ""
    assert set(body["groups"][0]["rows"][0][0]) == {"text", "value", "money", "href", "css", "style", "person"}


def test_print_of_a_selection_is_only_the_picked_people(register: Callable[..., Report], hr: User) -> None:
    register()
    client = _as(hr)
    ticket = _post(client, f"{_base()}/selected/print", {"ids": ["1", "3"]}).json()["ticket"]
    before = _export_count("print_selected")
    response = client.get(f"{_base()}/print", {"sel": ticket, "layout": "chart", "lby": "code"})  # ignored: a ticket
    assert response.status_code == 200
    body = response.json()
    texts = _texts(body["groups"])
    assert "Бат" in texts and "Дорж" in texts and "Ганаа" not in texts
    assert body["count"] == 2
    assert body["shows_count"] is True
    assert body["summary"] is None  # a subset prints no summary
    assert _export_count("print_selected") == before + 1


def test_staff_list_print_carries_the_count_flag(staff: list[Employee], hr: User) -> None:
    body = _as(hr).get(f"/api/v1/reports/{STAFF}/print").json()
    assert body["shows_count"] is True


def test_a_chart_address_prints_its_summary(staff: list[Employee], hr: User) -> None:
    response = _as(hr).get(f"/api/v1/reports/{STAFF}/print", {"layout": "chart", "lby": "department"})
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert set(summary) == SUMMARY_KEYS
    assert len(summary["head"]) == 2
    assert len(summary["lines"]) == 2  # Санхүү and Маркетинг
    assert sorted(line[1] for line in summary["lines"]) == ["1", "2"]  # the counts, as the print shows them


def _summary(money: bool) -> Summary:
    """A summary with a missing figure and a fraction, so the text rules are all visible."""
    return Summary(
        title="Диаграм",
        kind="bar",
        head=["Хэлтэс", "Дүн", "Тоо"],
        lines=[["Санхүү", Decimal("2500000"), 3], ["Маркетинг", None, 1]],
        foot=["Нийт", Decimal("2500000.5"), 4],
        money=money,
        masked=True,
    )


def test_money_summary_figures_are_text_with_grouping_and_the_tugrik_sign(
    monkeypatch: pytest.MonkeyPatch, staff: list[Employee], hr: User
) -> None:
    monkeypatch.setattr("reports.services.print_page.summary_of", lambda table: _summary(money=True))
    summary = _as(hr).get(f"/api/v1/reports/{STAFF}/print", {"layout": "chart"}).json()["summary"]
    # every figure of a money summary goes through mnt, as print.html does; the missing one is a dash
    assert summary["lines"] == [["Санхүү", "2,500,000₮", "3₮"], ["Маркетинг", "—", "1₮"]]
    assert summary["foot"] == ["Нийт", "2,500,000.50₮", "4₮"]
    assert summary["money"] is True
    assert summary["masked"] is True  # a bool, not text


def test_count_summary_figures_are_plain_text_and_a_missing_one_is_a_dash(
    monkeypatch: pytest.MonkeyPatch, staff: list[Employee], hr: User
) -> None:
    monkeypatch.setattr("reports.services.print_page.summary_of", lambda table: _summary(money=False))
    summary = _as(hr).get(f"/api/v1/reports/{STAFF}/print", {"layout": "chart"}).json()["summary"]
    assert summary["lines"] == [["Санхүү", "2500000", "3"], ["Маркетинг", "—", "1"]]
    assert summary["foot"] == ["Нийт", "2500000.5", "4"]
    assert summary["money"] is False


# --- the files-------------------------------------------------------------------------------------------------------


def test_file_headers_and_content_types(register: Callable[..., Report], hr: User) -> None:
    register()
    client = _as(hr)
    today = timezone.localdate().isoformat()  # the day the export names its file with
    excel = client.get(f"{_base()}/excel")
    assert excel.status_code == 200
    assert excel["Content-Type"] == XLSX
    assert excel["Content-Disposition"] == f'attachment; filename="{KEY}-{today}.xlsx"'
    assert excel["Cache-Control"] == "no-store"
    csv_file = _post(client, f"{_base()}/selected/csv", {"ids": ["1"]})
    assert csv_file.status_code == 200
    assert csv_file["Content-Type"] == CSV
    assert csv_file["Content-Disposition"] == f'attachment; filename="{KEY}-selected-{today}.csv"'
    assert csv_file.content.startswith(b"\xef\xbb\xbf")  # UTF-8 with BOM
    selected = _post(client, f"{_base()}/selected/excel", {"ids": ["1"]})
    assert selected["Content-Type"] == XLSX
    assert re.fullmatch(
        rf'attachment; filename="{KEY}-selected-\d{{4}}-\d{{2}}-\d{{2}}\.xlsx"', selected["Content-Disposition"]
    )


def test_selected_excel_holds_only_the_picked_person(register: Callable[..., Report], hr: User) -> None:
    register()
    response = _post(_as(hr), f"{_base()}/selected/excel", {"ids": ["2"]})
    assert response.status_code == 200
    sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
    cells = {c.value for row in sheet.iter_rows() for c in row}
    assert "Ганаа" in cells
    assert "Бат" not in cells and "Дорж" not in cells


def test_a_chart_excel_has_a_summary_sheet_and_a_table_has_one(staff: list[Employee], hr: User) -> None:
    client = _as(hr)
    chart = client.get(f"/api/v1/reports/{STAFF}/excel", {"layout": "chart", "lby": "department"})
    assert chart.status_code == 200
    assert len(openpyxl.load_workbook(io.BytesIO(chart.content)).sheetnames) == 2
    table = client.get(f"/api/v1/reports/{STAFF}/excel")
    assert len(openpyxl.load_workbook(io.BytesIO(table.content)).sheetnames) == 1


# --- the copy--------------------------------------------------------------------------------------------------------


def test_copy_is_the_names_in_report_order(register: Callable[..., Report], hr: User) -> None:
    register()
    response = _post(_as(hr), f"{_base()}/selected/copy", {"ids": ["3", "1"]})
    assert response.status_code == 200
    assert response.json() == {"text": "Бат\nДорж", "count": 2, "dropped": 0}


def test_copy_counts_the_ids_it_dropped(register: Callable[..., Report], hr: User) -> None:
    register()
    body = _post(_as(hr), f"{_base()}/selected/copy", {"ids": ["1", "999"]}).json()
    assert body == {"text": "Бат", "count": 1, "dropped": 1}


def test_copy_of_all_matching_people(register: Callable[..., Report], hr: User) -> None:
    register()
    body = _post(_as(hr), f"{_base()}/selected/copy", {"all": True}).json()
    assert body["count"] == len(NAMES)
    assert body["text"] == "\n".join(NAMES)


# --- a second report, with no route of its own-----------------------------------------------------------------------


def test_a_second_report_with_a_person_works_on_every_route(register: Callable[..., Report], hr: User) -> None:
    register(HELD_OUT)
    client = _as(hr)
    base = _base(HELD_OUT)
    printed = client.get(f"{base}/print")
    assert printed.status_code == 200
    assert printed.json()["title"] == "Тестийн тайлан" and printed.json()["count"] == len(NAMES)
    assert client.get(f"{base}/excel").status_code == 200
    assert _post(client, f"{base}/selected/excel", {"ids": ["1"]}).status_code == 200
    assert _post(client, f"{base}/selected/csv", {"ids": ["1"]}).status_code == 200
    ticket = _post(client, f"{base}/selected/print", {"ids": ["2"]}).json()["ticket"]
    assert client.get(f"{base}/print", {"sel": ticket}).json()["count"] == 1
    assert _post(client, f"{base}/selected/copy", {"ids": ["2"]}).json() == {"text": "Ганаа", "count": 1, "dropped": 0}
    assert _export_count("copy_selected") >= 1  # the line names the report
    assert SystemLogEntry.objects.filter(message__startswith="Тестийн тайлан").exists()


# --- a ticket belongs to its report----------------------------------------------------------------------------------


def test_a_ticket_of_report_a_is_400_on_report_b(register: Callable[..., Report], hr: User) -> None:
    register()
    register(HELD_OUT)
    ticket = _post(_as(hr), f"{_base()}/selected/print", {"ids": ["1"]}).json()["ticket"]
    response = _as(hr).get(f"{_base(HELD_OUT)}/print", {"sel": ticket})
    assert response.status_code == 400
    assert response.json()["form_errors"] == [TICKET_INVALID]
    assert _as(hr).get(f"{_base()}/print", {"sel": ticket}).status_code == 200  # its own report still reads it


def test_the_print_ticket_answer_is_no_store(register: Callable[..., Report], hr: User) -> None:
    register()
    response = _post(_as(hr), f"{_base()}/selected/print", {"ids": ["1"]})
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"


# --- the copy's email column-----------------------------------------------------------------------------------------


def test_copy_has_the_email_after_a_tab_when_the_user_may_see_it(register: Callable[..., Report], hr: User) -> None:
    register(email_needs="")  # an open column: every user may see the report's email
    body = _post(_as(hr), f"{_base()}/selected/copy", {"ids": ["1", "3"]}).json()
    assert body == {"text": "Бат\tu1@example.test\nДорж\tu3@example.test", "count": 2, "dropped": 0}


def test_copy_leaves_the_email_out_when_the_user_may_not_see_it(register: Callable[..., Report], hr: User) -> None:
    register(email_needs="macs.view_salary")  # HR does not hold it, so the column is not the user's to see
    body = _post(_as(hr), f"{_base()}/selected/copy", {"ids": ["1", "3"]}).json()
    assert body == {"text": "Бат\nДорж", "count": 2, "dropped": 0}


# --- privacy: a column the user may not see is nowhere in the answers------------------------------------------------


def test_a_column_the_user_may_not_see_is_absent_from_print_and_copy(register: Callable[..., Report], hr: User) -> None:
    register(secret=True)
    client = _as(hr)
    printed = client.get(f"{_base()}/print")
    assert printed.status_code == 200
    assert "Цалин" not in [head["label"] for head in printed.json()["heads"]]
    assert str(SECRET_SALARY) not in printed.content.decode()
    ticket = _post(client, f"{_base()}/selected/print", {"ids": ["1"]}).json()["ticket"]
    assert str(SECRET_SALARY) not in client.get(f"{_base()}/print", {"sel": ticket}).content.decode()
    copied = _post(client, f"{_base()}/selected/copy", {"all": True}).json()
    assert str(SECRET_SALARY) not in copied["text"]
    assert copied["text"] == "\n".join(NAMES)
