from datetime import timedelta

import pytest
from accounts.models import User
from django.utils import timezone
from mcp.types import CallToolResult, TextContent
from pytest_django.fixtures import SettingsWrapper
from sqlcore.catalogue import Catalogue
from sqlcore.check import CheckedQuery
from sqlcore.limits import Limits, Result
from sqlmcp.adapter import call_tool
from starlette.testclient import TestClient

from hr_mcp import app as hr_app
from hr_mcp.calls import RATE_REASON, log_and_limit
from hr_mcp.models import McpCall, McpToken
from hr_mcp.tests.helpers import FakeHost, _rpc, commit_for_other_threads
from hr_mcp.tokens import issue_token

PASSWORD = "x-long-pass-123"  # noqa: S105


class EmptyHost:
    """A host with no views: describe_data succeeds, run_query is never reached by these tests."""

    def catalogue_for(self, user: object) -> Catalogue:
        return Catalogue(views=())

    def execute(self, user: object, query: CheckedQuery, limits: Limits) -> Result:  # pragma: no cover
        raise AssertionError("execute must not be reached in these tests")

    def cancel(self, user: object) -> None:
        pass


@pytest.fixture
def user() -> User:
    return User.objects.create_user("mcp_calls_user", password=PASSWORD)


@pytest.fixture
def token(user: User) -> McpToken:
    row, _raw = issue_token(user, "Test client")
    return row


def _ok_result() -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text='{"ok": true, "rows": [[1], [2]]}')], is_error=False)


@pytest.mark.django_db
def test_successful_call_is_logged(token: McpToken, settings: SettingsWrapper) -> None:
    settings.MCP_RATE_PER_MINUTE = 30

    def run() -> CallToolResult:
        return call_tool(EmptyHost(), token.user, "describe_data", {})

    result = log_and_limit(token, "describe_data", {}, run)

    assert result.is_error is False
    call = McpCall.objects.get(token=token)
    assert call.tool == "describe_data"
    assert call.ok is True
    assert call.reason == ""
    assert call.duration_ms >= 0


@pytest.mark.django_db
def test_refused_call_is_logged_with_reason(token: McpToken, settings: SettingsWrapper) -> None:
    settings.MCP_RATE_PER_MINUTE = 30
    sql = "DELETE FROM X"

    def run() -> CallToolResult:
        return call_tool(EmptyHost(), token.user, "run_query", {"sql": sql})

    result = log_and_limit(token, "run_query", {"sql": sql}, run)

    assert result.is_error is True
    call = McpCall.objects.get(token=token)
    assert call.tool == "run_query"
    assert call.ok is False
    assert call.reason != ""
    assert call.sql == sql
    assert call.row_count is None


@pytest.mark.django_db
def test_rate_limit_refuses_after_limit(token: McpToken, settings: SettingsWrapper) -> None:
    settings.MCP_RATE_PER_MINUTE = 2
    calls: list[int] = []

    def run() -> CallToolResult:
        calls.append(1)
        return _ok_result()

    log_and_limit(token, "describe_data", {}, run)
    log_and_limit(token, "describe_data", {}, run)
    third = log_and_limit(token, "describe_data", {}, run)

    assert third.is_error is True
    block = third.content[0]
    assert isinstance(block, TextContent)
    assert RATE_REASON in block.text
    assert len(calls) == 2
    refused = McpCall.objects.filter(token=token, ok=False).get()
    assert refused.reason == RATE_REASON


@pytest.mark.django_db
def test_old_calls_do_not_count(token: McpToken, settings: SettingsWrapper) -> None:
    settings.MCP_RATE_PER_MINUTE = 1
    old = McpCall.objects.create(token=token, tool="describe_data", ok=True, duration_ms=1)
    McpCall.objects.filter(pk=old.pk).update(at=timezone.now() - timedelta(minutes=2))

    result = log_and_limit(token, "describe_data", {}, _ok_result)

    assert result.is_error is False
    assert McpCall.objects.filter(token=token).count() == 2


@pytest.mark.django_db(transaction=True)
def test_make_app_logs_calls_by_default(user: User, settings: SettingsWrapper, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.MCP_RATE_PER_MINUTE = 30
    monkeypatch.setattr(hr_app, "HrHost", FakeHost)
    _row, raw = issue_token(user, "Test client")
    commit_for_other_threads()
    with TestClient(hr_app.make_app()) as client:
        _rpc(client, "tools/call", {"name": "describe_data", "arguments": {}}, raw)

    commit_for_other_threads()
    assert McpCall.objects.filter(token__user=user, tool="describe_data", ok=True).exists()
