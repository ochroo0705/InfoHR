"""Send a user with a temporary password to the change-password page before anything else."""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse


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
