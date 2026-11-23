from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError
from ninja.security import django_auth

from api.attention import attention_router
from api.auth import auth_router
from api.company import company_router
from api.employee import employee_router
from api.employee_writes import employee_write_router
from api.errors import ApiError
from api.events import events_router
from api.hire import hire_router, selfform_router
from api.me import checklists_router, me_router
from api.meta import meta_router
from api.nav import nav_router
from api.order_files import order_files_router
from api.order_register import order_register_router
from api.orders import orders_router
from api.palette import palette_router
from api.selfforms import selfform_list_router
from api.slots import slot_router
from api.today import today_router

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


# The text ninja's APIKeyCookie (django_auth) raises when the CSRF token is missing or stale (ninja/security/apikey.py).
NINJA_CSRF_FAILED = "CSRF check Failed"


@api.exception_handler(HttpError)
def http_error_handler(request: HttpRequest, exc: HttpError) -> HttpResponse:
    # The React client refetches its token and retries once on this code (web/src/api/mutate.ts).
    is_csrf = exc.status_code == 403 and str(exc.message) == NINJA_CSRF_FAILED
    return _error_response(request, exc.status_code, [str(exc.message)], code="csrf_failed" if is_csrf else "")


api.add_router("/auth/", auth_router)
api.add_router("/meta", meta_router)
api.add_router("/nav", nav_router)
api.add_router("/today", today_router)
api.add_router("/attention", attention_router)
api.add_router("/me", me_router)
api.add_router("/checklists", checklists_router)
api.add_router("/employees", hire_router)  # before employee_router: /employees/new is not a pk
api.add_router("/selfforms", selfform_router)
api.add_router("/selfforms", selfform_list_router)
api.add_router("/employees", employee_router)
api.add_router("/employees", employee_write_router)
api.add_router("/employees", events_router)
api.add_router("/employees", orders_router)
api.add_router("/employees", order_files_router)
api.add_router("/orders", order_register_router)
api.add_router("/company", company_router)
api.add_router("/slots", slot_router)
api.add_router("/palette", palette_router)

if "welcome" in settings.INSTALLED_APPS:
    from welcome.api import welcome_router  # imports welcome.models, which needs the app installed

    api.add_router("/welcome", welcome_router)
