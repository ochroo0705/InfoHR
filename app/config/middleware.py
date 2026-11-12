from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.middleware.locale import LocaleMiddleware
from django.utils import translation


class DefaultLanguageMiddleware(LocaleMiddleware):
    """Mongolian unless the user picked another language with the switcher.

    Django's LocaleMiddleware would follow the browser's Accept-Language header, which
    shows English to anyone whose browser is set to English.
    """

    def process_request(self, request: HttpRequest) -> None:
        chosen = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME, "")
        language = chosen if chosen in dict(settings.LANGUAGES) else settings.LANGUAGE_CODE
        translation.activate(language)
        request.LANGUAGE_CODE = translation.get_language()


class SecurityHeadersMiddleware:
    """Content-Security-Policy and Permissions-Policy on every response, including redirects and framework errors.

    The policy text is settings.CONTENT_SECURITY_POLICY; with settings.CSP_REPORT_ONLY the browser only reports
    violations in its console instead of blocking (for trying a stricter policy). A view that sets its own header
    keeps it.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        name = "Content-Security-Policy-Report-Only" if settings.CSP_REPORT_ONLY else "Content-Security-Policy"
        if name not in response:
            response[name] = settings.CONTENT_SECURITY_POLICY
        if "Permissions-Policy" not in response:
            response["Permissions-Policy"] = settings.PERMISSIONS_POLICY
        return response
