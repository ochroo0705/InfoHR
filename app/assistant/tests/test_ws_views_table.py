"""The workspace table pane (Task 9): `ws_table` runs the tab's saved SQL through ws_run with the tools applied.

No Firebird: the gate seams are patched on sqlanswer and ws_views, and HrHost is patched in ws_run so the fake host
receives the wrapped SQL, which the tests read.
"""

import json
import re

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, Result

from assistant import sqlanswer, ws_run, ws_views
from assistant.models import WorkspaceTab, WorkspaceVersion
from assistant.ws_service import add_version, new_tab

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name")),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))
WITH_N = Catalogue(
    views=(
        View(
            name="GOV_EMPLOYEES",
            description="Employees you may see",
            columns=(Column("ID", "employee id"), Column("NAME", "full name"), Column("N", "a count column")),
        ),
    )
)
EMPTY_CATALOGUE = Catalogue(views=())
BASE_SQL = "SELECT ID, NAME FROM GOV_EMPLOYEES"
BASE_COLUMNS = ("ID", "NAME")
ROWS = [(1, "Aigerim"), (2, "Bat"), (3, None)]
WINDOW = re.compile(r"FIRST (\d+)(?: SKIP (\d+))?")  # the window the checker renders for a page


class FakeHost:
    """Records every SQL it is asked to run. Applies the Firebird window when the SQL has one, so a page past the end
    is empty. Each failure switch makes that kind of run raise (the runner reports it as a refusal)."""

    def __init__(self) -> None:
        self.columns: tuple[str, ...] = BASE_COLUMNS
        self.rows: list[tuple[object, ...]] = list(ROWS)
        self.total = 3
        self.sql: list[str] = []
        self.page_fails = False
        self.count_fails = False
        self.views_empty = False
        self.with_n = False

    def catalogue_for(self, user: object) -> Catalogue:
        if self.views_empty:
            return EMPTY_CATALOGUE
        return WITH_N if self.with_n else CATALOGUE

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.sql.append(query.sql)
        if "COUNT(*)" in query.sql:
            if self.count_fails:
                raise RuntimeError("count failed")
            return Result(columns=("N",), rows=((self.total,),), truncated=False)
        if self.page_fails and "FIRST " in query.sql:
            raise RuntimeError("page failed")
        rows = list(self.rows)
        match = WINDOW.search(query.sql)
        if match:
            skip = int(match.group(2) or 0)
            rows = rows[skip : skip + int(match.group(1))]
        return Result(columns=self.columns, rows=tuple(rows[: limits.max_rows + 1]), truncated=False)

    def cancel(self, user: object) -> None:
        pass

    def page_sql(self) -> str:
        """The last SQL that asked for a page of rows (the checker renders the window as FIRST n SKIP m)."""
        return [text for text in self.sql if "FIRST " in text][-1]


@pytest.fixture(autouse=True)
def _clear_gate_cache() -> None:
    """The gate answer is cached per user for a minute: every test starts with an empty cache."""
    cache.clear()


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """The gate is open for every user: switch on, database ready, one view. A test may change the switch."""
    state: dict[str, object] = {"views": (EMPLOYEES,)}
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)
    monkeypatch.setattr(ws_views, "_catalogue_views", lambda user: state["views"])
    return state


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> FakeHost:
    """The fake host, used by every run the workspace makes."""
    fake = FakeHost()
    monkeypatch.setattr(ws_run, "HrHost", lambda: fake)
    return fake


def _tab(user, sql: str = BASE_SQL, settings: str = "") -> WorkspaceTab:
    tab = new_tab(user, "Тест хүснэгт")
    add_version(tab, "Асуулт", sql, settings)
    return tab


def _url(tab: WorkspaceTab, query: str = "") -> str:
    base = reverse("assistant:ws_table", args=[tab.pk])
    return f"{base}?{query}" if query else base


def _pane(client: Client, url: str) -> str:
    """The pane as htmx asks for it (the fragment alone)."""
    response = client.get(url, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    return response.content.decode()


def test_table_shows_first_page_and_total(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert "Нийт 3 мөр" in html
    assert "Aigerim" in html and "Bat" in html
    assert "1–3 / 3" not in html  # one page: no paging line, the total above the table is enough
    assert "SELECT FIRST 100 " in host.page_sql()  # the page is run as a window of PAGE_SIZE rows
    assert "COUNT(*)" in host.sql[-1]


def test_sort_and_filter_reach_the_sql(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    _pane(client, _url(tab, "sort=NAME:desc&f=ID|gt|1&page=0"))

    page_sql = host.page_sql()
    assert "ORDER BY NAME DESC" in page_sql
    assert "ID > 1" in page_sql
    assert "ID > 1" in host.sql[-1]  # the count respects the same filter


def test_page_param_moves_the_window(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    _pane(client, _url(tab, "page=2"))

    assert "FIRST 100 SKIP 200" in host.page_sql()


def test_page_past_the_last_shows_zero_of_total(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    html = _pane(client, _url(tab, "page=3"))

    assert "FIRST 100 SKIP 300" in host.page_sql()
    assert "Aigerim" not in html
    assert "0 / 3" in html  # no «0–300» range for a page with no rows


def test_huge_page_falls_back_to_the_first_page(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    for query in ("page=9999999", "page=10001"):
        html = _pane(client, _url(tab, query))
        assert "Aigerim" in html
        assert "SKIP" not in host.page_sql()


def test_bad_params_are_ignored(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    query = (
        "page=abc&sort=NOPE:up&sort=ID:sideways&f=NOPE|eq|x&f=ID|bogus|1&f=ID|gt|abc"
        "&f=ID|contains&cols=NOPE&group=NOPE&fcol=NOPE&fop=eq&fval=z"
    )
    response = client.get(_url(tab, query), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert "Aigerim" in response.content.decode()
    assert "SELECT FIRST 100 " in host.page_sql()  # the page fell back to the first one
    assert "SKIP" not in host.page_sql()
    for text in host.sql:
        assert "NOPE" not in text
        assert "bogus" not in text
        assert "abc" not in text
        assert "GROUP BY" not in text


def test_duplicate_sort_keys_keep_the_first(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    _pane(client, _url(tab, "sort=ID:asc&sort=ID:desc&page=0"))

    assert "ORDER BY ID ASC" in host.page_sql()
    assert "ID DESC" not in host.page_sql()


def test_filter_value_with_a_pipe_is_kept_whole(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    _pane(client, _url(tab, "f=NAME|eq|a|b&page=0"))

    assert "'a|b'" in host.page_sql()


def test_filter_value_is_escaped_in_the_chip(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    html = _pane(client, _url(tab, "f=NAME|contains|<b>x</b>&page=0"))

    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>x</b>" not in html


def test_refused_shows_reason_no_rows(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.page_fails = True
    client.force_login(user)

    html = _pane(client, _url(tab, "f=ID|gt|1&page=0"))  # a spec: the refusal shows, the rows do not

    assert "Энэ хүснэгтийг одоо харуулах боломжгүй" in html
    assert "Aigerim" not in html
    assert "could not be run" not in html  # the English reason is never shown


def test_refused_keeps_controls_and_clear_link(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.page_fails = True
    client.force_login(user)

    html = _pane(client, _url(tab, "f=NAME|eq|x&page=0"))

    assert "Энэ хүснэгтийг одоо харуулах боломжгүй" in html
    assert "Шүүх" in html  # the filter form is still there
    assert f'href="{_url(tab, "page=0")}"' in html  # the clear link is still there
    assert tab.current().settings == ""  # a refused run saves nothing

    host.page_fails = False
    assert "Aigerim" in _pane(client, _url(tab, "page=0"))  # the clear link gets the viewer out


def test_no_views_has_its_own_line(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.views_empty = True  # the gate passes, but the run sees no view
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert "Танд асуух өгөгдлийн хүснэгт алга." in html
    assert "Өгөгдлийн сан бэлэн биш" not in html


def test_reason_line_splits_unavailable() -> None:
    assert ws_views._reason_line("unavailable", sqlanswer.NO_VIEWS_REASON) == ws_views.TABLE_REASONS["no_views"]
    assert ws_views._reason_line("unavailable", sqlanswer.UNAVAILABLE_REASON) == ws_views.TABLE_REASONS["unavailable"]
    assert ws_views._reason_line("off", "") == ws_views.TABLE_REASONS["off"]


def test_unusable_column_has_no_controls(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.columns = ("ID", "Full name")  # a name with a space is not a plain identifier
    host.rows = [(1, "Aigerim")]
    client.force_login(user)

    html = _pane(client, _url(tab, "sort=ID:asc&cols=ID,FULL NAME&page=0"))

    assert html.lower().count("full name") == 2  # the header and the cell's phone-card label; no control names it
    assert "sort=ID" in html  # a usable column keeps its sort link
    assert "1 багана хүснэгтийн хэрэгслээр ашиглагдахгүй" in html  # the note says one column is not used by tools
    assert "value=\"FULL" not in html.upper()
    page = host.page_sql()
    select_list = re.search(r"SELECT FIRST \d+ (?:SKIP \d+ )?(.*?) FROM \(", page, re.DOTALL)
    assert select_list is not None
    assert select_list.group(1).upper() == "ID"  # the run selects only the usable column


def test_no_usable_column_shows_rows_without_controls(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.columns = ("Full name", "COUNT(*)")
    host.rows = [("Aigerim", 3)]
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert "Aigerim" in html
    assert "Шүүх" not in html and "sort=" not in html and "Нийт" not in html
    assert "2 багана хүснэгтийн хэрэгслээр ашиглагдахгүй" in html


def test_no_usable_column_cut_note(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.columns = ("Full name",)
    host.rows = [(f"n{i}",) for i in range(101)]
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert html.count("data-ws-row") == 100  # at most PAGE_SIZE rows
    assert "Эхний 100 мөр" in html


def test_settings_saved_on_current_version(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    _pane(client, _url(tab, "sort=NAME:desc&f=ID|gt|1&page=0"))

    saved = json.loads(tab.current().settings)
    assert saved["sort"] == [["NAME", "desc"]]
    assert saved["filters"] == [{"column": "ID", "op": "gt", "value": "1"}]


def test_settings_saved_on_the_last_of_two_versions(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = new_tab(user, "Тест хүснэгт")
    add_version(tab, "Эхний", BASE_SQL, "")
    add_version(tab, "Хоёр дахь", BASE_SQL, "")
    client.force_login(user)

    _pane(client, _url(tab, "sort=NAME:desc&page=0"))

    first, last = tab.versions.order_by("id").first(), tab.versions.order_by("id").last()
    assert first.settings == ""  # the older version is left alone
    assert json.loads(last.settings)["sort"] == [["NAME", "desc"]]


def test_settings_restored_without_params(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)
    _pane(client, _url(tab, "sort=NAME:desc&page=0"))
    host.sql.clear()

    _pane(client, _url(tab))  # the bare address, as the page loads it

    assert "ORDER BY NAME DESC" in host.page_sql()


def test_stray_param_does_not_block_the_restore(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)
    _pane(client, _url(tab, "sort=NAME:desc&page=0"))
    host.sql.clear()

    _pane(client, _url(tab, "_=123"))  # a cache-buster is not a table parameter

    assert "ORDER BY NAME DESC" in host.page_sql()


def test_nul_filter_is_dropped_and_not_saved(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    response = client.get(_url(tab, "f=ID|eq|%00&page=0"), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    saved = tab.current().settings
    assert "\x00" not in saved and "u0000" not in saved
    assert json.loads(saved)["filters"] == []
    assert "Aigerim" in _pane(client, _url(tab))  # the next bare load shows normal rows


def test_group_by_n_is_dropped_and_not_saved(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user, "SELECT ID, N FROM GOV_EMPLOYEES")
    host.with_n = True  # the view has a column named N: the count uses that name, so it cannot be grouped
    host.columns = ("ID", "N")
    host.rows = [(1, 5), (2, 6), (3, 7)]
    client.force_login(user)

    response = client.get(_url(tab, "group=n&page=0"), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert json.loads(tab.current().settings)["group_by"] == ""
    html = _pane(client, _url(tab))
    assert "Нийт 3 мөр" in html  # not «бүлэг»: the rows are not grouped


def test_cell_text_is_escaped(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.rows = [(1, "<b>x</b>")]
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>x</b>" not in html


def test_total_none_shows_dash(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.count_fails = True
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert "Нийт: —" in html
    assert "Aigerim" in html  # the rows still show


def test_other_users_tab_404(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    owner = role_user("staff")
    intruder = role_user("staff")
    tab = _tab(owner)
    client.force_login(intruder)

    assert client.get(_url(tab)).status_code == 404
    assert host.sql == []  # nothing ran for the intruder


def test_gate_off_gives_404(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    cache.clear()  # the gate changed within this test

    assert client.get(_url(tab)).status_code == 404
    assert host.sql == []


def test_empty_tab_shows_empty_state(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = new_tab(user, "Хоосон")  # no version yet
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert "Хүснэгт хараахан хоосон байна" in html
    assert host.sql == []


def test_plain_request_gets_the_whole_page(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    response = client.get(_url(tab, "page=0"))

    html = response.content.decode()
    assert response.status_code == 200
    assert 'id="ws-chat-pane"' in html  # the whole workspace page, so the links work without the script
    assert "Aigerim" in html


def test_workspace_page_loads_the_table_pane(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    html = client.get(reverse("assistant:workspace_tab", args=[tab.pk])).content.decode()

    assert f'hx-get="{_url(tab)}"' in html
    assert 'hx-trigger="load, ws-table-changed from:body"' in html


def test_history_restore_gets_the_whole_page(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    restored = client.get(
        _url(tab, "page=0"), HTTP_HX_REQUEST="true", HTTP_HX_HISTORY_RESTORE_REQUEST="true"
    ).content.decode()
    fragment = client.get(_url(tab, "page=0"), HTTP_HX_REQUEST="true").content.decode()

    assert 'id="ws-chat-pane"' in restored  # a back or forward step gets the whole page
    assert 'aria-label="Хүснэгтүүд"' in restored  # with the tab strip
    assert "Aigerim" in restored
    assert 'id="ws-chat-pane"' not in fragment  # a normal htmx request still gets the pane alone
    assert "Aigerim" in fragment


def test_wrapped_refusal_with_empty_spec_shows_plain_rows(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.page_fails = True  # the wrapped run is refused; the saved query itself still runs
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert "Aigerim" in html and "Bat" in html  # the plain rows, so the viewer is not stuck
    assert "Шүүх" not in html  # with no tools
    assert "Энэ хүснэгтийг одоо харуулах боломжгүй" not in html
    assert tab.current().settings == ""  # nothing saved


def test_duplicate_column_names_have_no_tools(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.columns = ("ID", "id")  # the same name twice, in any case: the wrapper could not tell them apart
    host.rows = [(1, 1)]
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert "2 багана хүснэгтийн хэрэгслээр ашиглагдахгүй" in html
    assert "Шүүх" not in html
    assert "sort=" not in html


def test_settings_save_survives_a_concurrent_delete(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    original = ws_run.run_page

    def run_then_delete(viewer, base_sql, columns, spec, page, host=None):
        result = original(viewer, base_sql, columns, spec, page, host=host)
        WorkspaceVersion.objects.filter(tab=tab).delete()  # an undo in another request, between run and save
        return result

    monkeypatch.setattr(ws_run, "run_page", run_then_delete)
    client.force_login(user)

    response = client.get(_url(tab, "sort=NAME:desc&page=0"), HTTP_HX_REQUEST="true")

    assert response.status_code == 200  # no 500 from the save
    assert not WorkspaceVersion.objects.filter(tab=tab).exists()


def test_table_markup_for_phone_keyboard_and_screen_reader(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    """String checks only: the card labels, the aria-sort, the row box names and the sort hook that returns focus."""
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    html = _pane(client, _url(tab, "sort=NAME:desc&page=0"))

    assert 'class="ptable ws-cards"' in html
    assert 'data-label="NAME"' in html and 'data-label="ID"' in html  # a phone card names every value
    assert 'aria-sort="descending"' in html and html.count("aria-sort=") == 1
    assert 'data-ws-sort="NAME"' in html
    assert 'aria-label="Мөр сонгох: 1"' in html  # a row box is named by the row's first value
    assert "Бүгдийг сонгох" in html  # the select-all box a phone shows (the header row is hidden there)


def test_empty_tab_note_is_plain_guidance_not_a_warning(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    from assistant.ws_service import new_tab

    user = role_user("staff")
    tab = new_tab(user)
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert "Хүснэгт хараахан хоосон байна" in html
    assert "bg-amber-50" not in html


def test_model_labels_show_in_the_table_header(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    host.columns = ("ID", "ACTIVE_COUNT")  # an alias the governed views do not know: no view label
    host.rows = [(1, 5), (2, 7)]
    tab = new_tab(user, "Тест хүснэгт")
    add_version(tab, "Асуулт", BASE_SQL, "", labels='{"ACTIVE_COUNT": "Ажилтны тоо"}')
    client.force_login(user)

    html = _pane(client, _url(tab))

    assert "Ажилтны тоо" in html
    assert ">ACTIVE_COUNT<" not in html  # the header shows the heading, not the alias
