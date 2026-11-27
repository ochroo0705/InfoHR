"""Aggregate repair routes (all under /api/autoservice/, all need a token):

GET/POST  repairs                       list (filters: status, mode, plate, org, q) / create a not-started card
GET/PUT/DELETE  repairs/<id>            open / rewrite / delete (refused once finished or paid)
POST      repairs/<id>/start            not started -> started
POST      repairs/<id>/finish           set the exit date and finish (the database checks mechanics and payment)
POST      repairs/<id>/payments         record a payment;  DELETE repairs/<id>/payments/<journal id>
GET       payment-methods               the BANKS rows a payment can use
"""

import json
from typing import Any

from django.db import DatabaseError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from autoservice import repairs, tokens
from autoservice.quotes import QuoteError
from autoservice.registry import DEFAULT_LIMIT, MAX_LIMIT
from autoservice.views import _int, error, ok, token_required

FILTERS = ("status", "mode", "plate", "org", "q")
NOT_FOUND = "Засварын карт олдсонгүй."


def _body(request: HttpRequest) -> dict[str, Any] | None:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _user(request: HttpRequest) -> str:
    u: tokens.TokenUser = request.autoservice_user  # type: ignore[attr-defined]
    return u.username


def _refused(e: QuoteError) -> JsonResponse:
    return error(409 if isinstance(e, repairs.RepairLocked) else 400, str(e))


def _run(action: Any) -> HttpResponse:
    """Run `action` in one transaction; a refusal (ours or the database's) rolls everything back."""
    try:
        with transaction.atomic():
            return action()  # type: ignore[no-any-return]
    except QuoteError as e:  # RepairError too: the checks shared with quotes raise the base class
        return _refused(e)
    except DatabaseError as e:
        return _refused(repairs.db_error(e))


def _full(pk: int, status: int = 200) -> HttpResponse:
    card = repairs.load(pk)
    if card is None:
        return error(404, NOT_FOUND)
    response = ok(card)
    response.status_code = status
    return response


def _list(request: HttpRequest) -> HttpResponse:
    limit = _int(request.GET.get("limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int(request.GET.get("offset"), 0, 0, 10_000_000)
    filters = {k: request.GET.get(k, "").strip() for k in FILTERS if request.GET.get(k, "").strip()}
    rows, total = repairs.listing(filters, limit, offset)
    return ok({"count": total, "limit": limit, "offset": offset, "results": rows})


def _save(request: HttpRequest, pk: int | None) -> HttpResponse:
    body = _body(request)
    if body is None:
        return error(400, "JSON биш хүсэлт байна.")

    def action() -> HttpResponse:
        data = repairs.parse(body)
        if pk is None:
            return _full(repairs.create(data, _user(request)), 201)
        return _full(pk) if repairs.replace(pk, data, _user(request)) else error(404, NOT_FOUND)

    return _run(action)


@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def repair_list(request: HttpRequest) -> HttpResponse:
    return _list(request) if request.method == "GET" else _save(request, None)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@token_required
def repair_detail(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method == "GET":
        return _full(pk)
    if request.method == "PUT":
        return _save(request, pk)
    return _run(lambda: HttpResponse(status=204) if repairs.delete(pk) else error(404, NOT_FOUND))


@csrf_exempt
@require_POST
@token_required
def repair_start(request: HttpRequest, pk: int) -> HttpResponse:
    return _run(lambda: _full(pk) if repairs.start(pk) else error(404, NOT_FOUND))


@csrf_exempt
@require_POST
@token_required
def repair_finish(request: HttpRequest, pk: int) -> HttpResponse:
    body = _body(request) or {}

    def action() -> HttpResponse:
        when = repairs._when(body["date_out"]) if body.get("date_out") else None
        return _full(pk) if repairs.finish(pk, when) else error(404, NOT_FOUND)

    return _run(action)


@csrf_exempt
@require_POST
@token_required
def repair_pay(request: HttpRequest, pk: int) -> HttpResponse:
    body = _body(request)
    if body is None:
        return error(400, "JSON биш хүсэлт байна.")
    return _run(lambda: (repairs.pay(pk, body, _user(request)), _full(pk, 201))[1])


@csrf_exempt
@require_http_methods(["DELETE"])
@token_required
def repair_payment(request: HttpRequest, pk: int, journal_id: int) -> HttpResponse:
    return _run(
        lambda: HttpResponse(status=204) if repairs.remove_payment(pk, journal_id) else error(404, "Төлбөр олдсонгүй.")
    )


@require_GET
@token_required
def payment_methods(request: HttpRequest) -> JsonResponse:
    return ok({"results": repairs.banks()})
