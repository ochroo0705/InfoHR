"""Export of the workspace table (Task 11): the Excel file, the print page and the copied text cover every row under the
address's sort, filters and columns, up to EXPORT_MAX_ROWS. The page parameter is ignored.

No Firebird: the fake host and the gate fixtures come from test_ws_views_table, and HrHost is patched in ws_run.
"""

import io
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import unquote

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from assistant import sqlanswer, ws_excel, ws_run, ws_views
from assistant.tests.test_ws_views_table import (  # noqa: F401 (fixtures and helpers of the table tests)
    BASE_SQL,
    FakeHost,
    _clear_gate_cache,
    _pane,
    _tab,
    _url,
    gate,
    host,
)
from assistant.ws_limits import EXPORT_MAX_ROWS, EXPORT_TIMEOUT_S
from assistant.ws_service import add_version, new_tab

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REFUSED_LINE = "Энэ хүснэгтийг одоо харуулах боломжгүй байна. Шүүлтүүрээ арилгаад үзнэ үү."  # ws_views.TABLE_REASONS
EXPORTS = ("ws_excel", "ws_print", "ws_copy")


def _get(client: Client, tab, name: str, query: str = ""):
    base = reverse(f"assistant:{name}", args=[tab.pk])
    return client.get(f"{base}?{query}" if query else base)


def _sheet(content: bytes):
    return load_workbook(io.BytesIO(content)).active


def _refuse_when(host: FakeHost, monkeypatch: pytest.MonkeyPatch, marker: str) -> None:
    """The fake host raises (the runner reports a refusal) for any run whose SQL contains the marker."""
    original = host.execute

    def execute(user, query, limits):
        if marker in query.sql:
            raise RuntimeError("refused for the test")
        return original(user, query, limits)

    monkeypatch.setattr(host, "execute", execute)


def test_excel_has_all_rows_and_header(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.rows = [(i, f"n{i}") for i in range(1, 251)]  # 250 rows: more than one page
    client.force_login(user)

    response = _get(client, tab, "ws_excel")

    assert response.status_code == 200
    assert response["Content-Type"] == XLSX
    rows = list(_sheet(response.content).iter_rows(values_only=True))
    assert len(rows) == 251  # the header and every row
    assert rows[0] == ("ID", "NAME")
    assert rows[1] == (1, "n1")
    assert rows[-1] == (250, "n250")


def test_excel_cut_note_when_over_ceiling(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    monkeypatch.setattr(ws_run, "EXPORT_MAX_ROWS", 5)
    host.rows = [(i, f"n{i}") for i in range(1, 9)]  # 8 rows: the ceiling of 5 cuts them
    client.force_login(user)

    response = _get(client, tab, "ws_excel")

    rows = list(_sheet(response.content).iter_rows(values_only=True))
    assert rows[0][0] == "Эхний 5 мөрийг харуулав"  # the note is the first row
    assert rows[1] == ("ID", "NAME")
    assert len(rows) == 7  # note, header, five rows


def test_excel_respects_sort_and_filter_and_ignores_page(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    response = _get(client, tab, "ws_excel", "sort=NAME:desc&f=ID|gt|1&page=3")

    assert response.status_code == 200
    assert any("ORDER BY NAME DESC" in text and "ID > 1" in text for text in host.sql)
    assert all("FIRST" not in text for text in host.sql)  # no page window: every row


def test_export_without_params_uses_the_saved_settings(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)
    _pane(client, _url(tab, "sort=NAME:desc&page=0"))  # the table saves the sort on the current version
    host.sql.clear()

    _get(client, tab, "ws_excel")

    assert any("ORDER BY NAME DESC" in text for text in host.sql)


def test_excel_cells_starting_with_formula_characters_are_text(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.rows = [(1, "=1+1"), (2, "@x"), (3, "+5"), (4, "-2")]
    client.force_login(user)

    sheet = _sheet(_get(client, tab, "ws_excel").content)

    for row in range(2, 6):
        cell = sheet.cell(row=row, column=2)
        assert cell.data_type != "f"  # never a formula
        assert cell.data_type == "s"
    assert sheet["B2"].value == "=1+1"
    assert sheet["B3"].value == "@x"


def test_print_lists_rows_and_escapes_text(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.rows = [(1, "<b>x</b>"), (2, "Bat")]
    client.force_login(user)

    response = _get(client, tab, "ws_print", "f=ID|gt|0")

    html = response.content.decode()
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>x</b>" not in html
    assert "Bat" in html
    assert "ID их" in html  # the filter as the chip words it
    assert "Нийт: 2" in html
    assert "window.print()" in html


def test_print_cut_note_when_over_ceiling(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    monkeypatch.setattr(ws_run, "EXPORT_MAX_ROWS", 1)
    client.force_login(user)

    html = _get(client, tab, "ws_print").content.decode()

    assert "Эхний 1 мөр." in html


def test_copy_returns_tsv_with_header(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    response = _get(client, tab, "ws_copy")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert response.content.decode() == "ID\tNAME\n1\tAigerim\n2\tBat\n3\t"  # an empty cell is an empty field
    assert "X-Cut" not in response


def test_copy_marks_a_cut_result(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    monkeypatch.setattr(ws_run, "EXPORT_MAX_ROWS", 2)
    client.force_login(user)

    response = _get(client, tab, "ws_copy")

    assert response["X-Cut"] == "1"
    assert response.content.decode().count("\n") == 2  # header and two rows


@pytest.mark.parametrize("name", EXPORTS)
def test_export_other_users_tab_404(db: None, client: Client, role_user, gate, host: FakeHost, name: str) -> None:
    owner = role_user("staff")
    intruder = role_user("staff")
    tab = _tab(owner)
    client.force_login(intruder)

    assert _get(client, tab, name).status_code == 404
    assert host.sql == []  # nothing ran for the intruder


@pytest.mark.parametrize("name", EXPORTS)
def test_export_gate_off_404(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    cache.clear()  # the gate changed within this test

    assert _get(client, tab, name).status_code == 404
    assert host.sql == []


@pytest.mark.parametrize("name", EXPORTS)
def test_refused_export_gives_no_file_and_a_mongolian_line(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    _refuse_when(host, monkeypatch, "ID > 1")
    client.force_login(user)

    response = _get(client, tab, name, "f=ID|gt|1")

    assert response.status_code == 409
    assert response["Content-Type"].startswith("text/plain")
    assert response.content.decode() == REFUSED_LINE  # the reason is never shown, only the Mongolian line
    assert not response.content.startswith(b"PK")  # no workbook


def test_title_with_illegal_characters_gives_safe_file_and_sheet_names(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = new_tab(user, 'Отчет: a/b\\c*"d"?<x>|[y]')
    add_version(tab, "Асуулт", BASE_SQL, "")
    client.force_login(user)

    response = _get(client, tab, "ws_excel")

    disposition = response["Content-Disposition"]
    name = unquote(re.search(r"filename\*=UTF-8''(.+)$", disposition).group(1))
    assert name.startswith("Отчет")
    assert name.endswith(".xlsx")
    for character in '\\/:*?"<>|':
        assert character not in name
    sheet_name = load_workbook(io.BytesIO(response.content)).sheetnames[0]
    assert len(sheet_name) <= 31
    for character in "\\/?*[]:":
        assert character not in sheet_name


def test_table_offers_export_links_and_row_ticks(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    html = _pane(client, _url(tab, "sort=NAME:desc&page=0"))

    excel = reverse("assistant:ws_excel", args=[tab.pk])
    assert f'href="{excel}?sort=NAME%3Adesc&amp;page=0"' in html  # the same spec, all rows
    assert "data-ws-bar" in html and "data-ws-table" in html
    assert "data-ws-all" in html
    assert html.count("data-ws-row ") == 3  # one tick box per drawn row


def test_excel_bytes_types_and_empty_cells() -> None:
    data = ws_excel.ws_excel_bytes(
        ("ID", "NAME", "AMOUNT", "WHEN"),
        [(1, "a", Decimal("12.50"), date(2026, 1, 5)), (2, None, None, None)],
        "Тест",
    )

    sheet = _sheet(data)
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0] == ("ID", "NAME", "AMOUNT", "WHEN")
    assert rows[1][0] == 1 and rows[1][1] == "a" and rows[1][2] == 12.5
    assert rows[1][3] == datetime(2026, 1, 5)
    assert rows[2] == (2, None, None, None)
    assert sheet.title == "Тест"


def test_excel_bytes_cut_note_is_the_first_row() -> None:
    data = ws_excel.ws_excel_bytes(("ID",), [(1,), (2,)], "Тест", cut=True)

    rows = list(_sheet(data).iter_rows(values_only=True))
    assert rows[0][0] == "Эхний 2 мөрийг харуулав"
    assert rows[1] == ("ID",)
    assert rows[2] == (1,)


def test_sheet_and_file_names_are_cleaned() -> None:
    assert ws_excel.sheet_title("") == ws_excel.DEFAULT_SHEET
    assert len(ws_excel.sheet_title("x" * 40)) == 31
    assert ws_excel.sheet_title("a/b:c*?[d]") == "abcd"
    assert ws_excel.file_stem('a/b:c*?"<>|d') == "abcd"
    assert ws_excel.file_stem("   ") == "workspace"
    assert ws_excel.ascii_stem("Тест", "workspace-7") == "workspace-7"


def test_tsv_text_one_line_per_row() -> None:
    text = ws_excel.ws_tsv_text(("A", "B"), [("x\ty", None), ("line\nbreak", 3)])

    assert text == "A\tB\nx y\t\nline break\t3"


def _record_limits(host: FakeHost, monkeypatch: pytest.MonkeyPatch) -> list:
    """Records the Limits every run of the fake host receives."""
    seen: list = []
    original = host.execute

    def execute(user, query, limits):
        seen.append(limits)
        return original(user, query, limits)

    monkeypatch.setattr(host, "execute", execute)
    return seen


def test_export_runs_carry_the_export_timeout(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    seen = _record_limits(host, monkeypatch)
    client.force_login(user)

    _get(client, tab, "ws_excel")

    assert any(limit.max_rows == EXPORT_MAX_ROWS and limit.timeout_s == EXPORT_TIMEOUT_S for limit in seen)


def test_no_usable_column_export_is_not_capped_at_one_page(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.columns = ("Full name",)  # no plain identifier: the tools cannot be used, the rows still export
    host.rows = [(f"n{i}",) for i in range(250)]
    seen = _record_limits(host, monkeypatch)
    client.force_login(user)

    response = _get(client, tab, "ws_excel")

    rows = list(_sheet(response.content).iter_rows(values_only=True))
    assert len(rows) == 251  # the header and all 250 rows, not one page of 100
    assert rows[0][0] == "Full name"
    assert any(limit.max_rows == EXPORT_MAX_ROWS and limit.timeout_s == EXPORT_TIMEOUT_S for limit in seen)


def test_no_usable_column_copy_and_print_cover_all_rows(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.columns = ("Full name",)
    host.rows = [(f"n{i}",) for i in range(150)]
    client.force_login(user)

    text = _get(client, tab, "ws_copy").content.decode()
    html = _get(client, tab, "ws_print").content.decode()

    assert text.count("\n") == 150  # header and 150 lines
    assert "n149" in html and "Нийт: 150" in html


def test_no_usable_column_cut_note_over_the_ceiling(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    monkeypatch.setattr(ws_views, "EXPORT_MAX_ROWS", 5)  # the views pass their own ceiling to run_base
    host.columns = ("Full name",)
    host.rows = [(f"n{i}",) for i in range(8)]
    client.force_login(user)

    rows = list(_sheet(_get(client, tab, "ws_excel").content).iter_rows(values_only=True))

    assert rows[0][0] == "Эхний 5 мөрийг харуулав"
    assert len(rows) == 7  # note, header, five rows


def test_page_is_ignored_by_copy_and_print(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    plain = _get(client, tab, "ws_copy").content
    paged = _get(client, tab, "ws_copy", "page=3").content
    html = _get(client, tab, "ws_print", "page=3").content.decode()

    assert paged == plain  # the same three rows, not the empty page 3
    assert "Aigerim" in html and "Нийт: 3" in html
    assert all("FIRST" not in text for text in host.sql)


def test_print_title_drops_control_characters(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = new_tab(user, "Тест\x01\nхүснэгт")
    add_version(tab, "Асуулт", BASE_SQL, "")
    client.force_login(user)

    response = _get(client, tab, "ws_print")

    html = response.content.decode()
    assert response.status_code == 200
    assert "Тестхүснэгт" in html
    assert "\x01" not in html


def test_excel_title_with_control_characters_is_clean(
    db: None, client: Client, role_user, gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = new_tab(user, "Тест\x01\nX")
    add_version(tab, "Асуулт", BASE_SQL, "")
    client.force_login(user)

    response = _get(client, tab, "ws_excel")

    disposition = response["Content-Disposition"]
    name = unquote(re.search(r"filename\*=UTF-8''(.+)$", disposition).group(1))
    assert "\n" not in name and "\x01" not in name
    assert load_workbook(io.BytesIO(response.content)).sheetnames[0] == "ТестX"


def test_sheet_title_removes_openpyxl_illegal_characters() -> None:
    assert ws_excel.sheet_title("Тест\x01\nX") == "ТестX"
    assert ws_excel.plain_title("a\x02b\tc") == "abc"


def test_formula_like_copy_cells_are_text() -> None:
    text = ws_excel.ws_tsv_text(("A",), [("=1+1",), (" =1",), ("@x",), ("-2",), ("+3",), ("ok",), ("a=b",)])

    assert text == "A\n'=1+1\n'=1\n'@x\n'-2\n'+3\nok\na=b"


def test_copy_endpoint_makes_formula_cells_text(db: None, client: Client, role_user, gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.rows = [(1, "=1+1"), (2, "@x")]
    client.force_login(user)

    text = _get(client, tab, "ws_copy").content.decode()

    assert text == "ID\tNAME\n1\t'=1+1\n2\t'@x"


@override_settings(TIME_ZONE="Asia/Ulaanbaatar", USE_TZ=True)
def test_excel_bytes_aware_datetime_is_written_in_the_local_zone() -> None:
    utc_noon = datetime(2026, 1, 5, 10, 30, tzinfo=timezone.utc)  # 18:30 in Ulaanbaatar (UTC+8)
    data = ws_excel.ws_excel_bytes(("T",), [(utc_noon,), (datetime(2026, 1, 5, 9, 0),)], "Тест")

    sheet = _sheet(data)
    assert sheet["A2"].value == datetime(2026, 1, 5, 18, 30)  # the screen's zone, not UTC
    assert sheet["A3"].value == datetime(2026, 1, 5, 9, 0)  # a naive value is written as it is


def test_excel_bytes_non_finite_numbers_are_text() -> None:
    data = ws_excel.ws_excel_bytes(
        ("N",),
        [(float("nan"),), (float("inf"),), (1.5,)],
        "Тест",
    )

    sheet = _sheet(data)
    assert sheet["A2"].data_type == "s" and sheet["A2"].value == "nan"
    assert sheet["A3"].data_type == "s" and sheet["A3"].value == "inf"
    assert sheet["A4"].value == 1.5


def test_copy_cells_that_start_with_hidden_whitespace_are_text() -> None:
    cases = {
        "\n=1+1": "'=1+1",
        " =1+1": "'=1+1",
        "\t=x": "'=x",
        "\u00a0=1": "'=1",
        "\x1c=1": "'=1",
        "\ufeff+5": "'+5",
        "ok": "ok",
        "a=b": "a=b",
        "  ": "",
    }
    for raw, expected in cases.items():
        assert ws_excel._tsv_cell(raw) == expected, repr(raw)
    assert ws_excel._tsv_cell("@x") == "'@x"
    assert ws_excel._tsv_cell(None) == ""


def _refuse_wrapped(host: FakeHost, monkeypatch: pytest.MonkeyPatch) -> None:
    """The wrapped run (the derived table named ws_base) is refused; the saved query's own run is accepted."""
    _refuse_when(host, monkeypatch, "ws_base")


@pytest.mark.parametrize("name", EXPORTS)
def test_empty_spec_refused_wrapper_falls_back_to_the_saved_rows(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    host.rows = [(i, f"n{i}") for i in range(1, 151)]  # more than one page: the fallback is not capped
    _refuse_wrapped(host, monkeypatch)
    client.force_login(user)

    response = _get(client, tab, name)

    assert response.status_code == 200
    if name == "ws_excel":
        rows = list(_sheet(response.content).iter_rows(values_only=True))
        assert len(rows) == 151  # the header and every saved row
        assert rows[-1] == (150, "n150")
    elif name == "ws_print":
        html = response.content.decode()
        assert "n150" in html and "Нийт: 150" in html
    else:
        assert response.content.decode().count("\n") == 150


@pytest.mark.parametrize("name", EXPORTS)
def test_empty_spec_fallback_keeps_the_cut_note(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    monkeypatch.setattr(ws_views, "EXPORT_MAX_ROWS", 5)
    host.rows = [(i, f"n{i}") for i in range(1, 9)]
    _refuse_wrapped(host, monkeypatch)
    client.force_login(user)

    response = _get(client, tab, name)

    assert response.status_code == 200
    if name == "ws_excel":
        rows = list(_sheet(response.content).iter_rows(values_only=True))
        assert rows[0][0] == "Эхний 5 мөрийг харуулав"
        assert len(rows) == 7  # note, header, five rows
    elif name == "ws_print":
        assert "Эхний 5 мөр." in response.content.decode()
    else:
        assert response["X-Cut"] == "1"


@pytest.mark.parametrize("name", EXPORTS)
def test_filter_with_refused_wrapper_is_still_a_refusal(
    db: None, client: Client, role_user, gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    _refuse_wrapped(host, monkeypatch)
    client.force_login(user)

    response = _get(client, tab, name, "f=ID|gt|1")

    assert response.status_code == 409
    assert response.content.decode() == REFUSED_LINE  # the saved rows are not shown behind a tool
    assert not response.content.startswith(b"PK")


@pytest.mark.parametrize("name", EXPORTS)
@pytest.mark.parametrize("scenario", ("off", "unavailable", "no_views"))
def test_blocked_run_with_empty_spec_gives_its_line_not_rows(
    db: None,
    client: Client,
    role_user,
    gate,
    host: FakeHost,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    scenario: str,
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)
    assert _get(client, tab, name).status_code == 200  # the gate is cached open from here on
    expected = {
        "off": ws_views.TABLE_REASONS["off"],
        "unavailable": ws_views.TABLE_REASONS["unavailable"],
        "no_views": ws_views.TABLE_REASONS["no_views"],
    }[scenario]
    if scenario == "off":
        monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    elif scenario == "unavailable":
        monkeypatch.setattr(sqlanswer, "_database_ready", lambda: False)
    else:
        host.views_empty = True

    response = _get(client, tab, name)

    assert response.status_code == 409
    assert response.content.decode() == expected  # the fixed line, never the saved rows
