"""Map the governed SQL tools (sqlcore.tools) onto MCP tool definitions and results.

The sqlcore dispatcher returns plain dicts. This module wraps them in the MCP types from the
installed SDK (mcp.types, re-exported from mcp_types). No Django and no HR imports.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from mcp.types import CallToolResult, TextContent, Tool
from sqlcore.limits import Limits
from sqlcore.runner import DEFAULT_LIMITS, FAILURE_REASON, Host
from sqlcore.tools import TOOLS, handle

__all__ = ["call_tool", "mcp_tools"]

logger = logging.getLogger(__name__)


def mcp_tools() -> list[Tool]:
    """One MCP Tool per sqlcore tool definition, with the same name, description and input schema."""
    return [
        Tool(
            name=str(entry["name"]),
            description=str(entry["description"]),
            input_schema=dict(cast(dict[str, Any], entry["parameters"])),
        )
        for entry in TOOLS
    ]


def call_tool(
    host: Host,
    user: object,
    name: str,
    arguments: dict[str, object] | None,
    limits: Limits = DEFAULT_LIMITS,
) -> CallToolResult:
    """Run one tool call and return it as an MCP result: one text block holding the JSON payload.

    A refusal, an unknown tool or a host failure comes back with isError set. Nothing is raised.
    """
    try:
        result: dict[str, Any] = handle(host, user, name, arguments or {}, limits)
    except Exception:
        logger.exception("sqlmcp tool call failed: %s", name)
        result = {"ok": False, "reason": FAILURE_REASON}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
        is_error=not result["ok"],
    )
