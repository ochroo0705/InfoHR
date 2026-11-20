from __future__ import annotations

import socket
from collections.abc import Iterator

import httpx2
import pytest
from starlette.requests import Request

from front_server.proxy import _target_url
from front_server.tests.conftest import RAW_COOKIE, RAW_NOTE, STACK_INDEX, Stack, TrapStub

MB = 1024 * 1024


def _values(headers: list[list[str]], name: str) -> list[str]:
    return [value for key, value in headers if key == name]


def _chunks(total_mb: int) -> Iterator[bytes]:
    for _ in range(total_mb):
        yield b"x" * MB


def test_echo_gets_forwarded_headers(stack: Stack, http: httpx2.Client) -> None:
    response = http.get(stack.front_url + "/api/echo")
    assert response.status_code == 200
    headers = response.json()["headers"]
    front_host = stack.front_url.removeprefix("http://")
    assert _values(headers, "x-forwarded-proto") == ["http"]
    assert _values(headers, "x-forwarded-host") == [front_host]
    assert _values(headers, "host") == [front_host]


def test_incoming_forwarded_for_is_extended_with_client_ip(stack: Stack, http: httpx2.Client) -> None:
    response = http.get(stack.front_url + "/api/echo", headers={"X-Forwarded-For": "1.2.3.4"})
    assert _values(response.json()["headers"], "x-forwarded-for") == ["1.2.3.4, 127.0.0.1"]


def test_two_set_cookie_headers_reach_the_browser(stack: Stack, http: httpx2.Client) -> None:
    response = http.get(stack.front_url + "/two-cookies")
    cookies = [value for key, value in response.headers.multi_items() if key.lower() == "set-cookie"]
    assert cookies == ["first=1; Path=/", "second=2; Path=/"]


def test_non_ascii_request_header_is_forwarded_byte_for_byte(stack: Stack, http: httpx2.Client) -> None:
    response = http.get(stack.front_url + "/api/echo", headers=[(b"cookie", RAW_COOKIE)])
    assert response.status_code == 200
    assert _values(response.json()["headers"], "cookie") == [RAW_COOKIE.decode("latin-1")]


def test_non_ascii_response_header_is_passed_byte_for_byte(stack: Stack, http: httpx2.Client) -> None:
    response = http.get(stack.front_url + "/raw-header")
    assert response.status_code == 200
    assert [value for key, value in response.headers.raw if key.lower() == b"x-note"] == [RAW_NOTE]


def test_redirect_is_passed_through_not_followed(stack: Stack, http: httpx2.Client) -> None:
    response = http.get(stack.front_url + "/redirect")
    assert response.status_code == 302
    assert response.headers["location"] == "/elsewhere/"


def test_content_disposition_is_kept(stack: Stack, http: httpx2.Client) -> None:
    response = http.get(stack.front_url + "/file")
    assert response.headers["content-disposition"] == 'attachment; filename="a.xlsx"'
    assert response.content == b"sheet"


def test_stream_reaches_client_before_upstream_finishes(stack: Stack, http: httpx2.Client) -> None:
    with http.stream("GET", stack.front_url + "/stream") as response:
        chunks = response.iter_raw()
        first = next(chunks)
        assert first == b"first\n"
        stack.release.set()
        rest = b"".join(chunks)
    assert rest == b"second\n"


def test_20_mb_upload_passes(stack: Stack, http: httpx2.Client) -> None:
    response = http.post(stack.front_url + "/upload", content=b"x" * (20 * MB))
    assert response.status_code == 200
    assert response.text == str(20 * MB)


def test_30_mb_upload_with_content_length_is_413(stack: Stack, http: httpx2.Client) -> None:
    response = http.post(stack.front_url + "/upload", content=b"x" * (30 * MB))
    assert response.status_code == 413


def test_30_mb_chunked_upload_is_413(stack: Stack, http: httpx2.Client) -> None:
    response = http.post(stack.front_url + "/upload", content=_chunks(30))
    assert response.status_code == 413


def test_django_down_gives_502_but_ported_pages_still_load(stack: Stack, http: httpx2.Client) -> None:
    stack.stop_stub()
    response = http.get(stack.front_url + "/api/echo")
    assert response.status_code == 502
    assert response.text == "Bad gateway"
    page = http.get(stack.front_url + "/employees/12/")
    assert page.status_code == 200
    assert page.text == STACK_INDEX


def test_post_to_ported_path_reaches_django(stack: Stack, http: httpx2.Client) -> None:
    response = http.post(stack.front_url + "/employees/12/", content=b"a=1")
    assert response.status_code == 200
    assert response.json()["method"] == "POST"
    assert ("POST", "/employees/12/") in stack.requests


def _port(url: str) -> int:
    return int(url.rsplit(":", 1)[1])


def _raw_exchange(port: int, target: bytes) -> bytes:
    """Send a raw request line on a plain socket; httpx would normalise the target first."""
    request = b"GET " + target + b" HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(request)
        received = bytearray()
        while True:
            data = sock.recv(65536)
            if not data:
                break
            received.extend(data)
    return bytes(received)


def _status(raw: bytes) -> int | None:
    parts = raw.split(b" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return int(parts[1])


def test_encoded_slash_userinfo_target_is_400_and_never_contacts_second_host(stack: Stack, trap_stub: TrapStub) -> None:
    raw = _raw_exchange(_port(stack.front_url), f"%2F@127.0.0.1:{trap_stub.port}/x".encode())
    assert _status(raw) == 400
    assert trap_stub.requests == []


@pytest.mark.parametrize(
    "target",
    [
        "/%2F@127.0.0.1:{port}/x",
        "@127.0.0.1:{port}/x",
        "http://127.0.0.1:{port}/x",
    ],
)
def test_hostile_targets_never_contact_second_host(stack: Stack, trap_stub: TrapStub, target: str) -> None:
    _raw_exchange(_port(stack.front_url), target.format(port=trap_stub.port).encode())
    assert trap_stub.requests == []


def _request_for(raw_path: bytes, query: bytes = b"") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": raw_path.decode("latin-1"),
        "raw_path": raw_path,
        "root_path": "",
        "query_string": query,
        "headers": [(b"host", b"127.0.0.1:8000")],
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 50000),
    }
    return Request(scope)


BASE_URL = "http://127.0.0.1:8000"


@pytest.mark.parametrize(
    "raw_path",
    [b"/ok/x", b"/%2F@127.0.0.1:9/x", b"@127.0.0.1:9/x", b"//127.0.0.1:9/x", b"/a%40b", b"/\\evil.example/x"],
)
def test_target_url_keeps_scheme_host_and_port_or_is_rejected(raw_path: bytes) -> None:
    target = _target_url(_request_for(raw_path), BASE_URL)
    if target is None:
        return
    parsed = httpx2.URL(target)
    expected = httpx2.URL(BASE_URL)
    assert (parsed.scheme, parsed.host, parsed.port) == (expected.scheme, expected.host, expected.port)
    assert parsed.userinfo == b""


def test_target_url_rejects_path_not_starting_with_slash() -> None:
    assert _target_url(_request_for(b"%2F@127.0.0.1:9/x"), BASE_URL) is None


def test_target_url_builds_query_from_raw_query_string() -> None:
    assert _target_url(_request_for(b"/a", b"q=1&r=2"), BASE_URL) == "http://127.0.0.1:8000/a?q=1&r=2"


def test_query_string_reaches_django_intact(stack: Stack, http: httpx2.Client) -> None:
    response = http.get(stack.front_url + "/api/echo?a=1&b=%D0%9F")
    assert response.status_code == 200
    assert response.json()["query"] == "a=1&b=%D0%9F"
