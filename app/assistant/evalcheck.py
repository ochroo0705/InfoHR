"""Checks for the accuracy set: whether two filter queries mean the same, how a table case's expected query is read
against the database, and whether a plan passes a table case. Writes nothing to the database."""

import calendar
import re
from dataclasses import dataclass, replace
from datetime import date
from urllib.parse import parse_qsl, urlencode

from accounts.models import User
from django.http import QueryDict
from employees.models import CompanySettings
from reports.filters import parse_filters, to_query
from reports.rules import Group, Rule, dump_rules

from assistant.evalset import ActionCase, TableCase
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


def condition_rules(conditions: tuple[tuple[str, str, str], ...]) -> tuple[Rule, ...]:
    """The expected conditions as rules. «{soon_days}» becomes the company's «дөхсөн» days."""
    rules: list[Rule] = []
    for column, op, value in conditions:
        if "{soon_days}" in value:
            value = value.replace("{soon_days}", str(CompanySettings.get().soon_days))
        rules.append(Rule(column, op, value))
    return tuple(rules)


def expected_query(expected: str, today: date, conditions: tuple[tuple[str, str, str], ...] = ()) -> str:
    """The expected query as the staff table makes it: each `param~Name` becomes the id of the one row named exactly
    `Name`, and the conditions become the `rules` pair. Raises ValueError when no single row has that name, or the
    parameter is not a lookup."""
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
    if conditions:
        pairs.append(("rules", dump_rules(Group("and", condition_rules(conditions)))))
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
    conditions = plan.conditions if plan.tool == "staff_table" else ()
    # The earlier answer's filters, as the service passes them: the table keeps only what this user may use.
    base = QueryDict(case.previous).dict() if case.previous else None
    settled = settle(user, parts, base=base, unmapped=unmapped, conditions=conditions)
    if settled.ask is not None:
        return TableResult(passed=case.ask == settled.ask.param, got=f"asks {settled.ask.param}")
    query = to_query(parse_filters(QueryDict(urlencode(settled.params))))
    got = query or "-"
    if case.ask:
        return TableResult(passed=False, got=got)
    try:
        want = expected_query(case.expected, today, case.conditions)
    except ValueError as exc:
        return TableResult(passed=False, got=f"expected: {exc}")
    passed = same_filters(query, want)
    if case.unapplied:
        passed = passed and bool(settled.not_applied)
    if case.chart:
        got = (
            f"{got}; chart {plan.chart_kind or '-'}:{plan.chart_by or '-'}"
            if plan.want == "chart"
            else f"{got}; no chart"
        )
        passed = passed and _chart_matches(plan, case.chart)
    return TableResult(passed=passed, got=got)


def _chart_matches(plan: Plan, chart: str) -> bool:
    """Whether the plan asks for a chart of the kind and grouping the case names ("kind:by", by may be empty)."""
    kind, _, by = chart.partition(":")
    return plan.want == "chart" and plan.chart_kind == kind and plan.chart_by == by


@dataclass(frozen=True)
class ActionResult:
    passed: bool
    got: str  # the plan's tool and field, and what is wrong with a leave date


def _iso_or_empty(value: str) -> bool:
    """True when the value is "" (the plan left it out) or a real ISO date."""
    if not value:
        return True
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def check_action(case: ActionCase, plan: Plan) -> ActionResult:
    """Whether the plan picks the case's tool and field. A leave case also needs its start and end, when given, to
    parse as ISO dates. Writes nothing; the eval only reports the result."""
    got = f"{plan.tool} {plan.field}".strip()
    if plan.tool != case.tool or plan.field != case.field:
        return ActionResult(passed=False, got=got)
    if case.leave and not (_iso_or_empty(plan.start) and _iso_or_empty(plan.end)):
        return ActionResult(passed=False, got=f"{got}; a date is not ISO")
    return ActionResult(passed=True, got=got)
