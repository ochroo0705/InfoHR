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
    HttpResponseForbidden,
    QueryDict,
)
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from employees.palette import PersonHit
from reports.filters import parse_filters, to_query
from reports.staff_list import REPORT
from reports.table import usable_filters

from assistant.actions import field_address, leave_address
from assistant.chart_data import ChartData, chart_data, chart_possible
from assistant.chart_xlsx import chart_workbook
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


def _readable(raw: str) -> bool:
    """An address query the chart can read: short enough and a query string that parses."""
    if len(raw) > MAX_PREV:
        return False
    try:
        QueryDict(raw)
    except (TooManyFieldsSent, ValueError, UnicodeError):
        return False
    return True


def _chart_url(user: User, ta: TableAnswer) -> str:
    """The «График харах →» address of a list answer that asks for a chart and has chart data, else empty. Only then the
    link is drawn: a count or a plain list has none, and neither has a chart the user may not see."""
    if ta.status != "list" or ta.want != "chart":
        return ""
    if not chart_possible(user, ta.chart_kind, ta.chart_by):
        return ""
    return reverse("assistant:chart") + "?" + urlencode({"query": ta.query, "kind": ta.chart_kind, "by": ta.chart_by})


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


def _open_chart(raw: str) -> tuple[str, str] | None:
    """The kind and grouping of the chart open beside the chat, sent as «kind|by». Untrusted: anything that is not a
    known kind with a grouping the staff table offers is ignored."""
    kind, _, by = raw.partition("|")
    if kind in CHART_KINDS and by in REPORT.group_options:
        return kind, by
    return None


def _card(request: HttpRequest, result: Answer, chart_open: bool = False) -> HttpResponse:
    """The answer card. A table answer adds its pick buttons (`choices`) for the card's template."""
    context: dict[str, object] = {"result": result, **_person_context(result), **_action_context(result)}
    if result.table is not None:
        context["choices"] = _choices(result.table)
        user = request.user
        assert isinstance(user, User)
        context["chart_url"] = _chart_url(user, result.table)
        # A chart question asked while a chart is open updates that chart in place (the pane reads data-chart-auto).
        context["chart_auto"] = chart_open and bool(context["chart_url"])
    return render(request, "assistant/_answer.html", context)


def _percent(count: int, total: int) -> int:
    """The share of the total in whole percent, halves up (as the chart's hover text rounds)."""
    return int(count * 100 / total + 0.5) if total else 0


def _table_address(user: User, query: str, by: str) -> str:
    """The staff table on the chart's rows, grouped by the chart's column (the table reads this address)."""
    f = usable_filters(REPORT, user, parse_filters(QueryDict(query)))
    params = to_query(replace(f, columns=(), sort="", group=by))
    path = reverse("reports:report", args=[REPORT.key])
    return f"{path}?{params}" if params else path


def _chart_context(user: User, query: str, data: ChartData) -> dict[str, object]:
    """The pop-up's numbers: the JSON the chart draws from, the text list rows and the link to the staff table."""
    return {
        "data": data,
        "payload": {
            "kind": data.kind,
            "labels": list(data.labels),
            "counts": list(data.counts),
            "total": data.total,
        },
        "rows": [
            {"label": label, "count": count, "pct": _percent(count, data.total)}
            for label, count in zip(data.labels, data.counts, strict=True)
        ],
        "table_url": _table_address(user, query, data.by),
        "state": {"query": query, "kind": data.kind, "by": data.by},
        "xlsx_url": reverse("assistant:chart_xlsx")
        + "?"
        + urlencode({"query": query, "kind": data.kind, "by": data.by}),
    }


@login_required
@require_GET
def chart(request: HttpRequest) -> HttpResponse:
    """The chart pop-up for a staff table answer: one bar or pie chart of the people in the query, counted by one group
    column. 400 for an unknown kind or column or an unreadable query; 403 when the user may not see that column or the
    table. Only the chart's own numbers leave the server; the chart library loads from our own static files."""
    kind = request.GET.get("kind", "")
    by = request.GET.get("by", "")
    query = request.GET.get("query", "")
    if kind not in CHART_KINDS or by not in REPORT.group_options or not _readable(query):
        return HttpResponseBadRequest()
    user = request.user
    assert isinstance(user, User)
    data = chart_data(user, query, kind, by)
    if data is None:
        return HttpResponseForbidden()
    return render(request, "assistant/_chart_modal.html", _chart_context(user, query, data))


@login_required
@require_GET
def chart_xlsx(request: HttpRequest) -> HttpResponse:
    """The same chart as an Excel file with a native chart object. Same checks as the chart pane: 400 for an unknown
    kind or column or an unreadable query, 403 when the user may not see that column or the table."""
    kind = request.GET.get("kind", "")
    by = request.GET.get("by", "")
    query = request.GET.get("query", "")
    if kind not in CHART_KINDS or by not in REPORT.group_options or not _readable(query):
        return HttpResponseBadRequest()
    user = request.user
    assert isinstance(user, User)
    data = chart_data(user, query, kind, by)
    if data is None:
        return HttpResponseForbidden()
    response = HttpResponse(
        chart_workbook(data),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="assistant-chart.xlsx"'
    return response


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
    open_chart = _open_chart(request.POST.get("chart", ""))
    result = answer(request.user, question, timezone.localdate(), provider, previous, open_chart)
    return _card(request, result, chart_open=open_chart is not None)


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
