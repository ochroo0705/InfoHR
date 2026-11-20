from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx2
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from front_server.app import create_app

STACK_INDEX = "<!doctype html><title>stack</title>"
STACK_PORTED = ["^/employees/\\d+/$"]
START_TIMEOUT = 10.0
ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
STREAM_WAIT = 30.0
# UTF-8 bytes of "Привет" (not ASCII, not valid latin-1 text): must cross the proxy byte for byte.
RAW_NOTE = "Привет".encode()
RAW_COOKIE = "сессия=значение".encode()


@dataclass
class _Running:
    """One uvicorn server on its own thread, bound to an ephemeral port."""

    server: uvicorn.Server
    thread: threading.Thread
    port: int

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=START_TIMEOUT)


def _start(app: Starlette) -> _Running:
    # proxy_headers=False: otherwise uvicorn rewrites request.client from X-Forwarded-For
    # and the proxy would append the spoofed address a second time.
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        lifespan="on",
        proxy_headers=False,
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + START_TIMEOUT
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    return _Running(server=server, thread=thread, port=port)


def _stub_django(requests: list[tuple[str, str]], release: threading.Event) -> Starlette:
    """A stand-in for Django. Every request is recorded as (method, path)."""

    async def echo(request: Request) -> Response:
        requests.append((request.method, request.url.path))
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
        return JSONResponse(
            {
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query,
                "headers": [[key, value] for key, value in request.headers.items()],
                "body_size": size,
            }
        )

    async def two_cookies(request: Request) -> Response:
        requests.append((request.method, request.url.path))
        response = PlainTextResponse("ok")
        response.raw_headers.append((b"set-cookie", b"first=1; Path=/"))
        response.raw_headers.append((b"set-cookie", b"second=2; Path=/"))
        return response

    async def raw_header(request: Request) -> Response:
        requests.append((request.method, request.url.path))
        response = PlainTextResponse("ok")
        response.raw_headers.append((b"x-note", RAW_NOTE))
        return response

    async def redirect(request: Request) -> Response:
        requests.append((request.method, request.url.path))
        return Response(status_code=302, headers={"location": "/elsewhere/"})

    async def file(request: Request) -> Response:
        requests.append((request.method, request.url.path))
        return Response(b"sheet", headers={"content-disposition": 'attachment; filename="a.xlsx"'})

    async def stream(request: Request) -> Response:
        requests.append((request.method, request.url.path))

        async def body() -> AsyncIterator[bytes]:
            yield b"first\n"
            deadline = time.monotonic() + STREAM_WAIT
            while not release.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            yield b"second\n"

        return StreamingResponse(body(), media_type="text/plain")

    async def upload(request: Request) -> Response:
        requests.append((request.method, request.url.path))
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
        return PlainTextResponse(str(total))

    return Starlette(
        routes=[
            Route("/api/echo", echo, methods=ALL_METHODS),
            Route("/two-cookies", two_cookies, methods=ALL_METHODS),
            Route("/raw-header", raw_header, methods=ALL_METHODS),
            Route("/redirect", redirect, methods=ALL_METHODS),
            Route("/file", file, methods=ALL_METHODS),
            Route("/stream", stream, methods=ALL_METHODS),
            Route("/upload", upload, methods=ALL_METHODS),
            Route("/{path:path}", echo, methods=ALL_METHODS),
        ]
    )


@dataclass
class Stack:
    """A running front server in front of a stub Django, both on real sockets."""

    front_url: str
    stub_url: str
    requests: list[tuple[str, str]]
    release: threading.Event
    _stub: _Running

    def stop_stub(self) -> None:
        self.release.set()
        self._stub.stop()


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[Stack]:
    requests: list[tuple[str, str]] = []
    release = threading.Event()
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(STACK_INDEX, encoding="utf-8")
    (dist / "ported.json").write_text(json.dumps(STACK_PORTED), encoding="utf-8")

    stub = _start(_stub_django(requests, release))
    front = _start(create_app(dist, f"http://127.0.0.1:{stub.port}"))
    state = Stack(
        front_url=f"http://127.0.0.1:{front.port}",
        stub_url=f"http://127.0.0.1:{stub.port}",
        requests=requests,
        release=release,
        _stub=stub,
    )
    try:
        yield state
    finally:
        release.set()
        front.stop()
        stub.stop()


@dataclass
class TrapStub:
    """A second stub Django that must never be contacted by the proxy."""

    port: int
    requests: list[tuple[str, str]]


@pytest.fixture
def trap_stub() -> Iterator[TrapStub]:
    requests: list[tuple[str, str]] = []
    release = threading.Event()
    running = _start(_stub_django(requests, release))
    try:
        yield TrapStub(port=running.port, requests=requests)
    finally:
        release.set()
        running.stop()


@pytest.fixture
def http() -> Iterator[httpx2.Client]:
    """Real-socket client. The 10 s read timeout is the guard: a buffering proxy fails here instead of hanging."""
    with httpx2.Client(timeout=10, follow_redirects=False) as client:
        yield client
