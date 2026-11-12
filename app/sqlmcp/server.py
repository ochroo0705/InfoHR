"""Streamable HTTP server for the governed SQL tools, with bearer-token auth.

The tool logic lives in sqlcore; this module only moves requests between HTTP, the MCP SDK and
adapter.call_tool. It must not import Django or HR apps.

Per request, the authenticated principal travels in the ASGI scope (request.state.principal),
never in a module global.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

import anyio
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult
from sqlcore.limits import Limits
from sqlcore.runner import DEFAULT_LIMITS, Host
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from sqlmcp import SERVER_NAME, SQL_MCP_VERSION
from sqlmcp.adapter import call_tool, mcp_tools

__all__ = ["Authenticate", "CallHook", "build_app"]

Authenticate = Callable[[str], object | None]
"""Raw bearer token in, a principal (or None) out. Synchronous; may touch the database."""

CallHook = Callable[[object, str, dict[str, object], Callable[[], CallToolResult]], CallToolResult]
"""Wraps one call: (principal, tool name, arguments, run). The default just calls run()."""

MCP_PATH = "/mcp"
DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = ("127.0.0.1:*", "localhost:*")
"""Host header values accepted by default (DNS-rebinding protection)."""
_PRINCIPAL_KEY = "principal"


def _bearer_token(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            scheme, _, token = str(value.decode("latin-1")).partition(" ")
            stripped = token.strip()
            if scheme.lower() == "bearer" and stripped:
                return stripped
            return None
    return None


class BearerAuth:
    """Pure ASGI middleware: 401 unless the token authenticates; the principal goes into scope state."""

    def __init__(self, app: ASGIApp, authenticate: Authenticate) -> None:
        self.app = app
        self.authenticate = authenticate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _bearer_token(scope)
        principal = None
        if token is not None:
            principal = await anyio.to_thread.run_sync(self.authenticate, token)
        if principal is None:
            response = JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
            await response(scope, receive, send)
            return
        scope["state"] = {**scope.get("state", {}), _PRINCIPAL_KEY: principal}
        await self.app(scope, receive, send)


class _McpEndpoint:
    """ASGI endpoint wrapper around the session manager (a bound method would be treated as a request handler)."""

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


def _principal(ctx: ServerRequestContext[Any]) -> object:
    state = getattr(ctx.request, "state", None)
    if state is None or not hasattr(state, _PRINCIPAL_KEY):
        raise RuntimeError("no authenticated principal on this request")
    return getattr(state, _PRINCIPAL_KEY)


def build_app(
    host: Host,
    authenticate: Authenticate,
    *,
    limits: Limits = DEFAULT_LIMITS,
    call_hook: CallHook | None = None,
    allowed_hosts: Sequence[str] = DEFAULT_ALLOWED_HOSTS,
) -> Starlette:
    """Starlette app serving MCP Streamable HTTP at /mcp (stateless, JSON responses) behind bearer auth.

    Host and Origin headers are checked against allowed_hosts (DNS-rebinding protection); a Host
    that is not allowed gets HTTP 421 from the SDK. Origin values are derived as http:// and https://
    versions of each host.

    Run this app as the top-level ASGI app (for example uvicorn.run(build_app(...))). Do not mount it
    inside another app: the session manager starts in this app's own lifespan, and a mounted copy
    would fail with 'Task group is not initialized'.
    """

    async def on_list_tools(ctx: ServerRequestContext[Any], params: Any) -> ListToolsResult:
        return ListToolsResult(tools=mcp_tools())

    async def on_call_tool(ctx: ServerRequestContext[Any], params: CallToolRequestParams) -> CallToolResult:
        principal = _principal(ctx)
        user = getattr(principal, "user", principal)
        name = params.name
        arguments = dict(params.arguments or {})

        def run() -> CallToolResult:
            return call_tool(host, user, name, arguments, limits)

        def invoke() -> CallToolResult:
            if call_hook is None:
                return run()
            return call_hook(principal, name, arguments, run)

        return await anyio.to_thread.run_sync(invoke)

    server: Server[Any] = Server(
        SERVER_NAME,
        version=SQL_MCP_VERSION,
        instructions=(
            f"MACS Human Capital governed SQL, contract {SQL_MCP_VERSION}. Call describe_data before run_query."
        ),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    hosts = list(allowed_hosts)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"{scheme}://{host}" for host in hosts for scheme in ("http", "https")],
    )
    session_manager = StreamableHTTPSessionManager(
        app=server, json_response=True, stateless=True, security_settings=security
    )

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    return Starlette(
        routes=[Route(MCP_PATH, endpoint=_McpEndpoint(session_manager))],
        middleware=[Middleware(BearerAuth, authenticate=authenticate)],
        lifespan=lifespan,
    )
