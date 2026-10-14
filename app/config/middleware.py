from django.conf import settings
from django.http import HttpRequest
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
