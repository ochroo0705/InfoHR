"""The Today page's «Удахгүй болох» lines: the report setups that say what is coming up («дөхсөн» starter templates and
saved views with a «next_days» rule), each with its row count for this viewer now. Nothing is stored or sent."""

from collections.abc import Iterator
from dataclasses import dataclass

from accounts.models import User
from django.http import QueryDict
from django.urls import reverse

from reports import registry, views
from reports import rules as rules_mod
from reports.filters import parse_filters
from reports.starter import resolved_query
from reports.table import build_table
from reports.types import Report

MAX_TILES = 8  # the Today page shows at most this many lines


@dataclass(frozen=True)
class Tile:
    name: str  # the template's or the saved view's name
    report: str  # the report's title
    count: int  # the rows the setup matches for this user, now
    url: str  # the report's address with the setup


def _has_next_days(node: rules_mod.Rule | rules_mod.Group) -> bool:
    if isinstance(node, rules_mod.Rule):
        return node.op == "next_days"
    return any(_has_next_days(item) for item in node.items)


def uses_next_days(rules_text: str) -> bool:
    """True when the rule tree (address text) holds a «next_days» rule at any depth."""
    tree = rules_mod.parse_rules(rules_text)
    return tree is not None and _has_next_days(tree)


def _candidates(user: User) -> Iterator[tuple[Report, str, str, bool]]:
    """(report, name, stored query, is a saved view) in the order the page shows them: the «дөхсөн» templates first,
    then the saved views with a «next_days» rule, by report key and name."""
    reports = [r for r in registry.REPORTS.values() if registry.can_open(user, r)]
    for report in reports:
        for template in report.templates:
            if template.soon_column and views._template_allowed(user, report, template):
                yield report, template.name, resolved_query(template), False
    for report in sorted(reports, key=lambda r: r.key):
        for view in views._visible_views(user, report.key):
            # cheap pre-filter on the stored text; cleaning only removes rules, so tiles() re-checks the cleaned query
            if uses_next_days(parse_filters(QueryDict(view.query)).rules):
                yield report, view.name, view.query, True


def tiles(user: User) -> list[Tile]:
    if not user.has_perm("reports.view_reports"):
        return []
    found: list[Tile] = []
    for report, name, stored, is_view in _candidates(user):
        if len(found) == MAX_TILES:
            break
        query = views._viewer_query(user, report, stored)
        if not query:  # every rule vanished for this viewer
            continue
        # a saved view still says «coming up» only if its next_days rule survives cleaning for this viewer
        if is_view and not uses_next_days(parse_filters(QueryDict(query)).rules):
            continue
        table = build_table(report, user, parse_filters(QueryDict(query)))
        url = views._view_url(reverse("reports:report", args=[report.key]), query)
        found.append(Tile(name=name, report=report.title, count=table.count, url=url))
    return found
