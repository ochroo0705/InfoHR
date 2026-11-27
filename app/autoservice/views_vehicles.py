"""Vehicle owner routes (all need a token):

GET/POST       vehicles            paged list (?q= plate / owner / VIN / phone / organisation) / create
GET/PUT/DELETE vehicles/<id>       one vehicle
GET            vehicles/hur?plate  the state registry's record of a plate, matched to our mark / organisation
"""

import json
import time
from collections import defaultdict
from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from autoservice import hur, tokens, vehicles
from autoservice.registry import DEFAULT_LIMIT, MAX_LIMIT
from autoservice.views import _int, error, ok, token_required

NOT_FOUND = "Машин олдсонгүй."
HUR_PER_MINUTE = 20  # per user, like carcare.mn: the registry is a paid, shared service
_hur_calls: dict[str, list[float]] = defaultdict(list)


def _json(request: HttpRequest) -> dict[str, Any] | None:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _full(pk: int, status: int = 200, mark_created: bool = False) -> JsonResponse:
    v = vehicles.load(pk)
    # `mark_created`: the mark came from the registry and was added to CAR_REF by this save
    return (
        error(404, NOT_FOUND) if v is None else ok({**v, "mark_created": mark_created} if mark_created else v, status)
    )


def _save(request: HttpRequest, pk: int | None) -> HttpResponse:
    body = _json(request)
    if body is None:
        return error(400, "JSON биш хүсэлт байна.")
    try:
        data = vehicles.parse(body)
        with transaction.atomic():
            if pk is None:
                new_id = vehicles.create(data)
            elif vehicles.replace(pk, data):
                new_id = pk
            else:
                return error(404, NOT_FOUND)
    except vehicles.VehicleError as e:
        return error(400, str(e))
    except IntegrityError:
        return error(400, "Марк эсвэл байгууллага олдсонгүй.")
    return _full(new_id, 201 if pk is None else 200, bool(data.get("mark_created")))


@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def vehicle_list(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        return _save(request, None)
    limit = _int(request.GET.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int(request.GET.get("offset"), 0, 0, 10_000_000)
    rows, total = vehicles.listing(request.GET.get("q", "").strip(), limit, offset)
    return ok({"count": total, "limit": limit, "offset": offset, "results": rows})


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@token_required
def vehicle_detail(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method == "GET":
        return _full(pk)
    if request.method == "PUT":
        return _save(request, pk)
    try:
        with transaction.atomic():
            deleted = vehicles.delete(pk)
    except vehicles.VehicleInUse as e:
        return error(409, str(e))
    return HttpResponse(status=204) if deleted else error(404, NOT_FOUND)


def _allowed(username: str) -> bool:
    now = time.monotonic()
    calls = [t for t in _hur_calls[username] if now - t < 60]
    _hur_calls[username] = calls
    if len(calls) >= HUR_PER_MINUTE:
        return False
    calls.append(now)
    return True


@require_GET
@token_required
def vehicle_hur(request: HttpRequest) -> JsonResponse:
    user: tokens.TokenUser = request.autoservice_user  # type: ignore[attr-defined]
    plate = request.GET.get("plate", "").strip()
    if not plate:
        return error(400, "Улсын дугаараа оруулна уу.")
    if not _allowed(user.username):
        return error(429, "ХУР-ын лавлагааг хэт олон удаа дуудлаа. Минутын дараа дахин оролдоно уу.")
    try:
        info = hur.vehicle(plate)
    except hur.HurError as e:
        return error(e.status, str(e))
    existing = vehicles.find_by_plate(info["plate"])
    return ok({**info, **vehicles.match_hur(info), "registered_id": existing})
