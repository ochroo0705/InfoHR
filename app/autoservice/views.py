"""Online Auto Service JSON API (mounted at /api/autoservice/).

Token based: no cookie, no session, no Django login. `login` trades a MACS user name and password for a bearer
token; every other route needs `Authorization: Bearer <token>`. Runs in the same process as the Human Capital app.
"""

import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from typing import Any

from accounts import login_throttle
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from autoservice import passwords, tokens
from autoservice.registry import DEFAULT_LIMIT, DIRECTORIES, MAX_LIMIT, Directory

View = Callable[..., HttpResponse]


def error(status: int, message: str) -> JsonResponse:
    return JsonResponse({"error": {"message": message}}, status=status, json_dumps_params={"ensure_ascii": False})


def ok(data: Any, status: int = 200) -> JsonResponse:
    return JsonResponse(data, status=status, safe=not isinstance(data, list), json_dumps_params={"ensure_ascii": False})


def clean(value: Any) -> Any:
    """A column value as JSON: Firebird CHAR padding stripped, numbers and dates in plain JSON types."""
    if isinstance(value, str):
        return value.rstrip()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes | memoryview):
        return None  # blobs (pictures) are not part of the lists
    return value


def bearer(request: HttpRequest) -> tokens.TokenUser | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return tokens.read(token.strip())


def token_required(view: View) -> View:
    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = bearer(request)
        if user is None:
            response = error(401, "Нэвтрэх шаардлагатай эсвэл хугацаа дууссан.")
            response["WWW-Authenticate"] = "Bearer"
            return response
        request.autoservice_user = user  # type: ignore[attr-defined]
        return view(request, *args, **kwargs)

    return wrapper


def _body(request: HttpRequest) -> dict[str, Any]:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _find_login(username: str) -> tuple[str, str, str, int | None, str] | None:
    """(user name, password, rights, branch id, email) of the SECURITY row for this name, case-insensitive."""
    with connection.cursor() as c:
        c.execute(
            "SELECT USER_NAME, PASSW, RGHT, BRANCH_IDENT, EMAIL FROM SECURITY WHERE UPPER(USER_NAME) = UPPER(%s)",
            [username],
        )
        row = c.fetchone()
    if row is None:
        return None
    name, passw, rights, branch, email = row
    return str(name).strip(), str(passw or ""), str(rights or "").strip(), branch, str(email or "").strip()


@csrf_exempt
@require_POST
def login(request: HttpRequest) -> JsonResponse:
    body = _body(request)
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not username or not password:
        return error(400, "Нэвтрэх нэр, нууц үгээ оруулна уу.")
    if login_throttle.is_locked(request, username):
        return error(429, login_throttle.LOCK_MESSAGE)
    found = _find_login(username)
    # One answer for an unknown name and a wrong password, so the API does not reveal which names exist.
    if found is None or not passwords.matches(found[1], password):
        login_throttle.record_failure(request, username)
        return error(401, "Нэвтрэх нэр эсвэл нууц үг буруу байна.")
    name, _, rights, branch, email = found
    login_throttle.reset(request, username)
    token, expires_at = tokens.issue(name, rights)
    return ok(
        {
            "accessToken": token,
            "tokenType": "Bearer",
            "expiresAt": expires_at,
            "user": {"username": name, "rights": rights, "email": email, "branch_id": branch},
        }
    )


@csrf_exempt
@require_POST
@token_required
def logout(request: HttpRequest) -> HttpResponse:
    # Tokens are stateless and cannot be revoked; the client drops its copy. They expire on their own.
    return HttpResponse(status=204)


@require_GET
@token_required
def me(request: HttpRequest) -> JsonResponse:
    u: tokens.TokenUser = request.autoservice_user  # type: ignore[attr-defined]
    return ok({"username": u.username, "rights": u.rights, "expiresAt": u.expires_at})


@require_GET
@token_required
def directory_index(request: HttpRequest) -> JsonResponse:
    return ok({"directories": sorted(DIRECTORIES)})


def _int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        return min(max(int(value or default), low), high)
    except ValueError:
        return default


def _select(d: Directory, where: str, params: list[Any], limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    cols = ", ".join(d.columns.values())
    keys = list(d.columns)
    with connection.cursor() as c:
        c.execute(f"SELECT COUNT(*) FROM {d.table}{where}", params)  # noqa: S608 - names are constants (registry.py)
        total = int(c.fetchone()[0])
        c.execute(
            f"SELECT FIRST {int(limit)} SKIP {int(offset)} {cols} FROM {d.table}{where} ORDER BY {d.order}",  # noqa: S608
            params,
        )
        rows = [dict(zip(keys, (clean(v) for v in row), strict=True)) for row in c.fetchall()]
    return rows, total


@require_GET
@token_required
def directory(request: HttpRequest, slug: str) -> JsonResponse:
    d = DIRECTORIES.get(slug)
    if d is None:
        return error(404, "Ийм лавлах байхгүй.")
    limit = _int(request.GET.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int(request.GET.get("offset"), 0, 0, 10_000_000)
    conditions: list[str] = [f"({d.where})"] if d.where else []
    params: list[Any] = []
    q = request.GET.get("q", "").strip()
    if q and d.search:
        conditions.append("(" + " OR ".join(f"UPPER({col}) LIKE UPPER(%s)" for col in d.search) + ")")
        params = [f"%{q}%"] * len(d.search)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows, total = _select(d, where, params, limit, offset)
    return ok({"count": total, "limit": limit, "offset": offset, "results": rows})
