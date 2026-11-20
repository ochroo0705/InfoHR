from __future__ import annotations

import asyncio
import re
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx2
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from front_server.app import create_app
from front_server.static import is_ported, load_patterns
from front_server.tests.conftest import Stack

INDEX_BODY = "<!doctype html><title>x</title>"
PORTED_JSON = '["^\\\\/employees\\\\/orders\\\\/print\\\\/$", "^\\\\/employees\\\\/\\\\d+\\\\/$"]'
CANARY = "LEAK-CANARY-CONTENT"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "fonts").mkdir()
    (root / "index.html").write_text(INDEX_BODY, encoding="utf-8")
    (root / "ported.json").write_text(PORTED_JSON, encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log(1);", encoding="utf-8")
    (root / "fonts" / "f.woff2").write_bytes(b"wOF2")
    (tmp_path / "secret.txt").write_text(CANARY, encoding="utf-8")
    return root


@pytest.fixture
def client(dist: Path) -> TestClient:
    return TestClient(create_app(dist, "http://127.0.0.1:1"))


def test_ported_get_with_query_serves_index(client: TestClient) -> None:
    response = client.get("/employees/orders/print/?x=1")
    assert response.status_code == 200
    assert response.text == INDEX_BODY
    assert response.headers["cache-control"] == "no-cache"


def test_ported_head_serves_index_headers(client: TestClient) -> None:
    response = client.head("/employees/12/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_unported_get_is_not_index(stack: Stack, http: httpx2.Client) -> None:
    response = http.get(stack.front_url + "/employees/12/edit/")
    assert response.status_code == 200
    assert response.json()["path"] == "/employees/12/edit/"
    assert ("GET", "/employees/12/edit/") in stack.requests


def test_post_to_ported_path_is_not_index(stack: Stack, http: httpx2.Client) -> None:
    response = http.post(stack.front_url + "/employees/12/", content=b"a=1")
    assert response.status_code == 200
    assert response.json()["method"] == "POST"
    assert ("POST", "/employees/12/") in stack.requests


def test_assets_are_served_with_immutable_cache(client: TestClient) -> None:
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log(1);"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_fonts_have_one_day_cache(client: TestClient) -> None:
    response = client.get("/fonts/f.woff2")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"


def test_missing_asset_is_404(client: TestClient) -> None:
    assert client.get("/assets/nope.js").status_code == 404


async def _raw_get(app: Starlette, raw_path: str) -> tuple[int, bytes]:
    """Send a GET straight to the ASGI app, so the client cannot normalise '..' before the server sees it."""
    decoded = unquote(raw_path)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": decoded,
        "raw_path": raw_path.encode("ascii"),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 50000),
    }
    status = 0
    body = bytearray()

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])
        elif message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    await app(scope, receive, send)
    return status, bytes(body)


@pytest.mark.parametrize(
    "raw_path",
    ["/assets/../../secret.txt", "/assets/%2e%2e/%2e%2e/secret.txt"],
)
def test_asset_traversal_is_404_and_leaks_nothing(dist: Path, raw_path: str) -> None:
    app = create_app(dist, "http://127.0.0.1:1")
    status, body = asyncio.run(_raw_get(app, raw_path))
    assert status == 404
    assert CANARY.encode() not in body


def test_ported_path_without_index_is_503_but_assets_still_serve(dist: Path) -> None:
    (dist / "index.html").unlink()
    client = TestClient(create_app(dist, "http://127.0.0.1:1"))
    response = client.get("/employees/12/")
    assert response.status_code == 503
    assert response.text == "Run npm run build in web/"
    assert client.get("/assets/app.js").status_code == 200


def test_missing_ported_json_means_nothing_is_ported(dist: Path) -> None:
    (dist / "ported.json").unlink()
    with TestClient(create_app(dist, "http://127.0.0.1:1")) as client:
        response = client.get("/employees/orders/print/")
    assert response.status_code == 502
    assert response.text == "Bad gateway"


def test_load_patterns_returns_empty_when_manifest_missing(tmp_path: Path) -> None:
    assert load_patterns(tmp_path) == []


def test_load_patterns_compiles_each_source(dist: Path) -> None:
    patterns = load_patterns(dist)
    assert len(patterns) == 2
    assert all(isinstance(p, re.Pattern) for p in patterns)


def test_is_ported_matches_only_listed_paths(dist: Path) -> None:
    patterns = load_patterns(dist)
    assert is_ported("/employees/orders/print/", patterns)
    assert is_ported("/employees/7/", patterns)
    assert not is_ported("/employees/7/edit/", patterns)
    assert not is_ported("/leave/", patterns)
