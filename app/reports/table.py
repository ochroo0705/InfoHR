"""Turns a report's rows into the table the page, print and Excel show: visible columns only, sorted and grouped."""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.utils import timezone
from employees.access import visible_employees

from reports import layouts as layouts_mod
from reports import marks as marks_mod
from reports import rules as rules_mod
from reports import totals as totals_mod
from reports.column_filters import COLUMN_FILTERS, params_of
from reports.filters import FILTER_FIELDS, MAX_GROUP_KEYS, MAX_SORT_KEYS, Filters, without_today
from reports.kinds import column_kind
from reports.types import Column, Report

FILTER_NAMES = (  # every filter name a report may declare (Report.filters)
    "state",
    "as_of",
    "period",
    "branch",
    "department",
    "position",
    "gender",
    "emptype",
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
    mark: str = ""  # the CSS classes of the colour rule that passes for this cell, "" for none (set by build_table)
    sticky_left: str = ""  # the inline offset of a pinned column, e.g. "left: 12rem"; "" when not pinned
    person: int = 0  # the employee id of the row this cell is in (Report.person); 0 when the report has none

    @property
    def css(self) -> str:
        """The td's classes on the screen: alignment, colour and pinning."""
        return css_classes(self.cls, self.mark, self.sticky_left)


PIN_WIDTH_REM = 12  # the width of one pinned column, so the offsets of the pinned columns add up
# the classes of a pinned header or cell; the template comment in reports/_table.html lists them for Tailwind
STICKY = "sticky z-10 w-[12rem] min-w-[12rem] max-w-[12rem] truncate"


def pin_style(index: int, pin: int) -> str:
    """The inline left offset of the column at `index` (0-based) when the first `pin` columns are pinned, else ""."""
    if index >= pin:
        return ""
    return f"left: {PIN_WIDTH_REM * index}rem"


def css_classes(cls: str, mark: str, sticky_left: str) -> str:
    """The classes of a screen cell or header. A pinned cell with a colour keeps the colour's background instead of
    the surface one, so the two never fight over background-color."""
    if not sticky_left:
        return " ".join(part for part in (cls, mark) if part)
    background = "" if mark else "bg-surface"
    return " ".join(part for part in (cls, mark, STICKY, background) if part)


def _table_spec() -> layouts_mod.LayoutSpec:
    """The spec of a table with no other layout. The month is unused by the table and is a placeholder."""
    return layouts_mod.LayoutSpec(layout="table", by=None, by2=None, value=(None, "count"), chart="bar", month=date.min)


@dataclass
class Table:
    columns: list[Column]  # the columns shown, in order
    groups: list[tuple[str, list[list[Cell]]]]  # one ("", rows) group when not grouped; empty group last
    count: int
    filters: Filters  # the cleaned filters actually used, so links and print show the same thing
    shows_count: bool = True  # whether screen, print and Excel end with «Нийт: N»
    rules_text: str = ""  # the rules in words, for the screen and print; "" when none
    footer: list[Cell] | None = None  # the footer totals, one cell per shown column; None when there are none
    pin: int = 0  # how many leading columns stay fixed when scrolling sideways
    rows: list[Any] = field(default_factory=list)  # every filtered, sorted raw row, for the other layouts
    spec: layouts_mod.LayoutSpec = field(default_factory=_table_spec)  # the layout chosen and its columns


def allowed_columns(report: Report, user: User) -> list[Column]:
    """The columns the user may see: no permission needed, or the permission is held."""
    return [c for c in report.columns if not c.needs or user.has_perm(c.needs)]


def offered_filters(report: Report, user: User) -> list[str]:
    """The filter names the user may use: the report's filters less those that need a permission the user lacks."""
    return [
        name for name in report.filters if not report.filter_needs.get(name) or user.has_perm(report.filter_needs[name])
    ]


def offered_column_filters(report: Report, user: User) -> list[str]:
    """The column filter names the user may use: the report's own, whose column the user may see. A name that is not
    in COLUMN_FILTERS, or whose column the report does not have, is left out."""
    allowed = {c.key for c in allowed_columns(report, user)}
    return [name for name in report.column_filters if name in COLUMN_FILTERS and COLUMN_FILTERS[name].column in allowed]


def usable_filters(report: Report, user: User, filters: Filters) -> Filters:
    """The filters as this user may use them: a filter the report does not declare, or the user may not use, is reset to
    its default, and an employee the user may not see is dropped, so a typed id never shows another person's name or
    rows and a link never carries a filter the page does not show. Column filters the user may not use are dropped
    from `extra`; the rest keep their order."""
    offered = set(offered_filters(report, user))
    default = Filters()
    params = {p for name in offered_column_filters(report, user) for p in params_of(COLUMN_FILTERS[name])}
    usable = replace(
        filters,
        extra=tuple(pair for pair in filters.extra if pair[0] in params),
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


def _is_blank(value: object) -> bool:
    """A value with nothing to sort on: None, or text that is empty or only spaces. Other values are never blank."""
    return value is None or (isinstance(value, str) and not value.strip())


def _sorted_rows(rows: list[Any], column: Column, descending: bool) -> list[Any]:
    """Rows ordered by the column's raw value; blank rows (see _is_blank) always go last, in both directions."""
    keyed = [(column.value(row), row) for row in rows]
    present = sorted((p for p in keyed if not _is_blank(p[0])), key=lambda p: _sort_key(p[0]), reverse=descending)
    return [row for _, row in present] + [row for value, row in keyed if _is_blank(value)]


def _sort_spec(sort: str, by_key: dict[str, Column]) -> list[tuple[Column, bool]]:
    """The sort keys this user may use, in order, each with True when descending (a "-" prefix). A key that is not an
    allowed column is dropped, a repeated key is kept once, and at most MAX_SORT_KEYS are used."""
    spec: list[tuple[Column, bool]] = []
    seen: set[str] = set()
    for part in sort.split(","):
        descending = part.startswith("-")
        column = by_key.get(part[1:] if descending else part)
        if column is not None and column.key not in seen:
            seen.add(column.key)
            spec.append((column, descending))
    return spec[:MAX_SORT_KEYS]


def _group_cols(report: Report, by_key: dict[str, Column], group: str) -> list[Column]:
    """The group keys this user may use, in order: report group options the user may see, at most MAX_GROUP_KEYS."""
    cols: list[Column] = []
    for name in dict.fromkeys(group.split(",")):
        if name in report.group_options and name in by_key:
            cols.append(by_key[name])
    return cols[:MAX_GROUP_KEYS]


def _group_label(parts: tuple[str, ...], cols: list[Column]) -> str:
    """The heading of a group: each key's text joined with « › »; an empty part shows the placeholder of its column."""
    return " › ".join(
        part or (EMPTY_DEPARTMENT if col.label == "Хэлтэс" else EMPTY_GROUP)
        for part, col in zip(parts, cols, strict=True)
    )


def restricted_filters(report: Report, user: User, filters: Filters) -> Filters:
    """The filters with rules, totals and marks kept only on the columns this user may see. Used by the table, and by
    saved views (saved for the author, shown to each viewer), so a hidden column's rule never leaves this function."""
    allowed = {c.key for c in allowed_columns(report, user)}
    tree = rules_mod.restrict(rules_mod.parse_rules(filters.rules), allowed)
    totals = [pair for pair in totals_mod.parse_totals(filters.totals) if pair[0] in allowed]
    marks = [mark for mark in marks_mod.parse_marks(filters.marks) if mark.column in allowed]
    layout = layouts_mod.clean_params(report, user, filters)
    return replace(
        filters,
        rules=rules_mod.dump_rules(tree),
        totals=totals_mod.dump_totals(totals),
        marks=marks_mod.dump_marks(marks),
        layout=layout["layout"],
        lby=layout["lby"],
        lby2=layout["lby2"],
        lval=layout["lval"],
        lchart=layout["lchart"],
        lmonth=layout["lmonth"],
    )


FOOTER_LABEL = "Дүн"  # the footer's first cell when the first shown column has no total of its own


def _total_applies(column: Column, agg: str, rows: list[Any]) -> bool:
    """count works on any column; min and max on numbers or dates; sum and avg on numbers only (UI_RULES §4b)."""
    if agg == "count":
        return True
    kind = column_kind(column, rows)
    if agg in ("min", "max"):
        return kind in ("number", "date")
    return kind == "number"


def _footer(
    shown: list[Column], classes: list[str], totals: tuple[tuple[str, str], ...], rows: list[Any]
) -> list[Cell] | None:
    """One footer cell per shown column, over every filtered row. None when no total applies to a shown column."""
    wanted = dict(totals)  # parse_totals keeps one aggregate per column
    cells: list[Cell] = []
    applied: list[bool] = []
    for column, cls in zip(shown, classes, strict=True):
        agg = wanted.get(column.key)
        if agg is None or not _total_applies(column, agg, rows):
            cells.append(Cell(value=None, cls=cls))
            applied.append(False)
            continue
        value = totals_mod.aggregate([column.value(row) for row in rows], agg)
        money = column.money and agg != "count"
        cells.append(Cell(value=value, cls=cls, money=money))
        applied.append(True)
    if not any(applied):
        return None
    if not applied[0]:
        cells[0] = Cell(value=FOOTER_LABEL, cls=classes[0])
    return cells


def build_table(report: Report, user: User, filters: Filters) -> Table:
    """The table for these filters as this user may see it. Anything the user may not see is dropped, never shown."""
    filters = restricted_filters(report, user, without_today(usable_filters(report, user, filters)))
    by_key = {c.key: c for c in allowed_columns(report, user)}
    keys = shown_keys(report, user, filters)
    shown = [by_key[k] for k in keys]
    classes = column_classes(shown)

    # the filters are already restricted to the columns the user may see
    rule_tree = rules_mod.parse_rules(filters.rules)
    totals = totals_mod.parse_totals(filters.totals)
    marks = marks_mod.parse_marks(filters.marks)
    rule_keys = list(dict.fromkeys(rules_mod.rule_columns(rule_tree)))
    sort_cols = _sort_spec(filters.sort, by_key)
    group_cols = _group_cols(report, by_key, filters.group)
    # the layout needs no rows to choose its columns, so it is chosen before they load
    # the first choice, without rows, only decides which columns load; the final one (below) judges kinds by the rows
    spec = layouts_mod.resolve(report, user, filters)
    # rows load the shown columns first, then those only a rule, sort or group uses (a hidden column still filters, and
    # an allowed unshown column still sorts or groups). A total or colour on an unshown column is not applied, so it
    # loads nothing. A layout other than the table loads its own columns, and the requested value column too, since
    # its kind is only known from the loaded values (a hidden one still shows nothing).
    requested_value = filters.lval.partition(":")[0]
    layout_keys = (
        []
        if spec.layout == "table"
        else [
            *(c.key for c in (spec.by, spec.by2, spec.value[0]) if c is not None),
            *([requested_value] if spec.layout in layouts_mod.VALUE_LAYOUTS and requested_value in by_key else []),
        ]
    )
    load = list(
        dict.fromkeys(
            [
                *keys,
                *rule_keys,
                *(m.column for m in marks if m.column in keys),
                *(k for k, _ in totals if k in keys),
                *(c.key for c, _ in sort_cols),
                *(c.key for c in group_cols),
                *layout_keys,
            ]
        )
    )

    rows = report.rows(user, replace(filters, columns=tuple(load)))
    kinds = {key: column_kind(by_key[key], rows) for key in rule_keys}
    today = timezone.localdate()
    rows = rules_mod.keep_rows(rows, rule_tree, by_key, kinds, today)
    # the last key is sorted first: each pass is stable and keeps blanks last, so the first key decides the order
    for column, descending in reversed(sort_cols):
        rows = _sorted_rows(rows, column, descending)
    # the colour rules judge a value by its column's kind over the filtered rows; only shown columns are coloured
    mark_kinds = {c.key: column_kind(c, rows) for c in shown if any(m.column == c.key for m in marks)}
    pin = min(filters.pin, len(shown))
    # every filtered row, not only the page's batch; an empty table has no totals row
    footer = _footer(shown, classes, totals, rows) if rows else None
    if footer is not None:
        footer = [replace(cell, sticky_left=pin_style(i, pin)) for i, cell in enumerate(footer)]

    def cells(row: Any) -> list[Cell]:
        out: list[Cell] = []
        person = report.person(row) if report.person else 0
        for i, (c, cls) in enumerate(zip(shown, classes, strict=True)):
            value = c.value(row)
            mark = marks_mod.mark_for(marks, c.key, value, mark_kinds[c.key], today) if c.key in mark_kinds else ""
            out.append(
                Cell(
                    value=value,
                    href=c.href(row) if c.href is not None else "",
                    cls=cls,
                    money=c.money,
                    mark=mark,
                    sticky_left=pin_style(i, pin),
                    person=person,
                )
            )
        return out

    groups: list[tuple[str, list[list[Cell]]]]
    if not group_cols:
        groups = [("", [cells(row) for row in rows])]
    else:
        buckets: dict[tuple[str, ...], list[list[Cell]]] = {}
        for row in rows:
            parts = tuple(_text(c.value(row)) for c in group_cols)
            buckets.setdefault(parts, []).append(cells(row))
        blank = tuple("" for _ in group_cols)  # every key blank: this group goes last
        # per key: a named part before a blank one, then by text; the all-blank group is appended last
        named = sorted(
            (p for p in buckets if p != blank),
            key=lambda p: tuple((part == "", part.casefold()) for part in p),
        )
        groups = [(_group_label(p, group_cols), buckets[p]) for p in named]
        if blank in buckets:
            groups.append((_group_label(blank, group_cols), buckets[blank]))

    labels = {c.key: c.label for c in by_key.values()}
    # the layout again, now with the filtered rows, so an untyped column's kind is read from its values
    if spec.layout != "table":
        spec = layouts_mod.resolve(report, user, filters, rows)
    used = replace(
        filters,
        columns=tuple(c.key for c in shown),
        group=",".join(c.key for c in group_cols),
        sort=",".join(("-" if descending else "") + c.key for c, descending in sort_cols),
    )
    used = layouts_mod.used_params(used, spec)  # the resolved layout goes into the address (and only then)
    return Table(
        columns=shown,
        groups=groups,
        count=len(rows),
        filters=used,
        shows_count=report.shows_count,
        rules_text=rules_mod.describe_rules(rule_tree, labels),
        footer=footer,
        pin=pin,
        rows=rows,
        spec=spec,
    )
