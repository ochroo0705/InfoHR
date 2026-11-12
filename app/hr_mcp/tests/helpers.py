"""Shared helpers for the hr_mcp app tests: a fake HR host and JSON-RPC posts through the test client."""

import itertools

import httpx2
from django.db import connection
from sqlcore.catalogue import Catalogue, Column, View
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, Result
from starlette.testclient import TestClient

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
# The default Host allow-list is 127.0.0.1:* and localhost:*; TestClient's own default host is rejected.
DEFAULT_HOST = "localhost:8000"
INIT_PARAMS: dict[str, object] = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "test", "version": "0"},
}
_ids = itertools.count(1)

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name")),
    rules=("Only active employees are listed.",),
)
CATALOGUE = Catalogue(views=(EMPLOYEES,))


class FakeHost:
    """Stands in for hr_sql.host.HrHost so no Firebird is needed."""

    def catalogue_for(self, user: object) -> Catalogue:
        return CATALOGUE

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:
        return Result(columns=("NAME",), rows=(("Aigerim",),), truncated=False)

    def cancel(self, user: object) -> None:
        pass


def commit_for_other_threads() -> None:
    """Make this thread's writes visible to the MCP server thread, or reads of its writes.

    Firebird commits a pending autocommit write only on the next query or on close; the server runs in another thread.
    Closing the connection commits; Django reconnects on the next query.
    """
    connection.close()


def _post(client: TestClient, method: str, params: dict[str, object], token: str | None) -> httpx2.Response:
    headers = dict(HEADERS, Host=DEFAULT_HOST)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params}
    return client.post("/mcp", json=body, headers=headers)


def _rpc(client: TestClient, method: str, params: dict[str, object], token: str | None) -> httpx2.Response:
    """Initialize the stateless session first, then send the real request."""
    _post(client, "initialize", INIT_PARAMS, token)
    return _post(client, method, params, token)
