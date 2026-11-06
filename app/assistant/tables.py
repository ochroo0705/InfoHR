"""Settles the parts a question's table answer asks for into the staff table's filters. This is the only place where
the model's strings become query values: a fixed value must be a listed value, a date must be an ISO date, a number
must be digits, and a lookup phrase goes through the resolver so that only a real row's id is stored.

Two steps, both strict: `settle` decides which parts apply and which are asked about or listed as not applied.
The table answer (later in this module) turns the settled filters into the page's query and count."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from urllib.parse import urlencode

from accounts.models import User
from config.params import date_param, id_param
from django.core.exceptions import TooManyFieldsSent
from django.http import QueryDict
from django.urls import reverse
from reports import registry
from reports.filters import MAX_AGE, Filters, describe, parse_filters, to_query
from reports.staff_list import REPORT
from reports.table import allowed_columns, build_table, usable_filters

from assistant.plan import Part
from assistant.resolver import LOOKUP_WHERE, LOOKUPS, Candidate, resolve
from assistant.words import GROUP_OPTIONS, FilterWords, offered_words

MAX_BUTTONS = 5
MAX_ECHO = 80  # the user's own words, echoed in a line, are cut to this length
MAX_BASE = 2000  # the previous answer's address query is cut to this many characters

_NUMBER = re.compile(r"[0-9]{1,12}")
_AGE_PARAMS = frozenset({"age_from", "age_to"})
_NOT_OFFERED = "Ийм шүүлтүүр байхгүй эсвэл танд нээлттэй биш."
_NO_VALUE = "“{value}” гэсэн утга олдсонгүй."
_UNMAPPED = "“{word}” — ийм шүүлтүүр алга."
_NO_TABLE = "Ажилтны хүснэгтийг харах эрх алга."
_NO_CHART = "График хийх боломжгүй: “{by}”."
_NO_GROUP = "Ийм бүлэглэлт байхгүй эсвэл танд нээлттэй биш: “{by}”."
_NO_CHART_BY = "График хэлтэс, салбар эсвэл албан тушаалаар бүлэглэж хийгдэнэ: аль нэгийг нь нэрлэнэ үү."


@dataclass(frozen=True)
class Ask:
    param: str
    label: str  # «Хэлтэс»
    candidates: tuple[Candidate, ...]  # at most MAX_BUTTONS
    more: bool  # there were more candidates than buttons


@dataclass(frozen=True)
class Settled:
    params: tuple[tuple[str, str], ...]  # (query parameter, value), applied, in registry order
    ask: Ask | None  # the first ambiguous part
    rest: tuple[Part, ...]  # parts after the ambiguous one, still to settle
    not_applied: tuple[str, ...]  # Mongolian lines


def _echo(text: str) -> str:
    """The user's own words as they go into a line: cut to MAX_ECHO characters, with «…» when cut."""
    return text if len(text) <= MAX_ECHO else text[:MAX_ECHO] + "…"


def _plain(word: FilterWords, value: str) -> str | None:
    """The stored value of a fixed, date or number filter, or None when the filter does not accept the value."""
    if word.kind == "fixed":
        return value if any(v.value == value for v in word.values) else None
    if word.kind == "date":
        parsed = date_param(value)
        return parsed.isoformat() if parsed is not None else None
    if word.kind == "number":
        if not _NUMBER.fullmatch(value):
            return None
        if word.param in _AGE_PARAMS and int(value) > MAX_AGE:
            return None
        return value
    return None


def _known_id(param: str, value: str) -> str | None:
    """A lookup value already given as an id (from an earlier query), when a row with that id exists."""
    number = id_param(value)
    if number is None:
        return None
    where = LOOKUP_WHERE.get(param, {})
    exists = LOOKUPS[param]._default_manager.filter(pk=number, **where).exists()
    return str(number) if exists else None


def settle(
    user: User,
    parts: Sequence[Part],
    base: Mapping[str, str] | None = None,
    unmapped: Sequence[str] = (),
) -> Settled:
    """Apply the parts to the base query for this user. Stops at the first ambiguous lookup; never raises."""
    ordered = offered_words(user)  # the registry order; `params` comes out in this order
    words = {w.param: w for w in ordered}
    values: dict[str, str] = {}
    # The base is an earlier query: keep only what this user may use, and only values that still hold.
    for param, value in (base or {}).items():
        word = words.get(param)
        if word is None:
            continue
        clean = _known_id(param, value) if word.kind == "lookup" else _plain(word, value)
        if clean is not None:
            values[param] = clean

    not_applied: list[str] = []
    ask: Ask | None = None
    rest: tuple[Part, ...] = ()
    for index, part in enumerate(parts):
        word = words.get(part.param)
        if word is None:
            not_applied.append(_NOT_OFFERED)
            continue
        if word.kind == "lookup":
            found = resolve(word.param, part.value)
            if found.status == "one":
                values[word.param] = str(found.candidates[0].id)
            elif found.status == "several":
                ask = Ask(
                    param=word.param,
                    label=word.label,
                    candidates=found.candidates[:MAX_BUTTONS],
                    more=len(found.candidates) > MAX_BUTTONS,
                )
                rest = tuple(parts[index + 1 :])
                break
            else:
                not_applied.append(_NO_VALUE.format(value=_echo(part.value)))
            continue
        clean = _plain(word, part.value)
        if clean is None:
            # A rejected new part leaves an earlier value of the same filter in place, and the line says so.
            not_applied.append(_NO_VALUE.format(value=_echo(part.value)))
        else:
            values[word.param] = clean

    not_applied.extend(_UNMAPPED.format(word=_echo(word)) for word in unmapped)
    return Settled(
        params=tuple((w.param, values[w.param]) for w in ordered if w.param in values),
        ask=ask,
        rest=rest,
        not_applied=tuple(not_applied),
    )


@dataclass(frozen=True)
class TableAnswer:
    # "list": the full answer, count and link are final. "ask": chips, url and query are PARTIAL (only the parts
    # settled before the ambiguous one); they must not be presented as the answer. "denied": the user may not open
    # the table; count, url and query are empty.
    status: str  # "list" | "ask" | "denied"
    want: str  # "list" | "count" | "chart"
    query: str  # the settled filter query (as to_query makes it) for the link, prev and pick
    url: str  # the staff table address with `query`
    count: int | None  # None while status == "ask" or "denied"
    chips: tuple[str, ...]  # the filter lines as the table shows them
    not_applied: tuple[str, ...]
    ask: Ask | None
    rest: tuple[Part, ...]
    chart_kind: str
    chart_by: str
    group: str = ""  # the grouping the table link carries (a group option the user may see), or ""


def can_open_table(user: User) -> bool:
    """Whether the user may open the staff table: the report's own rights, as reports.registry.can_open checks them."""
    return registry.can_open(user, REPORT)


def _filters_of(user: User, params: Sequence[tuple[str, str]]) -> Filters:
    """The settled parameters read the way the table reads its address, then cut to what this user may use."""
    return usable_filters(REPORT, user, parse_filters(QueryDict(urlencode(params))))


def _query(f: Filters) -> str:
    """The address query that opens the staff table on the same rows, with the default columns, grouping and sort."""
    return to_query(replace(f, columns=(), group="", sort=""))


def _base_of(base_query: str) -> dict[str, str]:
    """The earlier answer's address read as parameters. Untrusted and never raises: a too-long or malformed address
    gives no base at all (QueryDict raises TooManyFieldsSent for very many fields)."""
    if not base_query:
        return {}
    try:
        return QueryDict(base_query[:MAX_BASE]).dict()
    except (TooManyFieldsSent, ValueError, UnicodeError):
        return {}


def _address(query: str) -> str:
    path = reverse("reports:report", args=[REPORT.key])
    return f"{path}?{query}" if query else path


def _chart_lines(want: str, chart_by: str) -> tuple[str, ...]:
    """The not-applied line for a chart asked for a grouping the staff table does not offer. Empty when no chart is
    asked for or when the grouping is offered. A chart asked for with no grouping the table offers gets its own line,
    so the request is never dropped silently."""
    if want != "chart" or chart_by in GROUP_OPTIONS:
        return ()
    if not chart_by:
        return (_NO_CHART_BY,)
    return (_NO_CHART.format(by=_echo(chart_by)),)


def _may_group(user: User, by: str) -> bool:
    """Whether the staff table may be grouped by this column for the user: a group option whose column they may see."""
    return by in GROUP_OPTIONS and any(c.key == by for c in allowed_columns(REPORT, user))


def table_answer(
    user: User,
    parts: Sequence[Part],
    *,
    base_query: str = "",
    unmapped: Sequence[str] = (),
    want: str = "list",
    chart_kind: str = "",
    chart_by: str = "",
    group_by: str = "",
) -> TableAnswer:
    """The staff table answer for these parts: the settled filters, their count and chips. `base_query` is the address
    of an earlier answer (untrusted): only the parameters this user may use survive. A user who may not open the
    table gets no count and no link."""
    if not can_open_table(user):
        return TableAnswer(
            status="denied",
            want=want,
            query="",
            url="",
            count=None,
            chips=(),
            not_applied=(_NO_TABLE,),
            ask=None,
            rest=(),
            chart_kind=chart_kind,
            chart_by=chart_by,
        )
    settled = settle(user, parts, base=_base_of(base_query), unmapped=unmapped)
    chart_lines = _chart_lines(want, chart_by)
    group = ""
    if group_by and want == "list":
        if _may_group(user, group_by):
            group = group_by
        else:
            chart_lines += (_NO_GROUP.format(by=_echo(group_by)),)
    elif want == "chart" and _may_group(user, chart_by):
        group = chart_by  # the table link groups the way the chart does (a bad chart grouping already has its own line)
    if settled.ask is not None:
        f = _filters_of(user, settled.params)
        query = _query(f)
        return TableAnswer(
            status="ask",
            want=want,
            query=query,
            url=_address(query),
            count=None,
            chips=tuple(describe(f, REPORT.filters)),
            not_applied=settled.not_applied + chart_lines,
            ask=settled.ask,
            rest=settled.rest,
            chart_kind=chart_kind,
            chart_by=chart_by,
        )
    table = build_table(REPORT, user, _filters_of(user, settled.params))
    query = _query(table.filters)
    return TableAnswer(
        status="list",
        want=want,
        query=query,
        url=_address(to_query(replace(table.filters, columns=(), sort="", group=group)) if group else query),
        count=table.count,
        chips=tuple(describe(table.filters, REPORT.filters)),
        not_applied=settled.not_applied + chart_lines,
        ask=None,
        rest=(),
        chart_kind=chart_kind,
        chart_by=chart_by,
        group=group,
    )
