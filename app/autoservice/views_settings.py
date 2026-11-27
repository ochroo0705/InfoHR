"""Settings routes (under /api/autoservice/, all need a token):

  GET   settings                    the main settings (company, accounts, VAT, payment methods) - read only
  POST  settings/advanced/unlock    {password}: the signed-in user's own password -> a 10-minute `advancedToken`
  GET   settings/advanced           the Advanced tab; needs the token in the `X-Advanced-Token` header

The Advanced part is never part of `settings`: the password check happens here, on the server, so a screen that merely
hides the tab would not be enough to read it.
"""

from accounts import login_throttle
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from autoservice import passwords, program_settings, tokens
from autoservice.views import _body, _find_login, error, ok, token_required

ADVANCED_HEADER = "X-Advanced-Token"
LOCKED = "Advanced тохиргоог нээхийн тулд нууц үгээ оруулна уу."


def _username(request: HttpRequest) -> str:
    u: tokens.TokenUser = request.autoservice_user  # type: ignore[attr-defined]
    return u.username


@require_GET
@token_required
def settings_main(request: HttpRequest) -> JsonResponse:
    return ok(program_settings.main())


@csrf_exempt
@require_POST
@token_required
def advanced_unlock(request: HttpRequest) -> JsonResponse:
    username = _username(request)
    password = str(_body(request).get("password") or "")
    if not password:
        return error(400, "Нууц үгээ оруулна уу.")
    # Counted apart from the sign-in: guessing the Advanced password must not lock the user out of signing in.
    key = f"advanced:{username}"
    if login_throttle.is_locked(request, key):
        return error(429, login_throttle.LOCK_MESSAGE)
    found = _find_login(username)
    if found is None or not passwords.matches(found[1], password):
        login_throttle.record_failure(request, key)
        # 403, not 401: a 401 means "the session ended" to the web app and its proxy, and would sign the user out.
        return error(403, "Нууц үг буруу байна.")
    login_throttle.reset(request, key)
    token, expires_at = tokens.issue_advanced(username)
    return ok({"advancedToken": token, "expiresAt": expires_at})


@require_GET
@token_required
def settings_advanced(request: HttpRequest) -> HttpResponse:
    if not tokens.read_advanced(request.headers.get(ADVANCED_HEADER, ""), _username(request)):
        return error(403, LOCKED)
    return ok(program_settings.advanced())
