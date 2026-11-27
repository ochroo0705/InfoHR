"""Discount card routes (read only; all need a token):

GET discount-cards                  paged list (?q= card no / owner / plate, limit, offset) with type and bonus balance
GET discount-cards/<id>             one card
GET discount-cards/<id>/statement   usage log (?from=YYYY-MM-DD&to=YYYY-MM-DD)
GET discount-cards/intervals        bonus collecting intervals (DISCOUNT_PERCENT)
"""

from datetime import date

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from autoservice import cards
from autoservice.registry import DEFAULT_LIMIT, MAX_LIMIT
from autoservice.views import _int, error, ok, token_required

NOT_FOUND = "Карт олдсонгүй."


@require_GET
@token_required
def card_list(request: HttpRequest) -> JsonResponse:
    limit = _int(request.GET.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int(request.GET.get("offset"), 0, 0, 10_000_000)
    rows, total = cards.listing(request.GET.get("q", "").strip(), limit, offset)
    return ok({"count": total, "limit": limit, "offset": offset, "results": rows})


@require_GET
@token_required
def card_detail(request: HttpRequest, pk: int) -> JsonResponse:
    card = cards.load(pk)
    return error(404, NOT_FOUND) if card is None else ok(card)


def _day(value: str) -> str | None:
    try:
        return date.fromisoformat(value).isoformat() if value else ""
    except ValueError:
        return None


@require_GET
@token_required
def card_statement(request: HttpRequest, pk: int) -> JsonResponse:
    start, end = _day(request.GET.get("from", "")), _day(request.GET.get("to", ""))
    if start is None or end is None:
        return error(400, "Огноо YYYY-MM-DD хэлбэртэй байх ёстой.")
    if cards.load(pk) is None:
        return error(404, NOT_FOUND)
    return ok({"results": cards.statement(pk, start, end)})


@require_GET
@token_required
def card_intervals(request: HttpRequest) -> JsonResponse:
    return ok({"results": cards.intervals()})
