"""Headers for the public employee form, on every response under /apply/.

One place for the headers: framework responses (the CSRF 403, the 405, the 413 for an oversized body, the resolver
404) are covered too, not only the responses the views build.

Referrer-Policy is same-origin, not no-referrer. With no-referrer the browser also sends Origin: null on the native
form POST, and Django's CSRF origin check then refuses the Send with 403. same-origin keeps the Origin header on our
own requests and still sends no Referer to other sites, so the token in the URL does not leak.
"""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


class SelfFormHeadersMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.path_info.startswith("/apply/"):
            response["Cache-Control"] = "no-store"
            response["Referrer-Policy"] = "same-origin"
        return response
