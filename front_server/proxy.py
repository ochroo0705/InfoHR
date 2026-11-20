from __future__ import annotations

from collections.abc import AsyncIterator

import httpx2
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response, StreamingResponse

# Lowercased header names as bytes. Headers travel as raw bytes end to end: Starlette decodes
# incoming values as latin-1 and httpx2 encodes str values as ASCII, so a UTF-8 byte would fail.
HOP_BY_HOP = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"te",
        b"trailers",
        b"transfer-encoding",
        b"upgrade",
    }
)
BAD_GATEWAY_TEXT = "Bad gateway"
BAD_REQUEST_TEXT = "Bad request"
TOO_LARGE_TEXT = "Request body too large"


class _BodyTooLarge(Exception):
    """Raised inside the upload stream so that the upstream request is aborted."""


def _has_body(request: Request) -> bool:
    return "content-length" in request.headers or "transfer-encoding" in request.headers


def _target_url(request: Request, django_url: str) -> str | None:
    """Upstream URL for this request, or None when it would not stay on django_url's scheme, host and port.

    Routing uses the percent-decoded path, but the forwarded path is the raw one. A raw target
    such as '%2F@host/x' decodes to a routable path yet would move the authority, so it is refused.
    """
    raw_path = request.scope.get("raw_path")
    path = raw_path if raw_path is not None else request.url.path.encode("utf-8")
    if not path.startswith(b"/"):
        return None
    query = request.scope["query_string"].decode("latin-1")
    url = django_url.rstrip("/") + path.decode("latin-1")
    if query:
        url += "?" + query
    try:
        target = httpx2.URL(url)
        expected = httpx2.URL(django_url)
    except httpx2.InvalidURL:
        return None
    if (target.scheme, target.host, target.port, target.userinfo) != (
        expected.scheme,
        expected.host,
        expected.port,
        b"",
    ):
        return None
    return url


def _request_headers(request: Request) -> list[tuple[bytes, bytes]]:
    """Forward every header as raw bytes except hop-by-hop and X-Forwarded-*, then add our own."""
    pairs: list[tuple[bytes, bytes]] = []
    forwarded_for: list[bytes] = []
    forwarded_proto: bytes | None = None
    host: bytes | None = None
    for name, value in request.scope["headers"]:
        lowered = name.lower()
        if lowered == b"x-forwarded-for":
            forwarded_for.append(value)
        elif lowered == b"x-forwarded-proto" and forwarded_proto is None:
            forwarded_proto = value
        elif lowered == b"host" and host is None:
            host = value
        if lowered in HOP_BY_HOP or lowered.startswith(b"x-forwarded-"):
            continue
        pairs.append((name, value))

    client_ip = request.client.host if request.client else None
    if client_ip:
        forwarded_for.append(client_ip.encode("ascii"))
    if forwarded_for:
        pairs.append((b"X-Forwarded-For", b", ".join(forwarded_for)))

    proto = forwarded_proto or request.url.scheme.encode("ascii")
    pairs.append((b"X-Forwarded-Proto", proto))

    if host:
        pairs.append((b"X-Forwarded-Host", host))
    return pairs


async def proxy_request(
    request: Request,
    client: httpx2.AsyncClient,
    django_url: str,
    max_body: int,
) -> Response:
    """Forward the request to Django and stream the answer back, without holding either body in memory."""
    target = _target_url(request, django_url)
    if target is None:
        return PlainTextResponse(BAD_REQUEST_TEXT, status_code=400)

    declared = request.headers.get("content-length")
    if declared is not None and declared.strip().isdigit() and int(declared) > max_body:
        return PlainTextResponse(TOO_LARGE_TEXT, status_code=413)

    too_large = False

    async def upload() -> AsyncIterator[bytes]:
        nonlocal too_large
        sent = 0
        async for chunk in request.stream():
            sent += len(chunk)
            if sent > max_body:
                too_large = True
                raise _BodyTooLarge
            yield chunk

    outgoing = client.build_request(
        request.method,
        target,
        headers=_request_headers(request),
        content=upload() if _has_body(request) else None,
    )
    try:
        upstream = await client.send(outgoing, stream=True)
    except Exception as exc:
        if too_large:
            return PlainTextResponse(TOO_LARGE_TEXT, status_code=413)
        if isinstance(exc, httpx2.TransportError):
            return PlainTextResponse(BAD_GATEWAY_TEXT, status_code=502)
        raise

    async def relay() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    response = StreamingResponse(
        relay(),
        status_code=upstream.status_code,
        background=BackgroundTask(upstream.aclose),
    )
    # Raw pairs, not a dict and not decoded text: repeated Set-Cookie and non-ASCII values pass unchanged.
    response.raw_headers = [(name, value) for name, value in upstream.headers.raw if name.lower() not in HOP_BY_HOP]
    return response
