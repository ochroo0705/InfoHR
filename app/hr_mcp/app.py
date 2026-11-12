"""The HR MCP app: governed SQL served to HR users with per-user bearer tokens.

Glue only. The tool logic lives in sqlcore, the HTTP and MCP plumbing in sqlmcp, and the
token checks in hr_mcp.tokens. Each worker thread closes stale database connections before and
after every token check and every tool call.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.db import close_old_connections
from hr_sql.host import HrHost
from mcp.types import CallToolResult
from sqlmcp.server import CallHook, build_app
from starlette.applications import Starlette

from hr_mcp.calls import log_and_limit
from hr_mcp.models import McpToken
from hr_mcp.text import HR_INSTRUCTIONS, HR_RUN_QUERY_DESCRIPTION
from hr_mcp.tokens import find_token

__all__ = ["make_app"]


def _authenticate(raw: str) -> McpToken | None:
    close_old_connections()
    try:
        return find_token(raw)
    finally:
        close_old_connections()


def make_app(call_hook: CallHook | None = None) -> Starlette:
    """The MCP app for the HR host.

    call_hook, when given, wraps every call. By default each call is logged and rate-limited (hr_mcp.calls).
    """

    def hook(
        principal: object, name: str, arguments: dict[str, object], run: Callable[[], CallToolResult]
    ) -> CallToolResult:
        # The whole call path (rate-limit count, the call, McpCall write) runs between two closes,
        # so the worker thread holds no database connection after the call.
        close_old_connections()
        try:
            if call_hook is not None:
                return call_hook(principal, name, arguments, run)
            if not isinstance(principal, McpToken):
                raise RuntimeError("the default call log needs an McpToken principal")
            return log_and_limit(principal, name, arguments, run)
        finally:
            close_old_connections()

    return build_app(
        HrHost(),
        _authenticate,
        call_hook=hook,
        allowed_hosts=settings.MCP_ALLOWED_HOSTS,
        instructions=HR_INSTRUCTIONS,
        run_query_description=HR_RUN_QUERY_DESCRIPTION,
    )
