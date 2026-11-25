"""The report page's rules that need no request: the cleaned address, the sort links, the header cells, the folded
filters and the saved-view helpers. reports.views (the Django pages) and the React API both call these, so a rule has
one home. Nothing here reads a request; a user is passed in only where a permission decides what is offered."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from urllib.parse import urlencode

from accounts.models import User
from django.http import QueryDict

from reports.column_filters import COLUMN_FILTERS, params_of
from reports.filters import MAX_SORT_KEYS, Filters, to_query
from reports.table import css_classes, offered_column_filters
from reports.types import Column, Report


@dataclass(frozen=True)
class HeaderCell:
    label: str
    href: str  # the address that sorts the table by this column (a second click reverses it)
    append_href: str  # the address that adds this column to the sort, or flips it (Shift+click)
    arrow: str  # "↑", "↓" on the sorted column, "↑1", "↓2" when several keys sort, else ""
    cls: str  # alignment classes
    sticky_left: str = ""  # the inline offset of a pinned column, "" when not pinned (table.pin_style)

    @property
    def css(self) -> str:
        """The th's classes on the screen: alignment and pinning."""
        return css_classes(self.cls, "", self.sticky_left)


# The address of a view with an empty cleaned query: a parameter, so the bare-address default does not apply.
PLAIN_VIEW = "view=plain"


def address(path: str, f: Filters, adds: Sequence[str] = (), *, plain: bool = False) -> str:
    """The report's address for these filters. `adds` are the column filters named by `add` (the picker's ephemeral
    chips): they go in the address bar only, never in the filters, print or Excel. `plain` (a report with saved views)
    makes an empty query read `view=plain`, so the bare address does not open the default view again."""
    query = "&".join(part for part in (to_query(f), urlencode([("add", name) for name in adds])) if part)
    if query:
        return f"{path}?{query}"
    return f"{path}?{PLAIN_VIEW}" if plain else path


def month_param(day: date, today: date) -> str:
    """The «YYYY-MM» of a day's month for lmonth; "" for this month (the default, kept out of the address)."""
    if (day.year, day.month) == (today.year, today.month):
        return ""
    return f"{day:%Y-%m}"


def added_names(get: QueryDict, offered: list[str]) -> list[str]:
    """The column filters named by `add`, in the order given. Only names the user may use; a repeat is kept once."""
    names: list[str] = []
    for name in get.getlist("add"):
        if name in offered and name not in names:
            names.append(name)
    return names


def next_sort(current: str, key: str, append: bool = False) -> str:
    """The sort after a click on a column header. A plain click sorts by this column alone: ascending, descending on
    the second click, ascending again on the third. Shift+click (append) adds the column after the other keys,
    ascending, or flips its direction where it already is; it never removes a key."""
    keys = [part for part in current.split(",") if part]
    if not append:
        return f"-{key}" if current == key else key
    if any(part.removeprefix("-") == key for part in keys):
        return ",".join(
            (part[1:] if part.startswith("-") else f"-{part}") if part.removeprefix("-") == key else part
            for part in keys
        )
    if len(keys) >= MAX_SORT_KEYS:
        return current
    return ",".join([*keys, key])


def sort_mark(sort: str, key: str) -> str:
    """A column's arrow: "↑" for ascending, "↓" for descending, "" when it is not sorted. With two or more keys the
    arrow carries the column's place in the sort ("↑1", "↓2")."""
    keys = [part for part in sort.split(",") if part]
    for place, part in enumerate(keys, start=1):
        if part.removeprefix("-") != key:
            continue
        arrow = "↓" if part.startswith("-") else "↑"
        return f"{arrow}{place}" if len(keys) >= 2 else arrow
    return ""


def group_text(group: str, choices: Sequence[Column]) -> str:
    """The label of a grouping with several keys ("a,b"), as the «Бүлэглэх» select shows it: the column labels joined.
    Empty for one key or none, which the select's own options show."""
    if "," not in group:
        return ""
    labels = {c.key: c.label for c in choices}
    return " · ".join(labels.get(key, key) for key in group.split(","))


# A long filter bar (more than FILTERS_SLIM_FROM filters) keeps only the FILTERS_QUICK most useful ones on screen. The
# others are offered in the «Шүүлтүүр нэмэх» menu and appear as a control with a ✕ once picked (`add=<name>` in the
# address) or as soon as they hold a value. Only the filters in FOLDABLE can be folded: each maps to the Filters
# fields its ✕ resets, which is also how «holds a value» is read from the address.
FILTERS_QUICK = 4
FILTERS_SLIM_FROM = 5
FILTERS_PRIORITY = ("state", "as_of", "period", "department", "emptype", "employee", "branch", "year", "quarter")
FOLDABLE: dict[str, tuple[str, ...]] = {
    "branch": ("branch",),
    "department": ("department",),
    "position": ("position",),
    "gender": ("gender",),
    "emptype": ("emptype",),
    "age_range": ("age_from", "age_to"),
    "employee": ("employee",),
}
FILTER_LABELS = {
    "branch": "Салбар",
    "department": "Хэлтэс",
    "position": "Албан тушаал",
    "gender": "Хүйс",
    "emptype": "Ажилтны төрөл",
    "age_range": "Нас",
    "employee": "Ажилтан",
}


def secondary_filters(names: Sequence[str]) -> tuple[str, ...]:
    """The filters that start folded away: all but the FILTERS_QUICK most useful ones (FILTERS_PRIORITY order, then the
    report's own order), and only those that can be folded. Empty for a short bar."""
    if len(names) <= FILTERS_SLIM_FROM:
        return ()
    rank = {n: i for i, n in enumerate(FILTERS_PRIORITY)}
    quick = sorted(names, key=lambda n: (rank.get(n, len(rank)), list(names).index(n)))[:FILTERS_QUICK]
    return tuple(n for n in names if n not in quick and n in FOLDABLE)


def holds_value(name: str, f: Filters) -> bool:
    return any(getattr(f, field) not in (None, "") for field in FOLDABLE[name])


def offered_adds(report: Report, user: User, names: Sequence[str]) -> list[str]:
    """Every name `add` may carry for this user: the column filters and the foldable built-in filters."""
    return [*offered_column_filters(report, user), *secondary_filters(names)]


def column_filter_panels(
    path: str, f: Filters, offered: list[str], adds: list[str], plain: bool = False
) -> tuple[list[tuple[str, str, str]], list[dict[str, Any]]]:
    """The picker's entries (name, label, href) for the offered filters not yet shown, and the chips (dicts) for the
    shown ones. A filter is shown when it has a value or `add` names it. Code-list rows are read for shown chips
    only."""
    given = dict(f.extra)
    choices: list[tuple[str, str, str]] = []
    chips: list[dict[str, Any]] = []
    for name in offered:
        cf = COLUMN_FILTERS[name]
        params = params_of(cf)
        if name not in adds and not any(p in given for p in params):
            choices.append((name, cf.label, address(path, f, [*adds, name], plain=plain)))
            continue
        options: list[tuple[str, str]] = []
        if cf.kind == "code" and cf.model is not None:
            rows = cf.model._default_manager.order_by("name").values_list("pk", "name")
            options = [(str(pk), label or "—") for pk, label in rows]  # a row with no name reads «—», not «None»
        elif cf.kind == "choice":
            options = [(str(key), label) for key, label in cf.choices]
        values = [given.get(p, "") for p in params]
        # removing the chip drops its values and its add entry; the other filters and add names stay
        rest = replace(f, extra=tuple(pair for pair in f.extra if pair[0] not in params))
        chips.append(
            {
                "name": name,
                "label": cf.label,
                "kind": cf.kind,
                "params": list(params),
                "options": options,
                "values": values,
                "remove_href": address(path, rest, [a for a in adds if a != name], plain=plain),
            }
        )
    return choices, chips


def builtin_panels(
    path: str, f: Filters, secondary: Sequence[str], adds: list[str], plain: bool
) -> tuple[list[str], list[tuple[str, str, str]], dict[str, str]]:
    """The folded built-in filters for the bar and the menu: the names to draw now (those with a value or named by
    `add`), the menu entries (name, label, href) for the others, and each drawn one's ✕ address (its fields reset, its
    `add` dropped)."""
    shown: list[str] = []
    choices: list[tuple[str, str, str]] = []
    removes: dict[str, str] = {}
    for name in secondary:
        if name in adds or holds_value(name, f):
            shown.append(name)
            blanks: dict[str, Any] = {field: ("" if field == "gender" else None) for field in FOLDABLE[name]}
            reset = replace(f, **blanks)
            removes[name] = address(path, reset, [a for a in adds if a != name], plain=plain)
        else:
            choices.append((name, FILTER_LABELS.get(name, name), address(path, f, [*adds, name], plain=plain)))
    return shown, choices, removes
