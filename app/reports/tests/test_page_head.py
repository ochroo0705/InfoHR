"""The report page's head as a request-free service (reports.services.page_head): the default-view redirect, the saved
view options and the one the address matches, the tool flags with their export and selection rights, the staff actions,
the title and the layout switcher. The Django page and the React API both read it."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from accounts.models import User
from config import batching
from django.contrib.auth import get_user_model
from django.db import connection
from django.http import QueryDict
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from macs.models import Branch, Department, Position

from reports import selection, views
from reports.filters import parse_filters
from reports.models import SavedView
from reports.registry import REPORTS
from reports.services import page_head as page_head_service
from reports.services.page_head import PageHead, default_view_redirect, page_head
from reports.table import build_table
from reports.tests.conftest import _make_user
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

KEY = "staff-list"
PATH = f"/reports/{KEY}/"
REPORT_URL = f"/reports/{KEY}/"
COLS = "cols=code&cols=email"


@pytest.fixture
def report() -> Report:
    return REPORTS[KEY]


def _head(user: User, report: Report, query: str = "", is_htmx: bool = False) -> PageHead:
    request_get = QueryDict(query)
    table = build_table(report, user, parse_filters(request_get))
    return page_head(request_get, is_htmx, PATH, user, report, table, plain=bool(report.saved_views))


def _view(author: User, name: str, query: str = COLS, visibility: str = "shared", default: bool = False) -> SavedView:
    return SavedView.objects.create(
        report=KEY, name=name, query=query, author=author, visibility=visibility, is_default=default
    )


def _no_rights_user() -> User:
    """A user with no role group: no export right, no staff management, no checklist start."""
    return get_user_model().objects.create_user("head-plain", password="x-long-pass-123")  # noqa: S106


def test_bare_address_redirects_to_visible_default_view(hr_user: User, report: Report) -> None:
    _view(hr_user, "Үндсэн", default=True)
    expected = f"{REPORT_URL}?{COLS}"
    assert default_view_redirect(QueryDict(""), False, "GET", hr_user, report) == expected
    assert _head(hr_user, report).redirect == expected


def test_view_plain_never_redirects(hr_user: User, report: Report) -> None:
    _view(hr_user, "Үндсэн", default=True)
    assert default_view_redirect(QueryDict("view=plain"), False, "GET", hr_user, report) == ""
    assert _head(hr_user, report, "view=plain").redirect == ""


def test_htmx_and_post_never_redirect(hr_user: User, report: Report) -> None:
    _view(hr_user, "Үндсэн", default=True)
    assert default_view_redirect(QueryDict(""), True, "GET", hr_user, report) == ""
    assert default_view_redirect(QueryDict(""), False, "POST", hr_user, report) == ""


def test_private_default_of_another_user_is_not_followed(hr_user: User, report: Report) -> None:
    other = _make_user("HR", "head-other")
    _view(other, "Чужой", visibility="private", default=True)
    assert default_view_redirect(QueryDict(""), False, "GET", hr_user, report) == ""
    assert _head(hr_user, report).redirect == ""


def test_saved_none_when_report_has_no_saved_views(hr_user: User, report: Report) -> None:
    plain = replace(report, saved_views=False)
    head = _head(hr_user, plain)
    assert head.saved is None
    assert head.title == report.title


def test_options_list_views_the_user_may_see_then_templates(hr_user: User, report: Report) -> None:
    other = _make_user("HR", "head-other-two")
    _view(hr_user, "Холбоо")
    _view(hr_user, "Миний", visibility="private")
    _view(other, "Тусгай", visibility="private")
    saved = _head(hr_user, report).saved
    assert saved is not None
    assert {o.name for o in saved.options} == {"Холбоо", "Миний (хувийн)"}
    assert saved.plain_url == REPORT_URL + "?view=plain"
    template_names = {t.name for t in report.templates}
    assert saved.templates and {o.name for o in saved.templates} <= template_names


def test_current_view_matches_cleaned_address(hr_user: User, report: Report) -> None:
    view = _view(hr_user, "Холбоо")
    saved = _head(hr_user, report, f"{COLS}&bogus=1&sort=--x").saved
    assert saved is not None
    assert saved.current_view is not None and saved.current_view.pk == view.pk
    assert saved.template_current is False
    assert saved.can_edit_view is True
    assert [o.selected for o in saved.options] == [True]

    other = _make_user("HR", "head-viewer")
    assert _head(other, report, COLS).saved.can_edit_view is False  # type: ignore[union-attr]


def test_tools_follow_report_flags_and_export_right(hr_user: User, report: Report) -> None:
    tools = _head(hr_user, report).tools
    assert tools.columns is report.picks_columns
    assert tools.rules is report.shows_count
    assert tools.format is True  # a table layout: the format pop-up is offered
    assert tools.print_url.startswith(reverse("reports:print", args=[KEY]))
    assert tools.excel_url.startswith(reverse("reports:excel", args=[KEY]))

    plain_tools = _head(_no_rights_user(), report).tools
    assert plain_tools.excel_url == ""
    assert plain_tools.print_url.startswith(reverse("reports:print", args=[KEY]))


def test_staff_actions_only_for_staff_list_and_managers(hr_user: User, report: Report) -> None:
    assert _head(hr_user, report).tools.staff_actions is hr_user.has_perm("macs.manage_employees")
    admin = _make_user("Admin", "head-admin")
    assert _head(admin, report).tools.staff_actions is True
    assert _head(_no_rights_user(), report).tools.staff_actions is False
    other_key = replace(report, key="other-list")
    assert _head(admin, other_key).tools.staff_actions is False


def test_selection_urls_empty_without_right(hr_user: User, report: Report) -> None:
    urls = _head(_no_rights_user(), report).tools.selection_urls
    assert urls["excel"] == "" and urls["csv"] == "" and urls["checklist"] == ""
    assert urls["print"] and urls["copy"]
    hr_urls = _head(hr_user, report).tools.selection_urls
    assert hr_urls["excel"] == reverse("reports:sel_excel", args=[KEY])


def test_batch_answer_does_no_saved_view_work(client: Client, login_hr: User, monkeypatch: pytest.MonkeyPatch) -> None:
    """A «Цааш харуулах» batch answers its rows only: the page head (saved views, switcher) is not built for it, while a
    full page builds it once."""
    _view(login_hr, "Холбоо")
    calls: list[str] = []
    real_page_head, real_saved_head = views.page_head, page_head_service.saved_head

    def spy_page_head(*args: object, **kwargs: object) -> object:
        calls.append("page_head")
        return real_page_head(*args, **kwargs)  # type: ignore[arg-type]

    def spy_saved_head(*args: object, **kwargs: object) -> object:
        calls.append("saved_head")
        return real_saved_head(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(views, "page_head", spy_page_head)
    monkeypatch.setattr(page_head_service, "saved_head", spy_saved_head)

    batch = client.get(f"{PATH}?{COLS}&offset=5", HTTP_HX_REQUEST="true")
    assert batch.status_code == 200
    assert calls == []

    full = client.get(f"{PATH}?{COLS}")
    assert full.status_code == 200
    assert calls == ["page_head", "saved_head"]


def test_htmx_batch_reads_no_option_lists(client: Client, login_hr: User, monkeypatch: pytest.MonkeyPatch) -> None:
    """A «Цааш харуулах» batch draws its rows only: the filter bar's option lists (branches, departments, positions) are
    not read for it. The full page for the same address reads them (the positive control), and runs more queries."""
    rows = [SimpleNamespace(name=f"Нэр {i}") for i in range(5)]
    key = "batch-options-test"
    report = Report(
        key=key,
        title="Тест",
        filters=("branch", "department", "position"),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name),),
        default_columns=("name",),
        rows=lambda user, f: rows,
    )
    monkeypatch.setitem(REPORTS, key, report)
    monkeypatch.setattr(batching, "LIST_BATCH", 2)
    path = f"/reports/{key}/"
    option_tables = (Branch._meta.db_table, Department._meta.db_table, Position._meta.db_table)

    def reads_options(ctx: CaptureQueriesContext) -> bool:
        return any(f'"{t}"' in q["sql"] for q in ctx.captured_queries for t in option_tables)

    with CaptureQueriesContext(connection) as full:
        assert client.get(f"{path}?cols=name").status_code == 200
    with CaptureQueriesContext(connection) as batch:
        answer = client.get(f"{path}?cols=name&offset=2", HTTP_HX_REQUEST="true")
    assert answer.status_code == 200
    assert "Нэр 2" in answer.content.decode()
    assert "Нэр 0" not in answer.content.decode()
    assert reads_options(full), "the full page should read the option lists (positive control)"
    assert not reads_options(batch)
    assert len(batch.captured_queries) < len(full.captured_queries)


def test_selection_max_is_the_live_cap(hr_user: User, report: Report, monkeypatch: pytest.MonkeyPatch) -> None:
    """The head carries the cap read at call time, for every report (selectable or not)."""
    assert _head(hr_user, report).selection_max == selection.MAX_PEOPLE == 500
    monkeypatch.setattr(selection, "MAX_PEOPLE", 7)
    assert _head(hr_user, report).selection_max == 7
    assert _head(_no_rights_user(), report).selection_max == 7
