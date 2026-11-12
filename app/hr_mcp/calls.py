"""Log every MCP tool call and limit how many one token may make per minute.

The default call hook for the HR MCP app. It records the call (tool, SQL text, outcome, row
count and duration) in McpCall, and refuses the call without running it once the token has
reached settings.MCP_RATE_PER_MINUTE calls in the last 60 seconds.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from mcp.types import CallToolResult, TextContent

from hr_mcp.models import McpCall, McpToken

__all__ = ["RATE_REASON", "log_and_limit"]

RATE_REASON = "Too many requests. Wait a minute and try again."
RATE_WINDOW = timedelta(seconds=60)
SQL_LOG_LIMIT = 4000


def _result(payload: dict[str, object], *, is_error: bool) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        is_error=is_error,
    )


def _sql_of(arguments: dict[str, object]) -> str:
    sql = arguments.get("sql", "")
    return sql[:SQL_LOG_LIMIT] if isinstance(sql, str) else ""


def _payload_of(result: CallToolResult) -> dict[str, object]:
    try:
        parsed = json.loads(result.content[0].text)  # type: ignore[union-attr]
    except (AttributeError, IndexError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def log_and_limit(
    principal: McpToken,
    name: str,
    arguments: dict[str, object],
    run: Callable[[], CallToolResult],
) -> CallToolResult:
    """Run one tool call for the token, unless the token is over its rate limit; log the call either way."""
    sql = _sql_of(arguments)
    since = timezone.now() - RATE_WINDOW
    recent = McpCall.objects.filter(token=principal, at__gte=since).count()
    if recent >= settings.MCP_RATE_PER_MINUTE:
        McpCall.objects.create(
            token=principal, tool=name, sql=sql, ok=False, reason=RATE_REASON, row_count=None, duration_ms=0
        )
        return _result({"ok": False, "reason": RATE_REASON}, is_error=True)

    started = time.monotonic()
    result = run()
    duration_ms = int((time.monotonic() - started) * 1000)

    payload = _payload_of(result)
    rows = payload.get("rows")
    reason = payload.get("reason")
    McpCall.objects.create(
        token=principal,
        tool=name,
        sql=sql,
        ok=not result.is_error,
        reason=str(reason)[:300] if isinstance(reason, str) else "",
        row_count=len(rows) if isinstance(rows, list) else None,
        duration_ms=duration_ms,
    )
    return result
