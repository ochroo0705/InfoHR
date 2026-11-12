"""The help assistant's views: the ask view (one question in, one answer card out, htmx, posted from the Ctrl+K palette)
and the pick view (a row chosen from a table answer's buttons, settled without the model or a log row)."""

import json
from collections.abc import Callable
from dataclasses import replace
from urllib.parse import urlencode

from accounts.models import User
from config.params import id_param
from django.contrib.auth.decorators import login_required
from django.core.exceptions import TooManyFieldsSent
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    JsonResponse,
    QueryDict,
)
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from employees.palette import PersonHit
from reports.filters import parse_filters, to_query
from reports.layouts import offered_layouts
from reports.staff_list import REPORT
from reports.table import allowed_columns, usable_filters

from assistant.actions import field_address, leave_address
from assistant.models import HelpQuestion, Outcome, VerifiedQuery
from assistant.people import PEOPLE_SHOWN
from assistant.plan import Part
from assistant.prompt import CHART_KINDS, WANTS
from assistant.providers import get_provider
from assistant.resolver import LOOKUP_WHERE, LOOKUPS
from assistant.services import Answer, answer
from assistant.tables import MAX_BASE, TableAnswer, can_open_table, table_answer

# The earlier answer's address query (prev, or a pick's query) is ignored above this length. It is the same cap as the
# one tables.py applies to a base query: a percent-encoded rules value makes the query longer than a plain one.
MAX_PREV = MAX_BASE
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


def _job(hit: PersonHit) -> str:
    """The position and department of a person, joined; empty parts are skipped."""
    return " · ".join(part for part in (hit.position, hit.department) if part)


def _action_rows(people: tuple[PersonHit, ...], address: Callable[[int], str]) -> dict[str, object]:
    """The rows of a pick: one link per person, each to its own address. Nothing is opened by a pick."""
    rows = [{"hit": hit, "url": address(hit.employee.pk), "job": _job(hit)} for hit in people[:PEOPLE_SHOWN]]
    return {"action_rows": rows, "action_more": len(people) > PEOPLE_SHOWN}


def _action_context(result: Answer) -> dict[str, object]:
    """The action card's people. One person (a field value, or a leave form that names one) is `action_person`; a pick
    lists its people as `action_rows`. The field's value and the form's link are read from the answer itself."""
    if result.outcome != Outcome.ACTION:
        return {}
    if result.field is not None:
        field = result.field
        if field.status in ("value", "empty"):
            return {"action_person": {"hit": field.people[0], "job": _job(field.people[0])}}
        if field.status == "pick":
            return _action_rows(field.people, lambda pk: field_address(pk, field.field_key))
        return {}
    leave = result.leave
    if leave is None:
        return {}
    if leave.status == "pick":
        return _action_rows(leave.people, lambda pk: leave_address(pk, leave.shared))
    if leave.people:
        return {"action_person": {"hit": leave.people[0], "job": _job(leave.people[0])}}
    return {}


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


def _chart(user: User, ta: TableAnswer) -> dict[str, str] | None:
    """The chart button of a list answer that asks for a chart: the staff report's own chart layout on the answer's
    filters (`url`), with the grouping column's label and the chart type's name for the description. None for a count
    or a plain list, for a grouping the user may not see, and for a user who is not offered the chart layout."""
    if ta.status != "list" or ta.want != "chart" or ta.chart_kind not in CHART_KINDS:
        return None
    column = next((c for c in allowed_columns(REPORT, user) if c.key == ta.chart_by), None)
    if column is None or column.key not in REPORT.group_options or "chart" not in offered_layouts(REPORT, user):
        return None
    pie = ta.chart_kind == "pie"
    f = usable_filters(REPORT, user, parse_filters(QueryDict(ta.query)))
    params = to_query(
        replace(f, columns=(), sort="", group="", layout="chart", lby=column.key, lchart="donut" if pie else "")
    )
    return {
        "url": f"{reverse('reports:report', args=[REPORT.key])}?{params}",
        "label": column.label,
        "kind": "дугуй" if pie else "багана",
    }


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
    """The answer card. A table answer adds its pick buttons (`choices`) and its chart button (`chart`) for the card's
    template. A governed SQL answer adds `workspace_ok`: the viewer may open it in the workspace (the card's button)."""
    context: dict[str, object] = {"result": result, **_person_context(result), **_action_context(result)}
    if result.table is not None:
        context["choices"] = _choices(result.table)
        user = request.user
        assert isinstance(user, User)
        context["chart"] = _chart(user, result.table)
    if result.outcome == Outcome.SQL:
        from assistant.ws_views import can_use_workspace  # imported here: ws_views loads the workspace service layer

        context["workspace_ok"] = can_use_workspace(request.user)  # fails closed; never raises for a non-User
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


@login_required
@require_POST
def sql_verify(request: HttpRequest) -> JsonResponse:
    """The asker marks their own governed SQL answer as correct: one proposed VerifiedQuery per source question.

    Only the asker, only an answer with outcome SQL and a stored SQL, and only SQL that still passes the checker for
    the asker's catalogue. A second mark for the same answer changes nothing. Every refusal is {"ok": false}."""
    from hr_sql.catalogue import catalogue_for
    from sqlcore.check import CheckError, check_sql

    user = request.user
    assert isinstance(user, User)
    raw = request.POST.get("question_id", "")
    if not raw.isdecimal():
        return JsonResponse({"ok": False})
    question = HelpQuestion.objects.filter(pk=int(raw), user=user, outcome=Outcome.SQL).exclude(sql="").first()
    if question is None:
        return JsonResponse({"ok": False})
    if VerifiedQuery.objects.filter(source=question).exists():
        return JsonResponse({"ok": True})
    try:
        checked = check_sql(question.sql, catalogue_for(user))
    except CheckError:
        return JsonResponse({"ok": False})
    VerifiedQuery.objects.create(
        question=question.question[:300],
        sql=checked.sql,
        views=",".join(sorted(checked.views))[:200],
        source=question,
        proposed_by=user,
    )
    return JsonResponse({"ok": True})
