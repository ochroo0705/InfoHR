"""Turns a report's rows into the table the page, print and Excel show: visible columns only, sorted and grouped."""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any

from accounts.models import User
from employees.access import visible_employees

from reports.filters import FILTER_FIELDS, Filters, without_today
from reports.types import Column, Report

FILTER_NAMES = (  # every filter name a report may declare (Report.filters)
    "state",
    "as_of",
    "period",
    "branch",
    "department",
    "position",
    "gender",
    "change",
    "reason",
    "order_type",
    "discipline",
    "employee",
    "leave_type",
    "leave_state",
    "absence_type",
    "age_range",
    "attribute",
    "contact_type",
    "year",
    "tr_type",
    "quarter",
    "present_type",
)
EMPTY_DEPARTMENT = "Хэлтэсгүй"  # the empty group of a department column
EMPTY_GROUP = "—"  # the empty group of any other column


@dataclass(frozen=True)
class Cell:
    value: object  # the raw value; the template formats dates and blanks None
    href: str = ""  # link target, empty when the cell is not a link
    cls: str = ""  # alignment classes of the column (see column_classes)
    money: bool = False  # the column is an amount, formatted by the template


@dataclass
class Table:
    columns: list[Column]  # the columns shown, in order
    groups: list[tuple[str, list[list[Cell]]]]  # one ("", rows) group when not grouped; empty group last
    count: int
    filters: Filters  # the cleaned filters actually used, so links and print show the same thing
    shows_count: bool = True  # whether screen, print and Excel end with «Нийт: N»


def allowed_columns(report: Report, user: User) -> list[Column]:
    """The columns the user may see: no permission needed, or the permission is held."""
    return [c for c in report.columns if not c.needs or user.has_perm(c.needs)]


def offered_filters(report: Report, user: User) -> list[str]:
    """The filter names the user may use: the report's filters less those that need a permission the user lacks."""
    return [
        name for name in report.filters if not report.filter_needs.get(name) or user.has_perm(report.filter_needs[name])
    ]


def usable_filters(report: Report, user: User, filters: Filters) -> Filters:
    """The filters as this user may use them: a filter the report does not declare, or the user may not use, is reset to
    its default, and an employee the user may not see is dropped, so a typed id never shows another person's name or
    rows and a link never carries a filter the page does not show."""
    offered = set(offered_filters(report, user))
    default = Filters()
    usable = replace(
        filters,
        **{
            field: getattr(default, field)
            for name in FILTER_NAMES
            if name not in offered
            for field in FILTER_FIELDS.get(name, (name,))
        },
    )
    if usable.employee is not None and not visible_employees(user).filter(pk=usable.employee).exists():
        usable = replace(usable, employee=None)
    return usable


def shown_keys(report: Report, user: User, filters: Filters) -> list[str]:
    """The column keys the table shows, in order: those asked for that the user may see, else the defaults."""
    by_key = {c.key for c in allowed_columns(report, user)}
    keys = [k for k in dict.fromkeys(filters.columns) if k in by_key]
    return keys or [k for k in report.default_columns if k in by_key]


def column_classes(columns: list[Column]) -> list[str]:
    """Numbers are right-aligned; the column after a number gets room so the headers do not touch (UI_RULES §4)."""
    classes: list[str] = []
    after_number = False
    for c in columns:
        classes.append("text-right" if c.numeric else ("pl-6" if after_number else ""))
        after_number = c.numeric
    return classes


def _text(value: object) -> str:
    """The display text of a value, used to group rows."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _sort_key(value: object) -> tuple[int, Any]:
    """A total order over mixed types: numbers, then dates, then text, then anything else. Never raises."""
    if isinstance(value, (int, float, Decimal)):  # bool is an int
        return (0, value)
    if isinstance(value, date):
        return (1, value.isoformat())
    if isinstance(value, str):
        return (2, value.casefold())
    return (3, str(value).casefold())


def _sorted_rows(rows: list[Any], column: Column, descending: bool) -> list[Any]:
    """Rows ordered by the column's raw value; rows with no value always go last, in both directions."""
    keyed = [(column.value(row), row) for row in rows]
    present = sorted((p for p in keyed if p[0] is not None), key=lambda p: _sort_key(p[0]), reverse=descending)
    return [row for _, row in present] + [row for value, row in keyed if value is None]


def build_table(report: Report, user: User, filters: Filters) -> Table:
    """The table for these filters as this user may see it. Anything the user may not see is dropped, never shown."""
    filters = without_today(usable_filters(report, user, filters))
    by_key = {c.key: c for c in allowed_columns(report, user)}
    keys = shown_keys(report, user, filters)
    shown = [by_key[k] for k in keys]
    classes = column_classes(shown)

    group_col = by_key.get(filters.group) if filters.group in report.group_options else None

    descending = filters.sort.startswith("-")
    sort_name = filters.sort[1:] if descending else filters.sort
    sort_col = next((c for c in shown if c.key == sort_name), None)

    rows = report.rows(user, replace(filters, columns=tuple(keys)))  # the rows get the same shown columns
    if sort_col is not None:
        rows = _sorted_rows(rows, sort_col, descending)

    def cells(row: Any) -> list[Cell]:
        return [
            Cell(value=c.value(row), href=c.href(row) if c.href is not None else "", cls=cls, money=c.money)
            for c, cls in zip(shown, classes, strict=True)
        ]

    groups: list[tuple[str, list[list[Cell]]]]
    if group_col is None:
        groups = [("", [cells(row) for row in rows])]
    else:
        buckets: dict[str, list[list[Cell]]] = {}
        for row in rows:
            buckets.setdefault(_text(group_col.value(row)), []).append(cells(row))
        groups = [(text, buckets[text]) for text in sorted((t for t in buckets if t), key=str.casefold)]
        if "" in buckets:
            empty_label = EMPTY_DEPARTMENT if group_col.label == "Хэлтэс" else EMPTY_GROUP
            groups.append((empty_label, buckets[""]))

    used = replace(
        filters,
        columns=tuple(c.key for c in shown),
        group=group_col.key if group_col is not None else "",
        sort=(("-" if descending else "") + sort_name) if sort_col is not None else "",
    )
    return Table(columns=shown, groups=groups, count=len(rows), filters=used, shows_count=report.shows_count)
