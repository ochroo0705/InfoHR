"""Discount settings routes (all need a token):

GET  discounts                  paged list (?q=, limit, offset)
POST discounts                  create
GET/PUT/DELETE discounts/<id>   one discount with its items
GET  discounts/lookups          types, asset accounts, item classes, the next free code
GET  discounts/items            item names to pick from (?q=, limit, offset)
"""

import json
from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from autoservice import discounts
from autoservice.registry import DEFAULT_LIMIT, MAX_LIMIT
from autoservice.views import _int, error, ok, token_required

NOT_FOUND = "Хямдралын тохиргоо олдсонгүй."


def _page(request: HttpRequest) -> tuple[str, int, int]:
    return (
        request.GET.get("q", "").strip(),
        _int(request.GET.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT),
        _int(request.GET.get("offset"), 0, 0, 10_000_000),
    )


def _json(request: HttpRequest) -> dict[str, Any] | None:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _full(pk: int, status: int = 200) -> JsonResponse:
    d = discounts.load(pk)
    return error(404, NOT_FOUND) if d is None else ok(d, status)


def _save(request: HttpRequest, pk: int | None) -> HttpResponse:
    body = _json(request)
    if body is None:
        return error(400, "JSON биш хүсэлт байна.")
    try:
        data = discounts.parse(body)
        with transaction.atomic():
            if pk is None:
                new_id = discounts.create(data)
            elif discounts.replace(pk, data):
                new_id = pk
            else:
                return error(404, NOT_FOUND)
    except (discounts.DiscountError, TypeError, ValueError) as e:
        return error(400, str(e) if isinstance(e, discounts.DiscountError) else "Талбарын утга буруу байна.")
    except IntegrityError:
        return error(400, "Холбогдох бараа олдсонгүй.")
    return _full(new_id, 201 if pk is None else 200)


@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def discount_list(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        return _save(request, None)
    q, limit, offset = _page(request)
    rows, total = discounts.listing(q, limit, offset)
    return ok({"count": total, "limit": limit, "offset": offset, "results": rows})


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@token_required
def discount_detail(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method == "GET":
        return _full(pk)
    if request.method == "PUT":
        return _save(request, pk)
    with transaction.atomic():
        deleted = discounts.delete(pk)
    return HttpResponse(status=204) if deleted else error(404, NOT_FOUND)


@require_GET
@token_required
def discount_lookups(request: HttpRequest) -> JsonResponse:
    return ok(discounts.lookups())


@require_GET
@token_required
def discount_items(request: HttpRequest) -> JsonResponse:
    q, limit, offset = _page(request)
    rows, total = discounts.search_items(q, limit, offset)
    return ok({"count": total, "limit": limit, "offset": offset, "results": rows})
