"""Quote routes: GET/POST /api/autoservice/quotes and GET/PUT/DELETE /api/autoservice/quotes/<id>.

Every quote is returned the way the screen wants it (see quotes.load): header fields, `works` and `parts`
lines with `ref` (WORKS / ITEM id), `qty`, `price` (VAT included), `disc`, `card`, `vat`.
"""

import json
from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from autoservice import quotes, tokens
from autoservice.registry import DEFAULT_LIMIT, MAX_LIMIT
from autoservice.views import _int, error, ok, token_required

FILTERS = ("branch_id", "plate", "org", "from", "to", "q")


def _json_body(request: HttpRequest) -> dict[str, Any] | None:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _user(request: HttpRequest) -> str:
    u: tokens.TokenUser = request.autoservice_user  # type: ignore[attr-defined]
    return u.username


def _full(pk: int) -> JsonResponse:
    q = quotes.load(pk)
    return error(404, "Үнийн санал олдсонгүй.") if q is None else ok(q)


def _list(request: HttpRequest) -> JsonResponse:
    limit = _int(request.GET.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int(request.GET.get("offset"), 0, 0, 10_000_000)
    filters = {k: request.GET.get(k, "").strip() for k in FILTERS if request.GET.get(k, "").strip()}
    if "branch_id" in filters and not filters["branch_id"].isdigit():
        return error(400, "branch_id тоо байх ёстой.")
    try:
        rows, total = quotes.listing(filters, limit, offset)
    except quotes.QuoteError as e:
        return error(400, str(e))
    return ok({"count": total, "limit": limit, "offset": offset, "results": rows})


def _save(request: HttpRequest, pk: int | None) -> HttpResponse:
    body = _json_body(request)
    if body is None:
        return error(400, "JSON биш хүсэлт байна.")
    try:
        data = quotes.parse(body)
        with transaction.atomic():
            if pk is None:
                new_id = quotes.create(data, _user(request))
            elif quotes.replace(pk, data, _user(request)):
                new_id = pk
            else:
                return error(404, "Үнийн санал олдсонгүй.")
    except quotes.QuoteError as e:
        return error(400, str(e))
    except IntegrityError:
        return error(400, "Холбогдох бүртгэл (ажил, бараа, харилцагч, салбар) олдсонгүй.")
    response = _full(new_id)
    response.status_code = 201 if pk is None else 200
    return response


@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def quote_list(request: HttpRequest) -> HttpResponse:
    return _list(request) if request.method == "GET" else _save(request, None)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@token_required
def quote_detail(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method == "GET":
        return _full(pk)
    if request.method == "PUT":
        return _save(request, pk)
    try:
        with transaction.atomic():
            deleted = quotes.delete(pk)
    except quotes.QuoteInUse as e:
        return error(409, str(e))
    return HttpResponse(status=204) if deleted else error(404, "Үнийн санал олдсонгүй.")
