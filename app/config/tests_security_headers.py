"""Security headers on every response: CSP, nosniff, referrer and permissions policy."""

from typing import Any

import pytest
from django.urls import reverse


def test_login_page_has_the_security_headers(client: Any) -> None:
    response = client.get(reverse("login"))

    policy = response["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "object-src 'none'" in policy or "object-src 'self'" in policy
    assert "'unsafe-eval'" in policy  # htmx hx-on handlers and the admin's Alpine need it
    assert "frame-ancestors 'self'" in policy
    assert "form-action 'self'" in policy
    assert "base-uri 'self'" in policy
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"]
    assert "camera=()" in response["Permissions-Policy"]


def test_redirects_and_errors_carry_the_headers_too(client: Any) -> None:
    redirect = client.get("/")
    missing = client.get("/no-such-page-anywhere/")

    assert redirect.status_code == 302
    assert "Content-Security-Policy" in redirect
    assert "Content-Security-Policy" in missing


def test_policy_allows_no_other_site(client: Any) -> None:
    policy = client.get(reverse("login"))["Content-Security-Policy"]

    assert "http:" not in policy
    assert "https:" not in policy
    assert "*" not in policy


def test_report_only_switch_changes_the_header_name(client: Any, settings: Any) -> None:
    settings.CSP_REPORT_ONLY = True

    response = client.get(reverse("login"))

    assert "Content-Security-Policy-Report-Only" in response
    assert "Content-Security-Policy" not in response


def test_a_view_that_sets_its_own_policy_keeps_it(client: Any, settings: Any) -> None:
    from django.http import HttpResponse
    from django.test import RequestFactory

    from config.middleware import SecurityHeadersMiddleware

    own = "default-src 'none'"
    middleware = SecurityHeadersMiddleware(lambda request: HttpResponse(headers={"Content-Security-Policy": own}))

    response = middleware(RequestFactory().get("/x/"))

    assert response["Content-Security-Policy"] == own
    assert "Permissions-Policy" in response


pytestmark = pytest.mark.django_db
