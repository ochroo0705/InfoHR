"""Checks for the accuracy set: whether two filter queries mean the same, how a table case's expected query is read
against the database, and whether a plan passes a table case. Writes nothing to the database."""

import calendar
import re
from dataclasses import dataclass, replace
from datetime import date
from urllib.parse import parse_qsl, urlencode

from accounts.models import User
from django.http import QueryDict
from reports.filters import parse_filters, to_query

from assistant.evalset import TableCase
from assistant.plan import Plan
from assistant.resolver import LOOKUP_WHERE, LOOKUPS
from assistant.tables import settle

_PAIR = re.compile(r"([a-z_]+)([=~])(.*)", re.DOTALL)


def _canonical(query: str) -> list[tuple[str, str]]:
    """The query as the filters read it: defaults left out, columns, grouping and sort dropped, pairs sorted."""
    f = replace(parse_filters(QueryDict(query)), columns=(), group="", sort="")
    return sorted(parse_qsl(to_query(f), keep_blank_values=True))


def same_filters(a: str, b: str) -> bool:
    """True when the two filter queries settle to the same filters. The order of the pairs does not matter, and an
    omitted default (state=working) equals the explicit default."""
    return _canonical(a) == _canonical(b)


def _month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def expected_pairs(expected: str, today: date) -> list[tuple[str, str, bool]]:
    """The (parameter, value, by_name) items of an expected query. `by_name` is True for `param~Name`. The month
    placeholders are filled from `today`."""
    text = expected.format(month_start=today.replace(day=1).isoformat(), month_end=_month_end(today).isoformat())
    pairs: list[tuple[str, str, bool]] = []
    for item in text.split("&"):
        if not item:
            continue
        match = _PAIR.fullmatch(item)
        if match is None:
            raise ValueError(f"not a filter: {item}")
        pairs.append((match.group(1), match.group(3), match.group(2) == "~"))
    return pairs


def expected_query(expected: str, today: date) -> str:
    """The expected query as the staff table makes it: each `param~Name` becomes the id of the one row named exactly
    `Name`. Raises ValueError when no single row has that name, or the parameter is not a lookup."""
    pairs: list[tuple[str, str]] = []
    for param, value, by_name in expected_pairs(expected, today):
        if by_name:
            if param not in LOOKUPS:
                raise ValueError(f"{param} is not a lookup")
            where = LOOKUP_WHERE.get(param, {})
            ids = list(LOOKUPS[param]._default_manager.filter(name=value, **where).values_list("pk", flat=True)[:2])
            if len(ids) != 1:
                raise ValueError(f"no single {param} row named «{value}»")
            value = str(ids[0])
        pairs.append((param, value))
    query = to_query(parse_filters(QueryDict(urlencode(pairs))))
    kept = set(parse_qsl(query, keep_blank_values=True))
    for param, value in pairs:
        # A pair the table drops would weaken the case silently (both sides would drop it), so it is a mistake here.
        # state=working is the one default that to_query leaves out, and it is written on purpose.
        if (param, value) not in kept and (param, value) != ("state", "working"):
            raise ValueError(f"{param}={value} is not a filter the staff table keeps")
    return query


@dataclass(frozen=True)
class TableResult:
    passed: bool
    got: str  # the settled query, "-" for no filter, or what was asked about or missing


def check_table(user: User, case: TableCase, plan: Plan, today: date) -> TableResult:
    """Whether the plan passes the table case for this user. The plan's parts are settled exactly as the service
    settles them (tables.settle); an ask passes only when the case expects an ask on the same lookup."""
    if plan.tool == "entry":
        return TableResult(passed=False, got="an entry answer, not a table")
    # A "none" answer (no table asked) passes only a case marked none_ok (the hostile case, which must not show a
    # table). Any other case expects a table, so a refusal fails it, even when the expected filter is empty.
    if plan.tool == "none" and not case.none_ok:
        return TableResult(passed=False, got="no table (none)")
    parts = plan.parts if plan.tool == "staff_table" else ()
    unmapped = plan.unmapped if plan.tool == "staff_table" else ()
    settled = settle(user, parts, unmapped=unmapped)
    if settled.ask is not None:
        return TableResult(passed=case.ask == settled.ask.param, got=f"asks {settled.ask.param}")
    query = to_query(parse_filters(QueryDict(urlencode(settled.params))))
    got = query or "-"
    if case.ask:
        return TableResult(passed=False, got=got)
    try:
        want = expected_query(case.expected, today)
    except ValueError as exc:
        return TableResult(passed=False, got=f"expected: {exc}")
    passed = same_filters(query, want)
    if case.unapplied:
        passed = passed and bool(settled.not_applied)
    return TableResult(passed=passed, got=got)
