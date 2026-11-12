import json
from typing import Any

import pytest
from accounts.models import User
from django.db import close_old_connections as real_close_old_connections
from django.db.models.signals import post_save
from starlette.testclient import TestClient

from hr_mcp import app as hr_app
from hr_mcp.models import McpCall
from hr_mcp.tests.helpers import INIT_PARAMS, FakeHost, _post, _rpc, commit_for_other_threads
from hr_mcp.tokens import issue_token

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture
def user() -> User:
    return User.objects.create_user("mcp_app_user", password=PASSWORD)


@pytest.fixture
def fake_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hr_app, "HrHost", FakeHost)


@pytest.mark.django_db(transaction=True)
def test_valid_token_lists_tools(user: User, fake_host: None) -> None:
    _row, raw = issue_token(user, "Test client")
    commit_for_other_threads()
    with TestClient(hr_app.make_app()) as client:
        response = _rpc(client, "tools/list", {}, raw)

    assert response.status_code == 200
    names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert "describe_data" in names
    assert "run_query" in names


@pytest.mark.django_db(transaction=True)
def test_bad_token_is_401(user: User, fake_host: None) -> None:
    issue_token(user, "Test client")
    with TestClient(hr_app.make_app()) as client:
        response = _rpc(client, "tools/list", {}, "mhc_not-a-real-token")

    assert response.status_code == 401
    assert "result" not in response.text


@pytest.mark.django_db(transaction=True)
def test_connections_close_after_the_call_log_is_written(
    user: User, fake_host: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def recording_close() -> None:
        events.append("close")
        real_close_old_connections()  # still really close, or the worker thread keeps its connection

    monkeypatch.setattr(hr_app, "close_old_connections", recording_close)

    def on_log_write(**_kwargs: Any) -> None:
        events.append("save")

    post_save.connect(on_log_write, sender=McpCall, weak=False, dispatch_uid="test_mcp_call_write")
    try:
        _row, raw = issue_token(user, "Test client")
        commit_for_other_threads()
        with TestClient(hr_app.make_app()) as client:
            _post(client, "initialize", INIT_PARAMS, raw)
            events.clear()
            response = _post(client, "tools/call", {"name": "describe_data", "arguments": {}}, raw)
    finally:
        post_save.disconnect(sender=McpCall, dispatch_uid="test_mcp_call_write")

    assert response.status_code == 200
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert payload["ok"] is True
    # The call log is written once, closes happen before it, and the last close comes after it.
    assert events.count("save") == 1
    assert events[0] == "close"
    assert events.index("save") > 0
    assert events[-1] == "close"
    assert events.index("save") < len(events) - 1
