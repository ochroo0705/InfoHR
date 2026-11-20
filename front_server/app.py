from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from front_server.proxy import proxy_request
from front_server.static import load_patterns, serve_static

MAX_BODY = 25 * 1024 * 1024
PROXY_TIMEOUT = httpx2.Timeout(connect=5, read=300, write=60, pool=5)
# Starlette treats methods=None on a function endpoint as GET only, so list the methods explicitly.
ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def create_app(
    dist_dir: Path,
    django_url: str,
    max_body: int = MAX_BODY,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> Starlette:
    """Build the front server. Static files come from dist_dir; everything else is proxied to django_url."""
    patterns = load_patterns(dist_dir)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with httpx2.AsyncClient(
            timeout=PROXY_TIMEOUT,
            follow_redirects=False,
            transport=transport,
        ) as client:
            app.state.client = client
            yield

    async def catch_all(request: Request) -> Response:
        static = await serve_static(request, dist_dir, patterns)
        if static is not None:
            return static
        client: httpx2.AsyncClient = request.app.state.client
        return await proxy_request(request, client, django_url, max_body)

    return Starlette(routes=[Route("/{path:path}", catch_all, methods=ALL_METHODS)], lifespan=lifespan)
