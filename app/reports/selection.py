"""Which people a bulk action (export, print, copy, checklist) may act on. Every bulk action goes through `pick`, which
re-runs the report for the user, so a person the report would not show them can never be acted on."""

from collections.abc import Collection
from dataclasses import dataclass, replace
from typing import Any

from accounts.models import User
from django.http import HttpRequest, QueryDict

from reports.filters import Filters, parse_filters
from reports.table import Cell, Table, build_table
from reports.types import Report

MAX_PEOPLE = 500  # one bulk action covers at most this many people; above it the action is refused, never truncated

NO_PERSON = "Энэ тайланд хүн сонгох боломжгүй."
NOTHING_PICKED = "Ядаж нэг хүнийг сонгоно уу."
MAX_ID_LENGTH = 12  # the longest id text read; the same bound config.params.id_param uses


def too_many() -> str:
    """The refusal for more people than one action covers; the live MAX_PEOPLE, read at the time of the call."""
    return f"Нэг удаад дээд тал нь {MAX_PEOPLE} хүнийг сонгож болно."


def not_allowed(count: int) -> str:
    """The refusal when every posted id is one the user may not act on."""
    return f"Сонгосон {count} хүн энэ тайланд харагдахгүй байна. Дахин сонгоно уу."


LAYOUT_KEYS = ("lby", "lby2", "lval", "lchart", "lmonth")  # the layout's own address parameters, dropped with "layout*"


class SelectionError(Exception):
    """A bulk action that cannot run; `message` is Mongolian and shown to the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Picked:
    table: Table  # the full report as this user sees it, before any subset
    ids: tuple[int, ...]  # the employee ids to act on, in report order
    dropped: int  # posted ids the user may not act on (outside scope, hidden by a filter or rule)


def _table_filters(query: str) -> Filters:
    """The report's filters from the posted address, with the layout forced to the table."""
    get = QueryDict(query.lstrip("?"), mutable=True)
    for key in list(get.keys()):
        if key.startswith("layout") or key in LAYOUT_KEYS:
            del get[key]
    return replace(parse_filters(get), layout="", lby="", lby2="", lval="", lchart="")


def _posted_ids(raw: list[str]) -> list[int]:
    """The distinct ids posted, in the order posted. Anything that is not a plain decimal number of at most
    MAX_ID_LENGTH digits is ignored, so no text can make int() fail."""
    found: dict[int, None] = {}
    for text in raw:
        if text.isascii() and text.isdecimal() and len(text) <= MAX_ID_LENGTH:
            found.setdefault(int(text), None)
    return list(found)


def pick(request: HttpRequest, user: User, report: Report) -> Picked:
    """The people the user may act on, from the posted report address (`query`), `all` ("1" for every matching
    person) or the ticked `ids`. Raises SelectionError when nothing is picked or the cap is passed."""
    if report.person is None:
        raise SelectionError(NO_PERSON)
    table = build_table(report, user, _table_filters(request.POST.get("query", "")))
    allowed = list(dict.fromkeys(report.person(row) for row in table.rows))  # report order, no repeats
    if request.POST.get("all") == "1":
        ids, dropped = allowed, 0
    else:
        posted = _posted_ids(request.POST.getlist("ids"))
        if len(posted) > MAX_PEOPLE:  # refused on the raw count, so a huge forged list is never intersected
            raise SelectionError(too_many())
        wanted, allowed_set = set(posted), set(allowed)  # each built once
        ids = [pk for pk in allowed if pk in wanted]
        dropped = sum(1 for pk in posted if pk not in allowed_set)
        if not ids and dropped:
            raise SelectionError(not_allowed(dropped))
    if not ids:
        raise SelectionError(NOTHING_PICKED)
    if len(ids) > MAX_PEOPLE:
        raise SelectionError(too_many())
    return Picked(table=table, ids=tuple(ids), dropped=dropped)


def subset(table: Table, report: Report, ids: Collection[int]) -> Table:
    """A copy of the table with only these people, in the same order. Totals are not redone: the footer is None."""
    chosen = set(ids)
    groups: list[tuple[str, list[list[Cell]]]] = []
    for label, group in table.groups:
        kept = [row for row in group if row and row[0].person in chosen]
        if kept or label == "":  # an ungrouped table keeps its one (possibly empty) group
            groups.append((label, kept))
    rows: list[Any] = [row for row in table.rows if report.person is not None and report.person(row) in chosen]
    return replace(table, groups=groups, count=len(rows), rows=rows, footer=None)
