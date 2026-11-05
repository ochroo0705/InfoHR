"""The help assistant's views: the ask view (one question in, one answer card out, htmx, posted from the Ctrl+K palette)
and the pick view (a row chosen from a table answer's buttons, settled without the model or a log row)."""

import json
from urllib.parse import urlencode

from accounts.models import User
from config.params import id_param
from django.contrib.auth.decorators import login_required
from django.core.exceptions import TooManyFieldsSent
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest, QueryDict
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from assistant.models import Outcome
from assistant.people import PEOPLE_SHOWN
from assistant.plan import Part
from assistant.prompt import CHART_KINDS, WANTS
from assistant.providers import get_provider
from assistant.resolver import LOOKUP_WHERE, LOOKUPS
from assistant.services import Answer, answer
from assistant.tables import TableAnswer, can_open_table, table_answer

MAX_PREV = 2000  # the earlier answer's address query (prev, or a pick's query) is ignored above this length
MAX_REST = 12  # the parts still to settle after a pick, as the plan allows
MAX_VALUE = 200  # one value of a rest part is cut above this length
MAX_BY = 60  # the chart grouping key is cut to this length (as the plan cuts it)


def _person_context(result: Answer) -> dict[str, object]:
    """The card's people links for a person-bound answer. One person opens the page (`person_one`); several are listed
    (`person_rows`, at most PEOPLE_SHOWN, `person_more` when there are more). The job line skips empty parts."""
    entry = result.entry
    if result.outcome != Outcome.ANSWERED or entry is None or not entry.person:
        return {}
    rows = [
        {
            "hit": hit,
            "url": entry.person_url(hit.employee.pk),
            "job": " · ".join(part for part in (hit.position, hit.department) if part),
        }
        for hit in result.people[:PEOPLE_SHOWN]
    ]
    if len(result.people) == 1:
        return {"person_one": rows[0]}
    return {"person_rows": rows, "person_more": len(result.people) > PEOPLE_SHOWN}


def _clean_query(raw: str) -> str:
    """An address query sent back by the page: kept only when it is short enough and parses as a query string.
    Anything else is ignored (it is never trusted; the table keeps only what this user may use anyway)."""
    if len(raw) > MAX_PREV:
        return ""
    try:
        QueryDict(raw)
    except (TooManyFieldsSent, ValueError, UnicodeError):
        return ""
    return raw


def _choices(ta: TableAnswer) -> list[dict[str, str]]:
    """The buttons of an ask: one per candidate. The body the pick view reads is encoded here, not in the template."""
    if ta.status != "ask" or ta.ask is None:
        return []
    rest = json.dumps([[part.param, part.value] for part in ta.rest], ensure_ascii=False)
    return [
        {
            "name": candidate.name,
            "body": urlencode(
                {
                    "query": ta.query,
                    "param": ta.ask.param,
                    "id": candidate.id,
                    "rest": rest,
                    "want": ta.want,
                    "chart_kind": ta.chart_kind,
                    "chart_by": ta.chart_by,
                }
            ),
        }
        for candidate in ta.ask.candidates
    ]


def _rest(raw: str) -> list[Part] | None:
    """The parts still to settle: a JSON list of [param, value] pairs, at most MAX_REST. None if the shape is wrong."""
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):  # deeply nested input is a bad request, not a server error
        return None
    if not isinstance(data, list) or len(data) > MAX_REST:
        return None
    parts: list[Part] = []
    for item in data:
        if not (
            isinstance(item, list)
            and len(item) == 2
            and all(isinstance(value, str) and len(value) <= MAX_VALUE for value in item)
        ):
            return None
        parts.append(Part(param=item[0], value=item[1]))
    return parts


def _card(request: HttpRequest, result: Answer) -> HttpResponse:
    """The answer card. A table answer adds its pick buttons (`choices`) for the card's template."""
    context: dict[str, object] = {"result": result, **_person_context(result)}
    if result.table is not None:
        context["choices"] = _choices(result.table)
    return render(request, "assistant/_answer.html", context)


@login_required
@require_POST
def ask(request: HttpRequest) -> HttpResponse:
    question = request.POST.get("q", "").strip()
    if not question:
        return HttpResponseBadRequest()
    provider = get_provider()
    if provider is None:
        raise Http404
    assert isinstance(request.user, User)
    previous = _clean_query(request.POST.get("prev", ""))
    result = answer(request.user, question, timezone.localdate(), provider, previous)
    return _card(request, result)


@login_required
@require_POST
def pick(request: HttpRequest) -> HttpResponse:
    """A candidate chosen from an ambiguous table answer: the query gets the chosen row's id, the parts still to settle
    are settled, and the same card is returned. No model call and no log row."""
    user = request.user
    assert isinstance(user, User)
    param = request.POST.get("param", "")
    if param not in LOOKUPS:
        return HttpResponseBadRequest()
    number = id_param(request.POST.get("id", ""))
    if number is None:
        return HttpResponseBadRequest()
    rest = _rest(request.POST.get("rest", "[]"))
    if rest is None:
        return HttpResponseBadRequest()
    # The id must be a real row only for a user who may open the table: a user who may not gets the same denied card
    # for any well-formed id, so a 400 never reveals which ids exist.
    if (
        can_open_table(user)
        and not LOOKUPS[param]._default_manager.filter(pk=number, **LOOKUP_WHERE.get(param, {})).exists()
    ):
        return HttpResponseBadRequest()
    settled = _clean_query(request.POST.get("query", ""))
    base = "&".join(part for part in (settled, urlencode({param: number})) if part)
    want = request.POST.get("want", "")
    chart_kind = request.POST.get("chart_kind", "")
    ta = table_answer(
        user,
        rest,
        base_query=base,
        want=want if want in WANTS else "list",
        chart_kind=chart_kind if chart_kind in CHART_KINDS else "",
        chart_by=request.POST.get("chart_by", "")[:MAX_BY],
    )
    return _card(request, Answer(outcome=Outcome.TABLE, entry=None, also=None, lead="", table=ta))
