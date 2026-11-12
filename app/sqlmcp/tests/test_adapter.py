import json

from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, Result

from sqlmcp.adapter import call_tool, mcp_tools

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name")),
    rules=("Only active employees are listed.",),
)
ALICE = Catalogue(views=(EMPLOYEES,))


class FakeHost:
    def __init__(self, catalogue: Catalogue | None = None, fail_catalogue: bool = False) -> None:
        self.catalogue = catalogue if catalogue is not None else ALICE
        self.fail_catalogue = fail_catalogue
        self.execute_calls: list[CheckedQuery] = []

    def catalogue_for(self, user: object) -> Catalogue:
        if self.fail_catalogue:
            raise RuntimeError("database is down")
        return self.catalogue

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        self.execute_calls.append(query)
        return Result(columns=("NAME",), rows=(("Aigerim",),), truncated=False)

    def cancel(self, user: object) -> None:
        pass


def _payload(result: object) -> dict[str, object]:
    content = result.content  # type: ignore[attr-defined]
    assert len(content) == 1
    loaded = json.loads(content[0].text)
    assert isinstance(loaded, dict)
    return loaded


def test_tools_match_sqlcore() -> None:
    tools = mcp_tools()

    assert [t.name for t in tools] == ["describe_data", "run_query"]
    assert tools[1].input_schema["required"] == ["sql"]


def test_describe_returns_text() -> None:
    result = call_tool(FakeHost(), "alice", "describe_data", {})

    assert result.is_error is False
    payload = _payload(result)
    assert payload["ok"] is True
    assert "GOV_EMPLOYEES" in json.dumps(payload)


def test_refusal_is_error_result() -> None:
    host = FakeHost()

    result = call_tool(host, "alice", "run_query", {"sql": "DELETE FROM X"})

    assert result.is_error is True
    assert _payload(result)["ok"] is False
    assert host.execute_calls == []


def test_unknown_tool_is_error_result() -> None:
    result = call_tool(FakeHost(), "alice", "drop_all", {})

    assert result.is_error is True
    assert _payload(result)["ok"] is False


def test_host_exception_becomes_error_result() -> None:
    result = call_tool(FakeHost(fail_catalogue=True), "alice", "describe_data", {})

    assert result.is_error is True
    assert _payload(result) == {"ok": False, "reason": "The query could not be run."}


def test_none_arguments() -> None:
    result = call_tool(FakeHost(), "alice", "describe_data", None)

    assert result.is_error is False
