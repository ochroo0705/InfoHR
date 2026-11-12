import pytest
import uvicorn
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from hr_mcp.management.commands import run_mcp

DISABLED_MESSAGE = "The MCP server is turned off. Set MCP_ENABLED=true to run it."


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_run(app: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr(run_mcp, "make_app", lambda: "APP")
    return calls


@override_settings(MCP_ENABLED=False)
def test_disabled_raises(recorder: list[dict[str, object]]) -> None:
    with pytest.raises(CommandError) as exc:
        call_command("run_mcp")
    assert str(exc.value) == DISABLED_MESSAGE
    assert recorder == []


@override_settings(MCP_ENABLED=True, MCP_BIND_HOST="127.0.0.1", MCP_BIND_PORT=8765)
def test_defaults_bind_localhost(recorder: list[dict[str, object]]) -> None:
    call_command("run_mcp")
    assert recorder == [{"host": "127.0.0.1", "port": 8765, "log_level": "info"}]


@override_settings(MCP_ENABLED=True, MCP_BIND_HOST="127.0.0.1", MCP_BIND_PORT=8765)
def test_flags_override(recorder: list[dict[str, object]]) -> None:
    call_command("run_mcp", "--host", "0.0.0.0", "--port", "9000")  # noqa: S104  (test argument; nothing binds)
    assert recorder == [{"host": "0.0.0.0", "port": 9000, "log_level": "info"}]  # noqa: S104  (test value only)
