"""Promotion routes (all need a token):

GET/POST       promotions        paged list (?q=, limit, offset) / create
GET/PUT/DELETE promotions/<id>   one promotion with its lines
"""

import json
from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from autoservice import promotions
from autoservice.registry import DEFAULT_LIMIT, MAX_LIMIT
from autoservice.views import _int, error, ok, token_required

NOT_FOUND = "Урамшуулал олдсонгүй."


def _json(request: HttpRequest) -> dict[str, Any] | None:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _full(pk: int, status: int = 200) -> JsonResponse:
    p = promotions.load(pk)
    return error(404, NOT_FOUND) if p is None else ok(p, status)


def _save(request: HttpRequest, pk: int | None) -> HttpResponse:
    body = _json(request)
    if body is None:
        return error(400, "JSON биш хүсэлт байна.")
    try:
        data = promotions.parse(body)
        with transaction.atomic():
            if pk is None:
                new_id = promotions.create(data)
            elif promotions.replace(pk, data):
                new_id = pk
            else:
                return error(404, NOT_FOUND)
    except promotions.PromotionError as e:
        return error(400, str(e))
    except IntegrityError:
        return error(400, "Барааны ангилал эсвэл ажил олдсонгүй.")
    return _full(new_id, 201 if pk is None else 200)


@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def promotion_list(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        return _save(request, None)
    limit = _int(request.GET.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int(request.GET.get("offset"), 0, 0, 10_000_000)
    rows, total = promotions.listing(request.GET.get("q", "").strip(), limit, offset)
    return ok({"count": total, "limit": limit, "offset": offset, "results": rows})


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@token_required
def promotion_detail(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method == "GET":
        return _full(pk)
    if request.method == "PUT":
        return _save(request, pk)
    with transaction.atomic():
        deleted = promotions.delete(pk)
    return HttpResponse(status=204) if deleted else error(404, NOT_FOUND)
