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
from employees.models import CompanySettings
from reports import registry
from reports.filters import MAX_AGE, Filters, describe, parse_filters, to_query
from reports.rules import MAX_RULES, MAX_TEXT, MAX_VALUE, Group, Rule, check_value, dump_rules, parse_rules, restrict
from reports.staff_list import REPORT
from reports.table import allowed_columns, build_table, usable_filters

from assistant.columns import offered_columns
from assistant.matching import covers, word_forms
from assistant.plan import Condition, Part
from assistant.resolver import LOOKUP_WHERE, LOOKUPS, Candidate, resolve
from assistant.words import GROUP_OPTIONS, FilterWords, offered_words

MAX_BUTTONS = 5
MAX_ECHO = 80  # the user's own words, echoed in a line, are cut to this length
MAX_BASE = 4000  # the previous answer's address query is cut to this many characters (rules text is percent-encoded)

_NUMBER = re.compile(r"[0-9]{1,12}")
_AGE_PARAMS = frozenset({"age_from", "age_to"})
_NOT_OFFERED = "Ийм шүүлтүүр байхгүй эсвэл танд нээлттэй биш."
_NO_VALUE = "“{value}” гэсэн утга олдсонгүй."
_UNMAPPED = "“{word}” — ийм шүүлтүүр алга."
_TOO_MANY = "Нөхцөл хэт олон тул сүүлийн {n}-ийг хэрэглээгүй."  # needs native read
_PREV_DROPPED = "Өмнөх нөхцөл хэрэглэгдсэнгүй."  # needs native read
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
    params: tuple[tuple[str, str], ...]  # (query parameter, value), applied, in registry order; "rules" comes last
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


def _covered(word: str, used: Sequence[str]) -> bool:
    """Whether the word lies inside one of the used phrases: every word of it matches a word of the phrase, with case
    endings folded (matching.covers). One direction only: a phrase inside the word does not cover it. An empty or
    blank word, or an empty phrase, never covers anything."""
    forms = word_forms(word)
    return any(covers(forms, phrase) for phrase in used)


def _settle_conditions(
    user: User, conditions: Sequence[Condition]
) -> tuple[list[Rule], list[str], list[str], list[str]]:
    """The conditions the staff table can apply, as rules, and a not-applied line for each one it cannot. A hidden
    column and a column that does not exist give the same line, so the answer never shows that a hidden one exists.
    Also returns the phrases of the applied conditions, and the phrases of the dropped ones whose line names them."""
    columns = {c.key: c for c in offered_columns(user)}
    applied: list[Rule] = []
    lines: list[str] = []
    applied_phrases: list[str] = []
    dropped_phrases: list[str] = []
    for condition in conditions:
        column = columns.get(condition.column)
        if column is None or condition.op not in column.ops:
            lines.append(_UNMAPPED.format(word=_echo(condition.phrase or condition.column)))
            dropped_phrases.append(condition.phrase)
            continue
        value = condition.value
        if condition.op == "next_days" and not value.strip():
            value = str(CompanySettings.get().soon_days)
        # A blank value is refused too (an empty «contains» would match every row), except where none is needed.
        needs_none = condition.op in ("empty", "filled")
        too_long = len(value) > MAX_VALUE  # a longer value would make the whole rules text unreadable later
        if too_long or (not value.strip() and not needs_none) or not check_value(condition.op, value, column.kind):
            lines.append(_NO_VALUE.format(value=_echo(condition.value)))
            continue
        applied.append(Rule(condition.column, condition.op, value))
        applied_phrases.append(condition.phrase)
    return applied, lines, applied_phrases, dropped_phrases


def _carried_rules(user: User, base: Mapping[str, str] | None) -> tuple[list[Rule], list[str]]:
    """The earlier answer's conditions that carry over, and a not-applied line for each one that does not check out.
    Only a flat AND group of rules is carried (checked before the permission cut, so a nested group is never carried,
    even a hidden one). The earlier address is untrusted: each rule is checked as a new condition would be."""
    text = (base or {}).get("rules", "")
    if not text:
        return [], []
    group = parse_rules(text)
    if group is None or group.op != "and" or not all(isinstance(node, Rule) for node in group.items):
        return [], [_PREV_DROPPED]  # unreadable, too long, an OR group or a nested group: nothing is carried
    columns = {c.key: c for c in offered_columns(user)}
    checked = restrict(group, set(columns))  # hidden and unknown columns are dropped without a line
    if checked is None:
        return [], []
    carried: list[Rule] = []
    lines: list[str] = []
    for node in checked.items:
        if not isinstance(node, Rule):
            continue
        column = columns[node.column]
        needs_none = node.op in ("empty", "filled")
        if (
            node.op not in column.ops
            or len(node.value) > MAX_VALUE
            or (not node.value.strip() and not needs_none)
            or not check_value(node.op, node.value, column.kind)
        ):
            lines.append(_NO_VALUE.format(value=_echo(node.value)))
            continue
        carried.append(node)
    return carried, lines


def _merge_rules(carried: Sequence[Rule], applied: Sequence[Rule]) -> list[Rule]:
    """The carried conditions, then the new ones. A new condition on a column that has carried conditions removes all
    of them and takes the place of the first; two new conditions on one column are both kept. Other new conditions
    are appended."""
    new_columns = {rule.column for rule in applied}
    carried_columns = {rule.column for rule in carried}
    merged: list[Rule] = []
    placed: set[str] = set()
    for rule in carried:
        if rule.column not in new_columns:
            merged.append(rule)
        elif rule.column not in placed:
            merged.extend(r for r in applied if r.column == rule.column)
            placed.add(rule.column)
    merged.extend(r for r in applied if r.column not in carried_columns)
    return merged


def settle(
    user: User,
    parts: Sequence[Part],
    base: Mapping[str, str] | None = None,
    unmapped: Sequence[str] = (),
    conditions: Sequence[Condition] = (),
) -> Settled:
    """Apply the parts to the base query for this user, then the conditions (each becomes a rule or a not-applied line).
    Stops at the first ambiguous lookup; never raises."""
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
    used: list[str] = []  # the phrases of the parts applied (a value stored, or an ask started)
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
                used.append(part.phrase)
            elif found.status == "several":
                used.append(part.phrase)
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
            used.append(part.phrase)

    applied, condition_lines, applied_phrases, dropped_phrases = _settle_conditions(user, conditions)
    used.extend(applied_phrases)
    used.extend(dropped_phrases)  # a dropped condition's own line already names its phrase
    not_applied.extend(_UNMAPPED.format(word=_echo(word)) for word in unmapped if not _covered(word, used))
    not_applied.extend(condition_lines)
    carried, carried_lines = _carried_rules(user, base)
    not_applied.extend(carried_lines)
    merged = _merge_rules(carried, applied)
    dropped = max(0, len(merged) - MAX_RULES)  # the newest rules go first: the cap and the text limit share one line
    merged = merged[:MAX_RULES]
    while merged and len(dump_rules(Group("and", tuple(merged)))) > MAX_TEXT:
        merged.pop()
        dropped += 1
    if dropped:
        not_applied.append(_TOO_MANY.format(n=dropped))
    params = [(w.param, values[w.param]) for w in ordered if w.param in values]
    if merged:
        params.append(("rules", dump_rules(Group("and", tuple(merged)))))
    return Settled(
        params=tuple(params),
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
    """The settled parameters read the way the table reads its address, then cut to what this user may use. The rules
    keep only the columns this user may see (usable_filters does not restrict them)."""
    f = usable_filters(REPORT, user, parse_filters(QueryDict(urlencode(params))))
    allowed = {c.key for c in allowed_columns(REPORT, user)}
    return replace(f, rules=dump_rules(restrict(parse_rules(f.rules), allowed)))


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
    conditions: Sequence[Condition] = (),
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
    settled = settle(user, parts, base=_base_of(base_query), unmapped=unmapped, conditions=conditions)
    labels = {c.key: c.label for c in allowed_columns(REPORT, user)}
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
            chips=tuple(describe(f, REPORT.filters, labels=labels)),
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
        chips=tuple(describe(table.filters, REPORT.filters, labels=labels)),
        not_applied=settled.not_applied + chart_lines,
        ask=None,
        rest=(),
        chart_kind=chart_kind,
        chart_by=chart_by,
        group=group,
    )
