import itertools
import json
from collections.abc import Callable

import httpx2
from mcp.types import CallToolResult
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, Result
from starlette.testclient import TestClient

from sqlmcp.server import build_app

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name")),
    rules=("Only active employees are listed.",),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))

TOKENS = {"t-alice": "alice", "t-bob": "bob"}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
_ids = itertools.count(1)
# TestClient defaults to Host "testserver", which the default allowlist rejects; the helpers send a local host.
DEFAULT_HOST = "localhost:8000"


class FakeHost:
    def __init__(self) -> None:
        self.users: list[object] = []

    def catalogue_for(self, user: object) -> Catalogue:
        self.users.append(user)
        return CATALOGUE

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        return Result(columns=("NAME",), rows=(("Aigerim",),), truncated=False)

    def cancel(self, user: object) -> None:
        pass


def authenticate(raw: str) -> object | None:
    return TOKENS.get(raw)


def _post(
    client: TestClient,
    method: str,
    params: dict[str, object],
    token: str | None,
    host: str = DEFAULT_HOST,
) -> httpx2.Response:
    headers = dict(HEADERS, Host=host)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params}
    return client.post("/mcp", json=body, headers=headers)


def rpc(
    client: TestClient,
    method: str,
    params: dict[str, object],
    token: str | None,
    host: str = DEFAULT_HOST,
) -> httpx2.Response:
    """Initialize the (stateless) session first, then send the real request."""
    init_params: dict[str, object] = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    }
    _post(client, "initialize", init_params, token, host)
    return _post(client, method, params, token, host)


def test_missing_bearer_is_401() -> None:
    app = build_app(FakeHost(), authenticate)
    with TestClient(app) as client:
        response = _post(client, "tools/list", {}, None)
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert "result" not in response.text


def test_unknown_token_is_401() -> None:
    app = build_app(FakeHost(), authenticate)
    with TestClient(app) as client:
        response = rpc(client, "tools/list", {}, "bad")
    assert response.status_code == 401
    assert "result" not in response.text


def test_tools_list() -> None:
    app = build_app(FakeHost(), authenticate)
    with TestClient(app) as client:
        response = rpc(client, "tools/list", {}, "t-alice")
    assert response.status_code == 200
    names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert names == ["describe_data", "run_query"]


def test_tools_call_runs_as_token_user() -> None:
    host = FakeHost()
    app = build_app(host, authenticate)
    with TestClient(app) as client:
        response = rpc(client, "tools/call", {"name": "describe_data", "arguments": {}}, "t-alice")
    assert response.status_code == 200
    assert host.users == ["alice"]
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["ok"] is True


def test_user_is_per_request() -> None:
    host = FakeHost()
    app = build_app(host, authenticate)
    with TestClient(app) as client:
        rpc(client, "tools/call", {"name": "describe_data", "arguments": {}}, "t-alice")
        rpc(client, "tools/call", {"name": "describe_data", "arguments": {}}, "t-bob")
    assert host.users == ["alice", "bob"]


def test_call_hook_wraps_call() -> None:
    host = FakeHost()
    seen: list[tuple[object, str]] = []

    def hook(
        principal: object, name: str, arguments: dict[str, object], run: Callable[[], CallToolResult]
    ) -> CallToolResult:
        seen.append((principal, name))
        return run()

    app = build_app(host, authenticate, call_hook=hook)
    with TestClient(app) as client:
        rpc(client, "tools/call", {"name": "describe_data", "arguments": {}}, "t-alice")
    assert seen == [("alice", "describe_data")]


def test_foreign_host_is_rejected() -> None:
    app = build_app(FakeHost(), authenticate)
    with TestClient(app) as client:
        response = _post(client, "tools/list", {}, "t-alice", host="evil.example")
    assert 400 <= response.status_code < 500
    assert "result" not in response.text


def test_allowed_host_passes() -> None:
    app = build_app(FakeHost(), authenticate, allowed_hosts=["mcp.example.com"])
    with TestClient(app) as client:
        response = rpc(client, "tools/list", {}, "t-alice", host="mcp.example.com")
    assert response.status_code == 200
    names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert names == ["describe_data", "run_query"]
