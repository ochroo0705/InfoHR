"""Snapshot of what the HR MCP server tells an AI client today.

Every assertion goes through the real HR app (hr_mcp.app.make_app) with a valid token. Only the
Firebird host is swapped for the test FakeHost, as in test_app.py. The expected strings are the
contract a client sees: the two tool descriptions, the run_query input schema and the server
instructions. They were copied from app/sqlcore/tools.py and sqlmcp/server.py as they stood in
Phase 1, task 1.0. They must stay unchanged through tasks 1.3 and 1.4.
"""

from typing import Any

import pytest
from accounts.models import User
from starlette.testclient import TestClient

from hr_mcp import app as hr_app
from hr_mcp.tests.helpers import INIT_PARAMS, FakeHost, _post, commit_for_other_threads
from hr_mcp.tokens import issue_token

PASSWORD = "x-long-pass-123"  # noqa: S105

EXPECTED_DESCRIBE_DESCRIPTION = (
    "List the data you may query: each view with its description, its rules and its columns. "
    "Call this before writing a query."
)
EXPECTED_RUN_DESCRIPTION = (
    "Run one read-only SELECT over the views that describe_data lists. Only those GOV_ views may be used. "
    "List the columns you need instead of SELECT *. Join views on their ID columns. "
    "For a head count of working employees use WORKING = 1 where the view has that column. "
    "Count people with COUNT(DISTINCT ...) when a view has one row per child or per record."
)
EXPECTED_INSTRUCTIONS = "MACS Human Capital governed SQL, contract 1.0. Call describe_data before run_query."


@pytest.fixture
def user() -> User:
    return User.objects.create_user("mcp_contract_user", password=PASSWORD)


@pytest.fixture
def fake_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hr_app, "HrHost", FakeHost)


def _tools_list(client: TestClient, raw: str) -> dict[str, Any]:
    response = _post(client, "tools/list", {}, raw)
    assert response.status_code == 200
    return response.json()["result"]


@pytest.mark.django_db(transaction=True)
def test_tools_list_descriptions_are_unchanged(user: User, fake_host: None) -> None:
    _row, raw = issue_token(user, "Contract client")
    commit_for_other_threads()
    with TestClient(hr_app.make_app()) as client:
        _post(client, "initialize", INIT_PARAMS, raw)
        tools = {tool["name"]: tool for tool in _tools_list(client, raw)["tools"]}

    assert set(tools) == {"describe_data", "run_query"}
    assert tools["describe_data"]["description"] == EXPECTED_DESCRIBE_DESCRIPTION
    assert tools["run_query"]["description"] == EXPECTED_RUN_DESCRIPTION


@pytest.mark.django_db(transaction=True)
def test_run_query_input_schema_is_unchanged(user: User, fake_host: None) -> None:
    _row, raw = issue_token(user, "Contract client")
    commit_for_other_threads()
    with TestClient(hr_app.make_app()) as client:
        _post(client, "initialize", INIT_PARAMS, raw)
        tools = {tool["name"]: tool for tool in _tools_list(client, raw)["tools"]}

    schema = tools["run_query"]["inputSchema"]
    assert schema["properties"]["sql"]["maxLength"] == 4000
    assert schema["required"] == ["sql"]


@pytest.mark.django_db(transaction=True)
def test_initialize_instructions_are_unchanged(user: User, fake_host: None) -> None:
    _row, raw = issue_token(user, "Contract client")
    commit_for_other_threads()
    with TestClient(hr_app.make_app()) as client:
        response = _post(client, "initialize", INIT_PARAMS, raw)

    assert response.status_code == 200
    assert response.json()["result"]["instructions"] == EXPECTED_INSTRUCTIONS

