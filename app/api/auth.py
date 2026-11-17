from accounts import login_throttle
from accounts.models import User
from accounts.password_change import finish_password_change, form_class_for
from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth
from ninja.utils import check_csrf

from api.errors import ApiError, form_error_payload

auth_router = Router(tags=["auth"])

WRONG_CREDENTIALS = "Нэвтрэх нэр эсвэл нууц үг буруу байна."


class CsrfOut(Schema):
    token: str


class LoginIn(Schema):
    username: str
    password: str


class LoginOut(Schema):
    ok: bool
    must_change_password: bool
    csrf: str


@auth_router.get("/csrf", auth=None, response=CsrfOut)
def csrf_token(request: HttpRequest) -> dict[str, str]:
    return {"token": get_token(request)}


@auth_router.post("/login", auth=None, response=LoginOut)
def login_view(request: HttpRequest, payload: LoginIn) -> dict[str, object]:
    # ninja views are csrf_exempt, so the login form's token check is done here (same as cookie auth).
    if check_csrf(request):
        raise HttpError(403, "CSRF check Failed")
    # authenticate() keeps the login throttle and the audit signals in play (accounts/backends.py, signals.py).
    user = authenticate(request, username=payload.username, password=payload.password)
    if user is None:
        if login_throttle.is_locked(request, payload.username):
            raise ApiError(400, [login_throttle.LOCK_MESSAGE])
        raise ApiError(400, [WRONG_CREDENTIALS])
    login(request, user)
    # login() rotates the CSRF secret, so the token the page holds before login is stale: return the new one.
    return {
        "ok": True,
        "must_change_password": bool(getattr(user, "must_change_password", False)),
        "csrf": get_token(request),
    }


@auth_router.post("/logout", auth=django_auth, response={204: None})
def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return HttpResponse(status=204)


class PasswordIn(Schema):
    old_password: str = ""
    new_password1: str
    new_password2: str


@auth_router.post("/password", auth=django_auth, response={204: None})
def password_view(request: HttpRequest, payload: PasswordIn) -> HttpResponse:
    if check_csrf(request):
        raise HttpError(403, "CSRF check Failed")
    user = request.user
    assert isinstance(user, User)
    # Same form choice as ForcedPasswordChangeView: a temporary password is replaced without the old one.
    form = form_class_for(user)(user, data=payload.model_dump())
    if not form.is_valid():
        errors = form_error_payload(form)
        raise ApiError(400, errors["form_errors"], errors["field_errors"])
    form.save()
    finish_password_change(request, user)
    return HttpResponse(status=204)
