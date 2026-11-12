"""Tests for the workspace run (Task 4): each call runs one checked query through run_question, with a fake host.

The gate settings are patched on assistant.sqlanswer, the same seams sqlanswer uses. No Firebird is needed.
"""

from decimal import Decimal
from typing import Any

import pytest
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery, check_sql
from sqlcore.limits import Limits, Result

from assistant import sqlanswer, ws_run
from assistant.sqlanswer import NO_VIEWS_REASON, OFF_REASON, UNAVAILABLE_REASON
from assistant.ws_limits import EXPORT_MAX_ROWS, MAX_PAGE, PAGE_SIZE
from assistant.ws_sql import Filter, Spec

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(
        Column("NAME", "full name"),
        Column("DEPARTMENT", "department"),
        Column("LATE_DAYS", "days late"),
    ),
)
CHILDREN = View(
    name="GOV_CHILDREN",
    description="Children of employees",
    columns=(Column("EMPLOYEE_ID", "employee id"),),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))
NO_EMPLOYEES = Catalogue(views=(CHILDREN,))
BASE = "SELECT NAME, DEPARTMENT, LATE_DAYS FROM GOV_EMPLOYEES"
COLS = ("NAME", "DEPARTMENT", "LATE_DAYS")
ASKER: Any = object()  # the fake host ignores the user


class FakeHost:
    """Records every execute. Returns the fixed columns and rows, up to the cap plus one, as the Protocol says."""

    def __init__(self, catalogue: Catalogue, columns: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
        self.catalogue = catalogue
        self.columns = columns
        self.rows = rows
        self.execute_calls: list[tuple[object, CheckedQuery, Limits]] = []

    def catalogue_for(self, user: object) -> Catalogue:
        return self.catalogue

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.execute_calls.append((user, query, limits))
        return Result(columns=self.columns, rows=tuple(self.rows[: limits.max_rows + 1]), truncated=False)

    def cancel(self, user: object) -> None:
        pass


@pytest.fixture(autouse=True)
def _gate_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)


def _host(rows: list[tuple[object, ...]] | None = None, catalogue: Catalogue = CATALOGUE) -> FakeHost:
    return FakeHost(catalogue, COLS, rows if rows is not None else [("Aigerim", "IT", 3), ("Bat", "HR", 0)])


def test_run_page_returns_rows() -> None:
    host = _host()

    result = ws_run.run_page(ASKER, BASE, COLS, Spec(), 0, host=host)

    assert result.status == "ok"
    assert result.reason == ""
    assert result.columns == COLS
    assert result.rows == (("Aigerim", "IT", 3), ("Bat", "HR", 0))
    assert len(host.execute_calls) == 1
    _user, query, limits = host.execute_calls[0]
    assert limits.max_rows == PAGE_SIZE
    assert "FROM (" in query.sql  # the saved query is wrapped as a derived table
    assert "SELECT NAME, DEPARTMENT, LATE_DAYS FROM GOV_EMPLOYEES" in query.sql
    assert "FIRST 100" in query.sql  # the checker renders the page window in Firebird dialect


def test_run_page_uses_group_sql_when_grouping() -> None:
    host = FakeHost(CATALOGUE, ("DEPARTMENT", "N"), [("IT", 2)])

    result = ws_run.run_page(ASKER, BASE, COLS, Spec(group_by="DEPARTMENT"), 0, host=host)

    assert result.status == "ok"
    assert result.columns == ("DEPARTMENT", "N")
    assert "GROUP BY DEPARTMENT" in host.execute_calls[0][1].sql


def test_run_count_reads_n() -> None:
    host = FakeHost(CATALOGUE, ("N",), [(7,)])

    count = ws_run.run_count(ASKER, BASE, COLS, Spec(filters=(Filter("LATE_DAYS", "gt", "1"),)), host=host)

    assert count == 7
    assert len(host.execute_calls) == 1
    assert host.execute_calls[0][2].max_rows == 1
    sent = host.execute_calls[0][1].sql
    assert "COUNT(*)" in sent
    assert "SELECT NAME, DEPARTMENT, LATE_DAYS FROM GOV_EMPLOYEES" in sent


def test_run_count_with_group_by_counts_groups() -> None:
    host = FakeHost(CATALOGUE, ("N",), [(2,)])

    count = ws_run.run_count(ASKER, BASE, COLS, Spec(group_by="DEPARTMENT"), host=host)

    assert count == 2
    sent = host.execute_calls[0][1].sql
    assert "GROUP BY DEPARTMENT" in sent
    assert "ws_groups" in sent
    assert "COUNT(*)" in sent


def test_run_count_is_none_when_run_is_not_ok() -> None:
    host = FakeHost(NO_EMPLOYEES, ("N",), [(7,)])

    assert ws_run.run_count(ASKER, BASE, COLS, Spec(), host=host) is None
    assert host.execute_calls == []


def test_refusal_has_reason_and_no_rows() -> None:
    host = _host(catalogue=NO_EMPLOYEES)

    result = ws_run.run_page(ASKER, BASE, COLS, Spec(), 0, host=host)

    assert result.status == "refused"
    assert result.reason
    assert result.rows == ()
    assert result.columns == ()


def test_export_cut_flag() -> None:
    rows = [(f"N{i}", "D", 0) for i in range(EXPORT_MAX_ROWS + 1)]
    host = _host(rows=rows)

    result, cut = ws_run.run_export(ASKER, BASE, COLS, Spec(), host=host)

    assert cut is True
    assert result.status == "ok"
    assert len(result.rows) == EXPORT_MAX_ROWS
    assert host.execute_calls[0][2].max_rows == EXPORT_MAX_ROWS
    sent = host.execute_calls[0][1].sql
    assert " ROWS " not in sent
    assert "FIRST" not in sent


def test_export_exactly_cap_is_not_cut() -> None:
    rows = [(f"N{i}", "D", 0) for i in range(EXPORT_MAX_ROWS)]
    host = _host(rows=rows)

    result, cut = ws_run.run_export(ASKER, BASE, COLS, Spec(), host=host)

    assert cut is False
    assert len(result.rows) == EXPORT_MAX_ROWS


def test_setting_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    host = _host()

    result = ws_run.run_page(ASKER, BASE, COLS, Spec(), 0, host=host)

    assert result.status == "off"
    assert result.reason == OFF_REASON
    assert host.execute_calls == []


def test_database_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: False)
    host = _host()

    result = ws_run.run_page(ASKER, BASE, COLS, Spec(), 0, host=host)

    assert result.status == "unavailable"
    assert result.reason == UNAVAILABLE_REASON
    assert host.execute_calls == []


def test_empty_catalogue_is_unavailable() -> None:
    host = _host(catalogue=Catalogue(views=()))

    result, cut = ws_run.run_export(ASKER, BASE, COLS, Spec(), host=host)

    assert result.status == "unavailable"
    assert result.reason == NO_VIEWS_REASON
    assert cut is False
    assert host.execute_calls == []


def test_unknown_column_is_refused_without_running() -> None:
    host = _host()

    result = ws_run.run_page(ASKER, BASE, COLS, Spec(filters=(Filter("NOPE", "eq", "x"),)), 0, host=host)

    assert result.status == "refused"
    assert "NOPE" in result.reason
    assert host.execute_calls == []


def test_page_above_cap_is_refused() -> None:
    host = _host()

    result = ws_run.run_page(ASKER, BASE, COLS, Spec(), MAX_PAGE + 1, host=host)

    assert result.status == "refused"
    assert result.rows == ()
    assert host.execute_calls == []


def test_negative_page_is_refused() -> None:
    host = _host()

    result = ws_run.run_page(ASKER, BASE, COLS, Spec(), -1, host=host)

    assert result.status == "refused"
    assert host.execute_calls == []


def test_base_columns_reads_names_with_one_row() -> None:
    host = _host()

    result = ws_run.base_columns(ASKER, BASE, host=host)

    assert result.status == "ok"
    assert result.columns == COLS
    assert len(host.execute_calls) == 1
    assert host.execute_calls[0][2].max_rows == 1


def test_money_is_rounded_like_the_card() -> None:
    host = FakeHost(CATALOGUE, ("AMOUNT",), [(Decimal("12.345"),)])

    result = ws_run.base_columns(ASKER, BASE, host=host)

    assert result.rows == ((Decimal("12.35"),),)


def test_run_base_returns_rows_up_to_a_page_and_says_when_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [("a", "b", i) for i in range(PAGE_SIZE + 1)]
    host = _host(rows)

    result = ws_run.run_base(ASKER, BASE, host=host)

    assert result.status == "ok"
    assert len(result.rows) == PAGE_SIZE
    assert result.cut is True
    assert host.execute_calls[0][2].max_rows == PAGE_SIZE
    assert host.execute_calls[0][1].sql == check_sql(BASE, CATALOGUE).sql  # the saved query, as checked, no wrapper


def test_run_base_not_cut_with_few_rows() -> None:
    result = ws_run.run_base(ASKER, BASE, host=_host([("a", "b", 1)]))

    assert result.status == "ok"
    assert result.cut is False


def test_run_base_is_off_when_the_switch_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    host = _host()

    result = ws_run.run_base(ASKER, BASE, host=host)

    assert result.status == "off"
    assert result.reason == OFF_REASON
    assert host.execute_calls == []


def test_run_base_refuses_an_unchecked_query_without_running() -> None:
    host = _host()

    result = ws_run.run_base(ASKER, "DELETE FROM GOV_EMPLOYEES", host=host)

    assert result.status == "refused"
    assert result.rows == ()
    assert host.execute_calls == []
