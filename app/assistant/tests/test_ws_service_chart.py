"""Tests for the chart saved with each workspace version (Task 4): refine_tab keeps, replaces or removes the chart.

The provider is a fake that returns the replies it is given, in order. The host is a fake that returns fixed result
columns. The gate is patched on assistant.sqlanswer, the same seams test_ws_refine.py uses. The DB is used for tabs.
"""

from datetime import date
from typing import Any

import pytest
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, Result

from assistant import sqlanswer, ws_service
from assistant.models import WorkspaceTab
from assistant.ws_chart import ChartSpec, chart_spec_from_json, chart_spec_to_json

DAY = date(2026, 11, 16)
EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name"), Column("DEPT", "department")),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))
SQL = "SELECT ID, NAME FROM GOV_EMPLOYEES"
NEW_SQL = "SELECT ID, NAME, DEPT FROM GOV_EMPLOYEES"
GROUPED_SQL = "SELECT DEPT, COUNT(*) AS N FROM GOV_EMPLOYEES GROUP BY DEPT"
COLUMNS = ("ID", "NAME")
GROUPED_COLUMNS = ("DEPT", "N")
DEPT_BAR = chart_spec_to_json(ChartSpec("bar", "DEPT", ("N",)))
NAME_BAR = chart_spec_to_json(ChartSpec("bar", "NAME", ("ID",)))


class FakeProvider:
    """Returns the queued replies in order. An exception in the queue is raised instead. Records every call."""

    name = "fake"
    model = "fake-model"

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, schema: Any = None) -> Any:
        self.calls.append((system, user))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class FakeHost:
    """A host with one catalogue and fixed result columns. execute returns one row, as the Protocol says."""

    def __init__(self, columns: tuple[str, ...] = COLUMNS) -> None:
        self.columns = columns

    def catalogue_for(self, user: object) -> Catalogue:
        return CATALOGUE

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        return Result(columns=self.columns, rows=(tuple("1" for _ in self.columns),), truncated=False)

    def cancel(self, user: object) -> None:
        pass


@pytest.fixture(autouse=True)
def _gate_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)


def _tab_with_version(user: Any, sql: str = SQL, chart: str = "") -> WorkspaceTab:
    tab = ws_service.new_tab(user, title="Ажилтнууд")
    ws_service.add_version(tab, "Ажилтнууд", sql, chart=chart)
    return tab


def test_first_build_saves_chart(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    reply = {"sql": GROUPED_SQL, "chart": {"type": "bar", "x": "DEPT", "y": ["N"]}}

    result = ws_service.refine_tab(user, tab, "Хэлтсээр", DAY, FakeProvider(reply), host=FakeHost(GROUPED_COLUMNS))

    assert result.status == "ok"
    spec = chart_spec_from_json(tab.current().chart, GROUPED_COLUMNS)
    assert spec is not None
    assert spec.type == "bar"
    assert spec.x == "DEPT"
    assert spec.y == ("N",)


def test_refine_without_chart_keeps_current(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user, chart=NAME_BAR)

    result = ws_service.refine_tab(user, tab, "Хэлтсийг нэм", DAY, FakeProvider({"sql": NEW_SQL}), host=FakeHost())

    assert result.status == "ok"
    assert tab.current().pk == result.version.pk
    assert tab.current().chart == NAME_BAR


def test_refine_none_removes_chart(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user, chart=NAME_BAR)
    reply = {"sql": NEW_SQL, "chart": {"type": "none"}}

    result = ws_service.refine_tab(user, tab, "Хүснэгт зөвхөн", DAY, FakeProvider(reply), host=FakeHost())

    assert result.status == "ok"
    assert tab.current().chart == ""


def test_refine_dropping_column_drops_chart(db: None, role_user) -> None:
    user = role_user("staff")
    tab = _tab_with_version(user, chart=DEPT_BAR)
    # The new result has no DEPT column, so the kept chart (x="DEPT") no longer fits.
    result = ws_service.refine_tab(user, tab, "Нэрээр нь харуул", DAY, FakeProvider({"sql": SQL}), host=FakeHost())

    assert result.status == "ok"
    assert tab.current().chart == ""


def test_invalid_chart_keeps_table(db: None, role_user) -> None:
    user = role_user("staff")
    tab = ws_service.new_tab(user)
    reply = {"sql": GROUPED_SQL, "chart": {"type": "radar", "x": "DEPT", "y": ["N"]}}

    result = ws_service.refine_tab(user, tab, "Радар", DAY, FakeProvider(reply), host=FakeHost(GROUPED_COLUMNS))

    assert result.status == "ok"
    assert tab.current().chart == ""
    assert tab.current().sql != ""
