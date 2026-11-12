import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, Result
from sqlcore.tools import TOOLS, describe_text, handle

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    description_mn="Харах эрхтэй ажилтнууд",
    columns=(
        Column("ID", "employee id", ("staff",), "Ажилтны дугаар"),
        Column("NAME", "full name"),
    ),
    rules=("Only active employees are listed.",),
)
CHILDREN = View(
    name="GOV_CHILDREN",
    description="Children of employees",
    columns=(Column("EMPLOYEE_ID", "employee id"),),
)
SALARY = View(
    name="GOV_SALARY",
    description="Salary of employees you may see",
    columns=(
        Column("AMOUNT", "monthly amount"),
        Column("PAID_ON", "pay date"),
        Column("PAID_AT", "pay time"),
        Column("RAW_DATA", "raw data"),
        Column("NOTE", "note"),
        Column("DAYS", "days"),
    ),
)
ALICE = Catalogue(views=(EMPLOYEES, CHILDREN, SALARY))
BOB = Catalogue(views=(EMPLOYEES,))

NAME_SQL = "SELECT e.NAME FROM GOV_EMPLOYEES e"


class FakeHost:
    """A host that records every call. Rows are returned up to the cap plus one, as the Protocol says."""

    def __init__(
        self,
        catalogues: dict[object, Catalogue],
        columns: tuple[str, ...] = ("NAME",),
        rows: list[tuple[object, ...]] | None = None,
        truncated: bool = False,
    ) -> None:
        self.catalogues = catalogues
        self.columns = columns
        self.rows: list[tuple[object, ...]] = rows if rows is not None else [("Aigerim",), ("Bat",)]
        self.truncated = truncated
        self.execute_calls: list[CheckedQuery] = []
        self.cancel_calls: list[object] = []

    def catalogue_for(self, user: object) -> Catalogue:
        return self.catalogues[user]

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.execute_calls.append(query)
        returned = tuple(self.rows[: limits.max_rows + 1])
        return Result(columns=self.columns, rows=returned, truncated=self.truncated)

    def cancel(self, user: object) -> None:
        self.cancel_calls.append(user)


def _warnings(outcome: dict[str, object]) -> list[str]:
    warnings: object = outcome["warnings"]
    assert isinstance(warnings, list)
    return [str(item) for item in warnings]


def test_tools_define_describe_data_and_run_query() -> None:
    by_name = {tool["name"]: tool for tool in TOOLS}

    assert set(by_name) == {"describe_data", "run_query"}
    for tool in TOOLS:
        assert isinstance(tool["description"], str) and tool["description"]
        parameters: Any = tool["parameters"]
        assert parameters["type"] == "object"
    run_query: Any = by_name["run_query"]["parameters"]
    assert run_query["required"] == ["sql"]
    assert run_query["properties"]["sql"]["type"] == "string"
    assert run_query["properties"]["sql"]["maxLength"] == 4000


def test_describe_lists_only_the_users_views() -> None:
    host = FakeHost({"alice": ALICE, "bob": BOB})

    alice = handle(host, "alice", "describe_data", {})
    bob = handle(host, "bob", "describe_data", {})

    alice_text = str(alice["text"])
    bob_text = str(bob["text"])
    assert alice["ok"] is True
    assert "GOV_CHILDREN" in alice_text
    assert "GOV_EMPLOYEES" in alice_text
    assert bob["ok"] is True
    assert "GOV_EMPLOYEES" in bob_text
    assert "GOV_CHILDREN" not in bob_text


def test_describe_text_includes_rules_and_synonyms() -> None:
    text = describe_text(Catalogue(views=(EMPLOYEES,)))

    assert "Employees you may see" in text
    assert "Харах эрхтэй ажилтнууд" in text
    assert "Only active employees are listed." in text
    assert "full name" in text
    assert "staff" in text
    assert "Ажилтны дугаар" in text


def test_run_query_success_is_json_serialisable() -> None:
    rows: list[tuple[object, ...]] = [
        (Decimal("1234.50"), date(2026, 1, 15), datetime(2026, 1, 15, 9, 30), b"\x01\x02", None, 7),
    ]
    host = FakeHost({"alice": ALICE}, columns=SALARY_COLUMNS, rows=rows)
    sql = (
        "SELECT s.AMOUNT, s.PAID_ON, s.PAID_AT, s.RAW_DATA, s.NOTE, s.DAYS FROM GOV_SALARY s"
    )

    outcome = handle(host, "alice", "run_query", {"sql": sql})

    json.dumps(outcome)
    assert outcome["ok"] is True
    assert outcome["columns"] == list(SALARY_COLUMNS)
    assert outcome["rows"] == [["1234.50", "2026-01-15", "2026-01-15T09:30:00", "0102", None, 7]]
    assert outcome["row_count"] == 1
    assert outcome["sql"] == host.execute_calls[0].sql
    assert "GOV_SALARY" in str(outcome["explanation"])


SALARY_COLUMNS = ("AMOUNT", "PAID_ON", "PAID_AT", "RAW_DATA", "NOTE", "DAYS")


def test_run_query_refusal_has_reason_and_no_rows() -> None:
    host = FakeHost({"alice": ALICE})

    outcome = handle(host, "alice", "run_query", {"sql": "DELETE FROM GOV_EMPLOYEES"})

    assert outcome["ok"] is False
    assert outcome["reason"]
    assert "rows" not in outcome
    assert host.execute_calls == []


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT e.NAME FROM IHR_EMPLOYEE e",
        "SELECT 1 FROM GOV_EMPLOYEES e; DELETE FROM GOV_EMPLOYEES",
    ],
)
def test_run_query_never_calls_the_host_when_the_check_fails(sql: str) -> None:
    host = FakeHost({"alice": ALICE})

    outcome = handle(host, "alice", "run_query", {"sql": sql})

    assert outcome["ok"] is False
    assert host.execute_calls == []


def test_run_query_uses_the_askers_catalogue() -> None:
    host = FakeHost({"alice": ALICE, "bob": BOB})

    outcome = handle(host, "bob", "run_query", {"sql": "SELECT c.EMPLOYEE_ID FROM GOV_CHILDREN c"})

    assert outcome["ok"] is False
    assert host.execute_calls == []


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("run_query", {}),
        ("run_query", {"sql": None}),
        ("run_query", {"sql": ["SELECT"]}),
        ("run_query", {"sql": "x" * 4001}),
        ("drop_everything", {}),
    ],
)
def test_unknown_tool_and_bad_arguments_do_not_raise(name: str, arguments: dict[str, object]) -> None:
    host = FakeHost({"alice": ALICE})

    outcome = handle(host, "alice", name, arguments)

    assert outcome["ok"] is False
    assert isinstance(outcome["reason"], str) and outcome["reason"]
    assert host.execute_calls == []


def test_run_query_includes_truncated_warning() -> None:
    host = FakeHost({"alice": ALICE}, truncated=True)

    outcome = handle(host, "alice", "run_query", {"sql": NAME_SQL}, Limits(max_rows=1, timeout_s=5.0))

    assert outcome["ok"] is True
    assert outcome["row_count"] == 1
    assert "truncated" in _warnings(outcome)


def test_run_query_warns_that_a_join_count_counts_rows() -> None:
    host = FakeHost({"alice": ALICE}, columns=("N",), rows=[(3,)])
    sql = "SELECT COUNT(*) FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.EMPLOYEE_ID = e.ID"

    outcome = handle(host, "alice", "run_query", {"sql": sql})

    assert outcome["ok"] is True
    assert "join_counts_rows" in _warnings(outcome)


def test_money_is_rounded_in_the_returned_rows() -> None:
    rows: list[tuple[object, ...]] = [
        (Decimal("0.30000000000000004"), Decimal("1234567.89"), "text", 3, None, 2),
    ]
    host = FakeHost({"alice": ALICE}, columns=SALARY_COLUMNS, rows=rows)
    sql = "SELECT s.AMOUNT, s.PAID_ON, s.PAID_AT, s.RAW_DATA, s.NOTE, s.DAYS FROM GOV_SALARY s"

    outcome = handle(host, "alice", "run_query", {"sql": sql})

    assert outcome["ok"] is True
    assert outcome["rows"] == [["0.30", "1234567.89", "text", 3, None, 2]]
    assert "money_rounded" in _warnings(outcome)
