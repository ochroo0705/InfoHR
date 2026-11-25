"""The «Багана сонгох», «Шүүлтүүр» and «Хэлбэр» pop-ups, request-free: each function answers the model its pop-up draws
from (the columns the user may see, the current values, and `keep`, the viewer's cleaned address minus the part the
pop-up owns, which the form keeps as hidden inputs). The Django views and the React API both call these, so a rule has
one home. Nothing here checks rights or reads a request: the caller passes the QueryDict, the viewer and the report,
and calls check_popup() first."""

from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import parse_qsl

from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.http import Http404, QueryDict

from reports import marks as marks_mod
from reports import registry
from reports import rules as rules_mod
from reports import totals as totals_mod
from reports.filters import Filters, parse_filters, to_query
from reports.kinds import KINDS
from reports.page_rules import added_names, group_text, offered_adds
from reports.services.page_head import _cleaned_for
from reports.table import allowed_columns, offered_filters, restricted_filters, shown_keys, usable_filters
from reports.types import Column, Report

# the colour names of the «Хэлбэр» pop-up, in the order the pop-up offers them
FORMAT_COLOURS = (("red", "Улаан"), ("amber", "Шар"), ("green", "Ногоон"), ("blue", "Цэнхэр"), ("grey", "Саарал"))
AGG_LABELS = {"sum": "Нийлбэр", "avg": "Дундаж", "min": "Хамгийн бага", "max": "Хамгийн их", "count": "Тоо"}
# the aggregates a column of each kind offers: a number all five, a date the three that mean something for dates
AGGS_BY_KIND = {
    "number": ("sum", "avg", "min", "max", "count"),
    "date": ("min", "max", "count"),
    "text": ("count",),
}


@dataclass(frozen=True)
class Pick:
    key: str
    label: str
    checked: bool  # the column is shown now


@dataclass(frozen=True)
class ColumnKind:
    key: str
    label: str
    kind: str  # "text", "number" or "date" (see _rule_kind)


@dataclass(frozen=True)
class OpOut:
    code: str
    label: str


@dataclass(frozen=True)
class ColourOut:
    key: str
    label: str
    classes: str  # the Tailwind classes the table paints a marked cell with (marks.COLOURS)


@dataclass(frozen=True)
class MarkOut:
    c: str  # column key
    o: str  # operator code
    v: str  # value
    k: str  # colour key


@dataclass(frozen=True)
class ColumnsModel:
    groups: list[tuple[str, list[Pick]]]  # (group title, its picks), in the order the columns come
    group_choices: list[Column]
    group: str
    group_text: str  # the label of a grouping with several keys, "" otherwise
    keep: list[tuple[str, str]]


@dataclass(frozen=True)
class RulesModel:
    columns: list[ColumnKind]
    ops: dict[str, list[OpOut]]
    rules: str  # the current rules as the compact JSON text (rules.dump_rules), "" for none
    keep: list[tuple[str, str]]


@dataclass(frozen=True)
class FormatModel:
    columns: list[ColumnKind]
    shown: list[str]  # the column keys the table shows now
    ops: dict[str, list[OpOut]]
    aggs: dict[str, tuple[str, ...]]
    agg_labels: dict[str, str]
    colours: list[ColourOut]
    totals: list[tuple[str, str]]  # (column key, aggregate)
    marks: list[MarkOut]
    pin: int
    keep: list[tuple[str, str]]


def check_popup(user: User, report: Report | None, *, needs: Literal["picks_columns", "shows_count"]) -> None:
    """The rights of a pop-up: 404 when the report is missing or has no such feature, else 403 when the user may not
    open it. A pop-up of a report without the feature is not there at all, so 404 comes first."""
    if report is None:
        raise Http404
    has_feature = report.picks_columns if needs == "picks_columns" else report.shows_count
    if not has_feature:
        raise Http404
    if not registry.can_open(user, report):
        raise PermissionDenied


def _rule_kind(column: Column) -> str:
    """The kind a pop-up can use without rows: the column's own kind, else number for amounts, else text."""
    if column.kind in KINDS:
        return column.kind
    return "number" if column.numeric or column.money else "text"


def _ops() -> dict[str, list[OpOut]]:
    return {
        kind: [OpOut(code=code, label=rules_mod.OP_LABELS[code]) for code in codes]
        for kind, codes in rules_mod.OPS.items()
    }


def _column_kinds(columns: list[Column]) -> list[ColumnKind]:
    return [ColumnKind(key=c.key, label=c.label, kind=_rule_kind(c)) for c in columns]


def _keep(get: QueryDict, user: User, report: Report, cleaned: Filters) -> list[tuple[str, str]]:
    """The address the pop-up's form keeps: `cleaned` as query pairs, then the `add` chips the viewer named."""
    offered = offered_adds(report, user, offered_filters(report, user))
    return parse_qsl(to_query(cleaned)) + [("add", name) for name in added_names(get, offered)]


def columns_model(get: QueryDict, user: User, report: Report) -> ColumnsModel:
    """The «Багана сонгох» pop-up: the columns the user may see (the shown ones ticked) and the grouping."""
    f = parse_filters(get)
    allowed = allowed_columns(report, user)
    shown = set(shown_keys(report, user, f))
    by_group: dict[str, list[Pick]] = {}
    for c in allowed:
        by_group.setdefault(c.group, []).append(Pick(key=c.key, label=c.label, checked=c.key in shown))
    group_choices = [c for c in allowed if c.key in report.group_options]
    # the viewer's cleaned address: a grouping key the viewer may not see is dropped, a visible multi-key group stays
    cleaned = _cleaned_for(user, report, f)
    return ColumnsModel(
        groups=list(by_group.items()),
        group_choices=group_choices,
        group=cleaned.group,
        group_text=group_text(cleaned.group, group_choices),
        # the hidden inputs carry this viewer's cleaned address, so a hidden column key never echoes back
        keep=_keep(get, user, report, replace(cleaned, columns=(), group="")),
    )


def rules_model(get: QueryDict, user: User, report: Report) -> RulesModel:
    """The «Шүүлтүүр» pop-up: the conditions the user may use and the current ones."""
    f = parse_filters(get)
    allowed = allowed_columns(report, user)
    current = rules_mod.restrict(rules_mod.parse_rules(f.rules), {c.key for c in allowed})
    return RulesModel(
        columns=_column_kinds(allowed),
        ops=_ops(),
        rules=rules_mod.dump_rules(current),
        keep=_keep(get, user, report, replace(_cleaned_for(user, report, f), rules="")),
    )


def format_model(get: QueryDict, user: User, report: Report) -> FormatModel:
    """The «Хэлбэр» pop-up: the footer totals, the pinned columns and the colour rules the user may use, and the current
    ones, as the table applies them: only the columns this user may see."""
    f = parse_filters(get)
    allowed = allowed_columns(report, user)
    current = restricted_filters(report, user, usable_filters(report, user, f))
    return FormatModel(
        columns=_column_kinds(allowed),
        shown=shown_keys(report, user, current),
        ops=_ops(),
        aggs=AGGS_BY_KIND,
        agg_labels=AGG_LABELS,
        colours=[ColourOut(key=name, label=label, classes=marks_mod.COLOURS[name]) for name, label in FORMAT_COLOURS],
        totals=list(totals_mod.parse_totals(current.totals)),
        marks=[MarkOut(c=m.column, o=m.rule_op, v=m.value, k=m.colour) for m in marks_mod.parse_marks(current.marks)],
        pin=current.pin,
        keep=_keep(get, user, report, replace(_cleaned_for(user, report, f), totals="", marks="", pin=0)),
    )
