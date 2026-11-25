"""GET /api/v1/reports/{key} and GET /api/v1/reports/{key}/rows: the report page's table layout, as React reads it.

The rules come from reports.services (table_page, page_head, filter_bar) and the registry; these tests pin the API's
shape, its rights (401 without a login, 403 when the user cannot open the report, 404 for an unknown key), the redirect
to the default saved view, the batches, and the review-focus inputs: a column the user may not see, a person the user
may not see, HTML typed into a cell, and a query count that does not grow with the rows.
"""

from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from accounts.models import User
from config import batching
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from employees.models import Employee
from macs.models import Branch, Department, Position
from reports.filters import Filters
from reports.models import SavedView
from reports.registry import REPORTS
from reports.types import Column, Report

from api.tests.logs_support import NOT_LOGGED_IN, hr, job_values, scoped  # noqa: F401

pytestmark = pytest.mark.django_db

KEY = "api-report-page-test"
URL = f"/api/v1/reports/{KEY}"
ROWS_URL = f"/api/v1/reports/{KEY}/rows"
FORBIDDEN = {"field_errors": {}, "form_errors": ["Хандах эрх байхгүй."], "code": "forbidden"}
NAMES = ("Бат", "Ганаа", "Дорж", "Номин", "Сараа")
SECRET_SALARY = 731415  # the value of the salary column in the rows below; must never reach a user without the right

PAGE_KEYS = {"redirect", "title", "layout", "head", "bar", "table"}
HEAD_KEYS = {
    "title",
    "saved",
    "tools",
    "layouts",
    "staff_actions",
    "selectable",
    "selection_urls",
    "print_url",
    "excel_url",
}
SAVED_KEYS = {"plain_url", "options", "templates", "current_view", "template_current", "can_edit_view", "save_url"}
BAR_KEYS = {"items", "picker", "column_chips", "adds", "clear_url", "columns_query", "options"}
TABLE_KEYS = {
    "heads",
    "groups",
    "next_offset",
    "count",
    "shows_count",
    "rules_text",
    "clear_rules_url",
    "note",
    "footer",
    "selectable",
    "check_css",
    "check_style",
    "table_span",
    "pin",
    "address",
    "query",
}
CELL_KEYS = {"text", "value", "money", "href", "css", "style", "person"}


def _client(role: str | None) -> Client:
    client = Client()
    if role is not None:
        name = f"report_page_api_{role.lower()}"
        user = User.objects.filter(username=name).first()
        if user is None:  # a test may ask for the same role twice
            user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
            user.groups.add(Group.objects.get(name=role))
        client.force_login(User.objects.get(pk=user.pk))
    return client


def _as(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _default_rows(user: User, f: Filters) -> list[Any]:
    return [SimpleNamespace(name=name, salary=SECRET_SALARY) for name in NAMES]


def _register(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: Callable[[User, Filters], list[Any]] = _default_rows,
    filters: tuple[str, ...] = (),
    layouts: tuple[str, ...] = (),
    saved_views: bool = True,
) -> Report:
    report = Report(
        key=KEY,
        title="Тестийн тайлан",
        filters=filters,
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name),
            Column(
                key="salary",
                label="Цалин",
                value=lambda r: r.salary,
                needs="macs.view_salary",
                numeric=True,
                money=True,
            ),
        ),
        default_columns=("name",),
        rows=rows,
        saved_views=saved_views,
        layouts=layouts,
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _get(client: Client, url: str = URL, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.get(url, params or {})
    assert response.status_code == 200, response.content.decode()
    body: dict[str, Any] = response.json()
    return body


def _names(body: dict[str, Any]) -> list[str]:
    return [row[0]["text"] for group in body["table"]["groups"] for row in group["rows"]]


def _text(body: Any) -> str:
    """Every string in an answer, joined: to look for a value that must not appear anywhere."""
    if isinstance(body, dict):
        return " ".join(_text(v) for v in body.values())
    if isinstance(body, list):
        return " ".join(_text(v) for v in body)
    return "" if body is None else str(body)


def _branches(count: int, start: int = 0) -> None:
    for i in range(start, start + count):
        Branch.objects.create(name=f"Салбар {i:03d}")


# --- rights and the unknown key -----------------------------------------------------------------------------------


def test_report_requires_login(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    response = _client(None).get(URL)
    assert response.status_code == 401
    assert response.json() == NOT_LOGGED_IN


def test_unknown_report_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    assert _client("HR").get("/api/v1/reports/no-such-report").status_code == 404
    assert _client("HR").get("/api/v1/reports/no-such-report/rows").status_code == 404


def test_report_403_when_user_cannot_open(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    response = _client("Employee").get(URL)  # an Employee has no reports.view_reports
    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert _client("Employee").get(ROWS_URL).status_code == 403


# --- shape --------------------------------------------------------------------------------------------------------


def test_report_shape_for_a_table_report(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    body = _get(_client("HR"))
    assert set(body) == PAGE_KEYS
    assert body["redirect"] == ""
    assert body["title"] == "Тестийн тайлан"
    assert body["layout"] == "table"
    assert set(body["head"]) == HEAD_KEYS
    assert set(body["head"]["tools"]) == {"columns", "rules", "format"}
    assert set(body["head"]["saved"]) == SAVED_KEYS
    assert set(body["bar"]) == BAR_KEYS
    assert set(body["table"]) == TABLE_KEYS
    assert [head["label"] for head in body["table"]["heads"]] == ["Нэр"]
    assert set(body["table"]["heads"][0]) == {"label", "href", "append_href", "arrow", "css", "sticky_left"}
    assert set(body["table"]["groups"][0]["rows"][0][0]) == CELL_KEYS
    assert body["table"]["count"] == len(NAMES)
    assert body["table"]["next_offset"] is None
    assert _names(body) == list(NAMES)


def test_column_chip_answers_its_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    # the chip's parameter names come from the server (React must not build them): a range chip has _from and _to
    report = _register(monkeypatch)
    hired_column = Column(key="first_hire_date", label="Ажилд орсон", value=lambda r: "")
    monkeypatch.setitem(
        REPORTS, KEY, replace(report, column_filters=("hired",), columns=(*report.columns, hired_column))
    )
    body = _get(_client("HR"), params={"add": "hired"})  # `add` shows the chip with no value yet
    (chip,) = body["bar"]["column_chips"]
    assert chip["name"] == "hired"
    assert chip["params"] == ["hired_from", "hired_to"]
    assert chip["values"] == ["", ""]


def test_report_redirect_for_default_saved_view(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    client = _client("HR")
    author = User.objects.get(username="report_page_api_hr")
    SavedView.objects.create(
        report=KEY, name="Үндсэн", query="cols=name", author=author, visibility="shared", is_default=True
    )
    body = _get(client)
    assert body["redirect"].startswith(f"/reports/{KEY}/?")
    assert body["redirect"] != f"/reports/{KEY}/"
    assert body["title"] == ""
    assert body["layout"] == ""
    assert body["head"] is None
    assert body["bar"] is None
    assert body["table"] is None
    # the target has a query, so it is answered in full (no loop) when followed
    followed = _get(client, URL, {"view": "plain"})
    assert followed["redirect"] == ""
    assert followed["table"] is not None


def test_report_other_layout_has_no_table(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch, layouts=("cards",))
    body = _get(_client("HR"), URL, {"layout": "cards"})
    assert body["redirect"] == ""
    assert body["layout"] == "cards"
    assert body["table"] is None
    assert body["head"] is not None
    assert body["bar"] is not None
    current = [option for option in body["head"]["layouts"] if option["current"]]
    assert [option["name"] for option in current] == ["cards"]


def test_report_no_store(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch)
    client = _client("HR")
    assert client.get(URL).headers["Cache-Control"] == "no-store"
    assert client.get(ROWS_URL).headers["Cache-Control"] == "no-store"


# --- batches ------------------------------------------------------------------------------------------------------


def test_rows_batch_matches_page_first_batch_and_next(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    _register(monkeypatch)
    client = _client("HR")
    first = _get(client, URL, {"cols": "name"})
    assert _names(first) == list(NAMES[:2])
    assert first["table"]["next_offset"] == 2
    second = _get(client, ROWS_URL, {"cols": "name", "offset": "2"})
    assert set(second) == {"groups", "next_offset"}
    assert [row[0]["text"] for row in second["groups"][0]["rows"]] == list(NAMES[2:4])
    assert second["next_offset"] == 4
    last = _get(client, ROWS_URL, {"cols": "name", "offset": "4"})
    assert [row[0]["text"] for row in last["groups"][0]["rows"]] == list(NAMES[4:])
    assert last["next_offset"] is None
    # a bad or huge offset starts at the first batch
    assert _get(client, ROWS_URL, {"cols": "name", "offset": "-3"})["groups"] == first["table"]["groups"]


# --- review focus: what the user may not see never reaches the body -----------------------------------------------


def test_unseen_column_not_in_body(monkeypatch: pytest.MonkeyPatch) -> None:
    # HR lacks macs.view_salary: the salary column, its sort, its rule and its column filter are all dropped
    _register(monkeypatch)
    rule = '{"op":"and","items":[{"c":"salary","o":"gt","v":"0"}]}'
    body = _get(_client("HR"), URL, {"cols": "name,salary", "sort": "salary", "rules": rule})
    text = _text(body)
    assert "Цалин" not in text
    assert str(SECRET_SALARY) not in text
    assert "salary" not in text
    assert [head["label"] for head in body["table"]["heads"]] == ["Нэр"]
    assert _names(body) == list(NAMES)


def test_hidden_person_not_in_body(monkeypatch: pytest.MonkeyPatch, scoped: tuple[Employee, Employee, User]) -> None:  # noqa: F811
    # `limited` sees the north branch only: the outsider in the address is dropped, and so is their name
    inside, outside, limited = scoped
    _register(monkeypatch, filters=("employee",))
    shown = _get(_as(limited), URL, {"employee": str(inside.pk)})
    assert "Дотно" in _text(shown["bar"])  # the visible person is offered in the bar
    hidden = _get(_as(limited), URL, {"employee": str(outside.pk)})
    text = _text(hidden)
    assert "Гадна" not in text
    assert "Мөнх" not in text
    assert f"employee={outside.pk}" not in text
    assert _names(hidden) == list(NAMES)


# --- review focus: cell text is text --------------------------------------------------------------------------------


def test_html_in_cell_is_returned_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "<b>Тест</b>"
    _register(monkeypatch, rows=lambda user, f: [SimpleNamespace(name=raw, salary=1)])
    body = _get(_client("HR"), URL, {"cols": "name"})
    cell = body["table"]["groups"][0]["rows"][0][0]
    assert cell["text"] == raw
    assert cell["value"] == raw


# --- review focus: the query count does not grow with the rows ----------------------------------------------------


def _queries(client: Client) -> tuple[int, int]:
    with CaptureQueriesContext(connection) as ctx:
        body = _get(client, URL, {"cols": "name"})
    return len(ctx.captured_queries), len(_names(body))


def test_query_count_is_flat_for_200_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", 500)  # one batch holds every row, so the cells are all converted
    _register(monkeypatch, rows=lambda user, f: list(Branch.objects.order_by("name")))
    _branches(20)
    client = _client("HR")
    _queries(client)  # warm the caches once, so the two counts compare like with like
    small_count, small_rows = _queries(client)
    _branches(180, start=20)
    large_count, large_rows = _queries(client)
    assert large_rows == small_rows + 180
    assert large_count == small_count


def test_rows_route_reads_no_option_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    """A batch draws no filter bar, so it runs none of the drawn dropdowns' option queries (branches, departments,
    positions); the page for the same address does (the positive control), and it runs more queries than the batch."""
    _register(monkeypatch, filters=("branch", "department", "position"), saved_views=False)
    client = _client("HR")
    _get(client, URL, {"cols": "name"})  # warm the caches once
    with CaptureQueriesContext(connection) as page_ctx:
        _get(client, URL, {"cols": "name"})
    with CaptureQueriesContext(connection) as rows_ctx:
        _get(client, ROWS_URL, {"cols": "name", "offset": "0"})
    option_tables = (Branch._meta.db_table, Department._meta.db_table, Position._meta.db_table)

    def touches(ctx: CaptureQueriesContext) -> list[str]:
        return [q["sql"] for q in ctx.captured_queries for table in option_tables if f'"{table}"' in q["sql"]]

    assert touches(page_ctx), "the page should read the option lists (positive control)"
    assert touches(rows_ctx) == []
    assert len(rows_ctx.captured_queries) < len(page_ctx.captured_queries)
