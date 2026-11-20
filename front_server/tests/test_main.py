from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import uvicorn
from starlette.applications import Starlette

import front_server.__main__ as launcher
from front_server.__main__ import REPO_ROOT, main
from front_server.app import create_app


@pytest.fixture
def run_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace uvicorn.run and create_app with recorders; create_app still builds the real app."""
    recorded: dict[str, Any] = {}

    def fake_run(app: Starlette, **kwargs: Any) -> None:
        recorded["app"] = app
        recorded["run"] = kwargs

    def spy_create_app(dist_dir: Path, django_url: str, *args: Any, **kwargs: Any) -> Starlette:
        recorded["dist_dir"] = dist_dir
        recorded["django_url"] = django_url
        return create_app(dist_dir, django_url, *args, **kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr(launcher, "create_app", spy_create_app)
    return recorded


def test_main_passes_environment_to_uvicorn(
    monkeypatch: pytest.MonkeyPatch, run_calls: dict[str, Any], tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    monkeypatch.setenv("FRONT_HOST", "127.0.0.1")
    monkeypatch.setenv("FRONT_PORT", "8090")
    monkeypatch.setenv("DJANGO_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("WEB_DIST", str(dist))

    main()

    assert run_calls["run"]["host"] == "127.0.0.1"
    assert run_calls["run"]["port"] == 8090
    assert run_calls["run"]["proxy_headers"] is False
    assert run_calls["dist_dir"] == dist
    assert run_calls["django_url"] == "http://127.0.0.1:8001"
    assert isinstance(run_calls["app"], Starlette)


def test_main_defaults(monkeypatch: pytest.MonkeyPatch, run_calls: dict[str, Any]) -> None:
    for name in ("FRONT_HOST", "FRONT_PORT", "DJANGO_URL", "WEB_DIST"):
        monkeypatch.delenv(name, raising=False)

    main()

    assert run_calls["run"]["host"] == "127.0.0.1"
    assert run_calls["run"]["port"] == 8080
    assert run_calls["run"]["proxy_headers"] is False
    assert run_calls["django_url"] == "http://127.0.0.1:8000"
    assert run_calls["dist_dir"] == REPO_ROOT / "web" / "dist"


def test_relative_web_dist_resolves_against_repo_root(
    monkeypatch: pytest.MonkeyPatch, run_calls: dict[str, Any]
) -> None:
    monkeypatch.setenv("WEB_DIST", "web/dist")

    main()

    assert run_calls["dist_dir"] == REPO_ROOT / "web" / "dist"
