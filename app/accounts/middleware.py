"""Send a user with a temporary password to the change-password page before anything else."""

import ipaddress
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from accounts import audit_context


def client_ip(request: HttpRequest) -> str | None:
    """The visitor's IP for the system log, or None when the value is not a valid IP.

    When AUDIT_TRUSTED_PROXY_HEADER names a request.META key (e.g. HTTP_X_FORWARDED_FOR), its last
    comma-separated value is used: the hop the operator's own proxy appended. The first value can be
    sent by the client. Otherwise REMOTE_ADDR is used.
    """
    header = settings.AUDIT_TRUSTED_PROXY_HEADER
    if header:
        value = request.META.get(header, "").split(",")[-1].strip()
    else:
        value = request.META.get("REMOTE_ADDR", "").strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


class AuditContextMiddleware:
    """Put the request's user and IP into audit_context, so system-log entries can read them.

    The context is always cleared after the response, even when the view raises.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        try:
            audit_context.set_context(user, client_ip(request))
            return self.get_response(request)
        finally:
            audit_context.clear_context()


class ForcePasswordChangeMiddleware:
    """While `must_change_password` is set, every page redirects to the change form.

    The change form itself, logout and static files stay reachable. htmx requests get an
    HX-Redirect header instead of a 302, so the whole page moves rather than a fragment.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "must_change_password", False):
            if not self._exempt(request.path):
                target = reverse("password_change")
                if request.headers.get("HX-Request"):
                    response = HttpResponse(status=200)
                    response["HX-Redirect"] = target
                    return response
                return redirect(target)
        return self.get_response(request)

    @staticmethod
    def _exempt(path: str) -> bool:
        return (
            path == reverse("password_change")
            or path == reverse("logout")
            or path.startswith(settings.STATIC_URL)
            or path.startswith("/admin/jsi18n/")
        )
