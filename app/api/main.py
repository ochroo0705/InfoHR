from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError
from ninja.security import django_auth

from api.auth import auth_router
from api.errors import ApiError
from api.meta import meta_router
from api.nav import nav_router

API_VERSION = 1  # bumped when the API changes shape in a way a client must notice (GET /api/v1/meta reports it)

# Closed by default: every operation needs a signed-in session unless it says `auth=None` itself.
# django_auth already enforces CSRF on unsafe methods, so csrf=True is not set (deprecated in ninja 1.4.3).
api = NinjaAPI(
    title="MACS Human Capital API",
    version="1",
    urls_namespace="api",
    docs_url=None,
    auth=django_auth,
)


def _error_response(
    request: HttpRequest,
    status: int,
    form_errors: list[str],
    field_errors: dict[str, list[str]] | None = None,
    code: str = "",
) -> HttpResponse:
    body: dict[str, object] = {"field_errors": field_errors or {}, "form_errors": form_errors}
    if code:
        body["code"] = code
    return api.create_response(request, body, status=status)


@api.exception_handler(ApiError)
def api_error_handler(request: HttpRequest, exc: ApiError) -> HttpResponse:
    return _error_response(request, exc.status, exc.form_errors, exc.field_errors, exc.code)


@api.exception_handler(ValidationError)
def validation_error_handler(request: HttpRequest, exc: ValidationError) -> HttpResponse:
    field_errors: dict[str, list[str]] = {}
    for error in exc.errors:
        loc = error.get("loc") or ()
        name = str(loc[-1]) if loc else ""
        field_errors.setdefault(name, []).append(str(error.get("msg", "")))
    return _error_response(request, 400, [], field_errors)


@api.exception_handler(AuthenticationError)
def authentication_error_handler(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
    return _error_response(request, 401, ["Нэвтрэх шаардлагатай."], code="not_authenticated")


@api.exception_handler(HttpError)
def http_error_handler(request: HttpRequest, exc: HttpError) -> HttpResponse:
    return _error_response(request, exc.status_code, [str(exc.message)])


api.add_router("/auth/", auth_router)
api.add_router("/meta", meta_router)
api.add_router("/nav", nav_router)
