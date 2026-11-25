"""The report page's filter bar, request-free: which filters are drawn and their ✕ addresses, the «Шүүлтүүр нэмэх»
picker, the column-filter chips, the cleaned `add` names, and every option list behind the drawn dropdowns.

The Django report page builds its filter-bar context from `filter_bar()`; the React API reads `FilterBar.options`
(plain (value, label) pairs). Nothing here reads a request: the caller passes the QueryDict, and `user` decides what
is offered (a column the user may not see, a person the user may not see, are never listed)."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlencode

from accounts.models import User
from django.http import QueryDict
from django.utils import timezone
from employees import access, listing
from macs.models import (
    AbsenceType,
    Branch,
    ContactType,
    Department,
    DisciplineType,
    FiredReason,
    LeaveTypeRow,
    Position,
    PresentType,
)

from reports.filters import (
    ATTRIBUTES,
    EMPTYPES,
    GENDERS,
    LEAVE_STATES,
    MOVEMENT_KINDS,
    NO_WORKING_STATE,
    ORDER_TYPES,
    STATES,
    TRAINING_TYPES,
    Filters,
    period_of,
    this_quarter,
    to_query,
)
from reports.page_rules import (
    added_names,
    address,
    builtin_panels,
    column_filter_panels,
    group_text,
    secondary_filters,
)
from reports.table import Table, allowed_columns, offered_column_filters, offered_filters
from reports.types import Column, Report


@dataclass(frozen=True)
class BarItem:
    """A filter drawn in the bar: its name, and its ✕ address ("" when it is always drawn)."""

    name: str
    remove: str


@dataclass(frozen=True)
class PickerEntry:
    """One line of the «Шүүлтүүр нэмэх» menu: its label, its address, and the heading printed above it ("" if none)."""

    label: str
    href: str
    heading: str


@dataclass(frozen=True)
class ColumnChip:
    """A shown column filter: its values, the options its select offers, and the address that removes it."""

    name: str
    label: str
    kind: str  # "code", "choice", "date", "number"
    params: list[str]  # the query parameters in order: the name, or "<name>_from" and "<name>_to" for a range
    options: list[tuple[str, str]]  # (value, label) for a code or choice filter; empty otherwise
    values: list[str]  # the current values, one per parameter ("" when unset)
    remove_href: str


@dataclass(frozen=True)
class FilterOptions:
    """The option lists behind the drawn built-in filters, as (value, label) pairs in the view's order. A list is
    read only when its filter is drawn; the others are empty. The scalars are the values the bar shows now."""

    states: list[tuple[str, str]]
    emptypes: list[tuple[str, str]]
    genders: list[tuple[str, str]]
    branches: list[tuple[str, str]]
    departments: list[tuple[str, str]]
    positions: list[tuple[str, str]]
    period_from: date
    period_to: date
    change_kinds: list[tuple[str, str]]
    order_types: list[tuple[str, str]]
    leave_states: list[tuple[str, str]]
    leave_types: list[tuple[str, str]]
    absence_types: list[tuple[str, str]]
    attributes: list[tuple[str, str]]
    contact_types: list[tuple[str, str]]
    year: int | None
    training_types: list[tuple[str, str]]
    quarter: int | None
    present_types: list[tuple[str, str]]
    reasons: list[tuple[str, str]]
    discipline_types: list[tuple[str, str]]
    people: list[tuple[str, str]]
    no_working_state: list[tuple[str, str]]
    group_choices: list[tuple[str, str]]
    group_text: str


@dataclass(frozen=True)
class FilterBar:
    items: list[BarItem]  # the filters drawn now, in report order
    picker: list[PickerEntry]  # the «Шүүлтүүр нэмэх» menu: built-in filters first, then column filters
    column_chips: list[ColumnChip]  # the column filters drawn now
    adds: list[str]  # the `add` names this user may use (picker chips without a value yet; never stored)
    clear_url: str  # the «Цэвэрлэх» address
    columns_query: str  # the query the «Багана», «Шүүлтүүр» and «Хэлбэр» pop-ups carry
    options: FilterOptions
    # what the Django template reads, keyed as the template names it: the querysets and dicts it iterates, the
    # picker and chips in the shapes it unpacks. Each queryset is the same object the options were read from.
    context: dict[str, Any] = field(default_factory=dict)


def bar_adds(request_get: QueryDict, user: User, report: Report) -> list[str]:
    """The picker's `add` names this user may use: the same list filter_bar() returns as FilterBar.adds, computed
    without the option lists (no queries for the drawn dropdowns). A batch answer that skips the bar takes it from
    here."""
    column_names = offered_column_filters(report, user)
    secondary = secondary_filters(offered_filters(report, user))
    return added_names(request_get, [*column_names, *secondary])


def filter_bar(request_get: QueryDict, path: str, user: User, report: Report, table: Table, plain: bool) -> FilterBar:
    """The filter bar of a report page for this address and user. `table` is the built table (its `filters` are the
    cleaned filters the bar shows); `plain` is True for a report with saved views (an empty address reads
    view=plain)."""
    f = table.filters
    column_names = offered_column_filters(report, user)
    names = offered_filters(report, user)  # the filter bar draws these, in the report's order
    secondary = secondary_filters(names)
    adds = added_names(request_get, [*column_names, *secondary])
    column_choices, chips = column_filter_panels(path, f, column_names, adds, plain)
    shown_secondary, builtin_choices, removes = builtin_panels(path, f, secondary, adds, plain)

    drawn = [n for n in names if n not in secondary or n in shown_secondary]
    drawn_set = set(drawn)  # the option lists are read only for these

    # one «Шүүлтүүр нэмэх» menu: the folded built-in filters first, then the column filters
    picker = [
        PickerEntry(label, href, "Шүүлтүүр" if i == 0 else "") for i, (_n, label, href) in enumerate(builtin_choices)
    ]
    picker += [
        PickerEntry(label, href, "Баганаар" if i == 0 and builtin_choices else "")
        for i, (_n, label, href) in enumerate(column_choices)
    ]
    items = [BarItem(name=n, remove=removes.get(n, "")) for n in drawn]
    column_chips = [
        ColumnChip(
            name=chip["name"],
            label=chip["label"],
            kind=chip["kind"],
            params=chip["params"],
            options=chip["options"],
            values=chip["values"],
            remove_href=chip["remove_href"],
        )
        for chip in chips
    ]
    columns_query = "&".join(part for part in (to_query(f), urlencode([("add", n) for n in adds])) if part)

    # the querysets and dicts: built lazily, read only when the template draws their filter (as before)
    branches = Branch.objects.order_by("name")
    departments = Department.objects.order_by("name")
    positions = Position.objects.order_by("name")
    leave_types = LeaveTypeRow.objects.order_by("name") if "leave_type" in names else []
    absence_types = AbsenceType.objects.order_by("name") if "absence_type" in names else []
    contact_types = ContactType.objects.order_by("name") if "contact_type" in names else []
    present_types = PresentType.objects.order_by("name") if "present_type" in names else []
    reasons = FiredReason.objects.order_by("name") if "reason" in names else []
    discipline_types = DisciplineType.objects.order_by("name") if "discipline" in names else []
    people = (
        access.visible_employees(user).exclude(emptype__in=listing.NEVER_WORKED).order_by("family_name", "given_name")
        if "employee" in names
        else []
    )
    period_start, period_end = period_of(f)
    year = (f.year or timezone.localdate().year) if "year" in names else None
    quarter = (f.quarter or this_quarter()) if "quarter" in names else None
    # the «Бүлэглэх» select replaces the column picker's grouping, so only reports without the picker offer it
    allowed = allowed_columns(report, user)
    grouping: list[Column] = [c for c in allowed if c.key in report.group_options]
    group_choices = [] if report.picks_columns else grouping
    grouping_label = group_text(f.group, grouping)

    def pairs(rows: Any, value: Any, label: Any) -> list[tuple[str, str]]:
        return [(str(value(row)), label(row)) for row in rows]

    def named(row: Any) -> str:
        return row.name or "—"  # a row with no name reads a dash, as the template's default filter does

    def choices(source: dict[Any, str]) -> list[tuple[str, str]]:
        return [(str(key), label) for key, label in source.items()]

    def rows_of(name: str, qs: Any) -> list[tuple[str, str]]:
        return pairs(qs, lambda r: r.pk, named) if name in drawn_set else []

    options = FilterOptions(
        states=choices(STATES) if "state" in drawn_set else [],
        emptypes=choices(EMPTYPES) if "emptype" in drawn_set else [],
        genders=choices(GENDERS) if "gender" in drawn_set else [],
        branches=rows_of("branch", branches),
        departments=rows_of("department", departments),
        positions=rows_of("position", positions),
        period_from=period_start,
        period_to=period_end,
        change_kinds=choices(MOVEMENT_KINDS) if "change" in drawn_set else [],
        order_types=choices(ORDER_TYPES) if "order_type" in drawn_set else [],
        leave_states=choices(LEAVE_STATES) if "leave_state" in drawn_set else [],
        leave_types=rows_of("leave_type", leave_types),
        absence_types=rows_of("absence_type", absence_types),
        attributes=choices(ATTRIBUTES) if "attribute" in drawn_set else [],
        contact_types=rows_of("contact_type", contact_types),
        year=year,
        training_types=choices(TRAINING_TYPES) if "tr_type" in drawn_set else [],
        quarter=quarter,
        present_types=rows_of("present_type", present_types),
        reasons=rows_of("reason", reasons),
        discipline_types=rows_of("discipline", discipline_types),
        people=pairs(people, lambda p: p.pk, str) if "employee" in drawn_set else [],
        no_working_state=[(str(code), EMPTYPES.get(code, str(code))) for code in sorted(NO_WORKING_STATE)]
        if "emptype" in drawn_set
        else [],
        group_choices=[(c.key, c.label) for c in group_choices],
        group_text=grouping_label,
    )
    context: dict[str, Any] = {
        "filter_names": drawn,
        "secondary_filters": secondary,  # drawn with a ✕ (and a hidden `add`) when shown
        "filter_items": items,
        "filter_picker": [(e.label, e.href, e.heading) for e in picker],
        "column_filter_choices": column_choices,
        "active_column_filters": column_chips,
        "clear_url": address(path, Filters(), plain=plain),  # the filter bar's «Цэвэрлэх»
        "columns_query": columns_query,
        "states": STATES,
        "emptypes": EMPTYPES,
        "no_working_state": NO_WORKING_STATE,
        "genders": GENDERS,
        "branches": branches,
        "departments": departments,
        "positions": positions,
        "period_from": period_start,
        "period_to": period_end,
        "change_kinds": MOVEMENT_KINDS,
        "order_types": ORDER_TYPES,
        "leave_states": LEAVE_STATES,
        "leave_types": leave_types,
        "absence_types": absence_types,
        "attributes": ATTRIBUTES if "attribute" in names else {},
        "contact_types": contact_types,
        "year": year,
        "training_types": TRAINING_TYPES if "tr_type" in names else {},
        "quarter": quarter,
        "present_types": present_types,
        "reasons": reasons,
        "discipline_types": discipline_types,
        "people": people,
        "group_choices": group_choices,
        "group_text": grouping_label,
    }
    return FilterBar(
        items=items,
        picker=picker,
        column_chips=column_chips,
        adds=adds,
        clear_url=context["clear_url"],
        columns_query=columns_query,
        options=options,
        context=context,
    )
