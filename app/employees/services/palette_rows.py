"""The rows and groups of the Ctrl+K palette's answer, ready for the React panel: the same rows, in the same order,
as the Django fragment templates (employees/_palette_results.html and its includes).

`groups` turns a PaletteAnswer into display groups; `empty` tells whether the answer shows the empty box's fallback;
`fallback` gives the rows under «Эсвэл нээх:»; `open_target` says what a row opens: a page, a pop-up, or
the list page of a pop-up not yet ported. Rights are enforced by employees.palette and
employees.services.palette_answer. The fallback rows are the one exception: they are gated here, as the template
gates them. Nothing here reads an HttpRequest.
"""

from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from accounts.models import User
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone

from employees import palette
from employees.services import slot_page
from employees.services.palette_answer import PaletteAnswer

EMPTY_TEXT = "Юу ч олдсонгүй"  # the empty box's line when nothing matches (_palette_results.html)
FALLBACK_HEADING = "Эсвэл нээх:"  # the line above the fallback rows (_palette_results.html)

# The pop-ups not ported yet: each opens the list page that owns it. A bare htmx fragment must never load as a page.
# Open question for the user: until step 4 these three open the list page instead of the pop-up.
_LEGACY_MODAL_PAGE: dict[str, str] = {
    "leave:add": "leave:list",
    "leave:request_new": "leave:requests",
    "recruitment:vacancy_add": "recruitment:vacancies",
}


@dataclass(frozen=True)
class PalettePiece:
    text: str
    hit: bool  # the letters a typed word matches (highlighted)


@dataclass(frozen=True)
class PaletteOpen:
    kind: Literal["page", "popup", "legacy"]
    path: str  # a page: its URL (with query); a pop-up: its path; a legacy target: the list page's path
    popup: Literal["order_detail", "event", "slot_add"] | None
    employee: int | None
    order: int | None
    event_type: str | None
    year: int | None


@dataclass(frozen=True)
class PaletteRow:
    key: str  # unique inside its group (the React list key)
    kind: str  # person, page, calendar, action, order or more (the icon)
    ref: str | None  # what the browser may remember: `p:<pk>` for a person, `s:<path>` for a fixed page
    open: PaletteOpen | None  # None for the «show all» row, which does not navigate
    title: list[PalettePiece]
    code: list[PalettePiece]
    lines: list[list[PalettePiece]]  # a person's position and department (people only)
    initials: str
    left: bool  # the person has left the company
    day: str = ""  # an order's date as YYYY-MM-DD, the second line under its title ("" when none)


@dataclass(frozen=True)
class PaletteGroup:
    key: str
    title: str
    count: int  # the items of the group (the «more» row is not counted)
    total: int | None  # every match, only when it is more than `count` (the header then shows «count / total»)
    rows: list[PaletteRow]
    note: str  # a line under the rows (the cut note), "" when none


def _query_int(query: dict[str, list[str]], name: str) -> int | None:
    values = query.get(name)
    if not values:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


def open_target(url: str, modal: bool) -> PaletteOpen:
    """Where a palette row opens. A page keeps its URL, query included. A pop-up is resolved from its path (the query
    is read for `year`, and `employee` where the pop-up has none in its path); an unported pop-up opens its list page.
    A modal URL that no table names (or that does not resolve) opens as the page it names."""
    page = PaletteOpen("page", url, None, None, None, None, None)
    if not modal:
        return page
    parts = urlsplit(url)
    try:
        match = resolve(parts.path)
    except Resolver404:
        return page
    query = parse_qs(parts.query)
    name = match.view_name
    if name == "employees:order_detail":
        return PaletteOpen(
            "popup", parts.path, "order_detail", match.kwargs["pk"], match.kwargs["order_id"], None, None
        )
    if name == "employees:event":
        return PaletteOpen("popup", parts.path, "event", match.kwargs["pk"], None, match.kwargs["type"], None)
    if name == "employees:slot_add":
        employee = _query_int(query, "employee")
        # The slot form starts with the year of ?year= when it is a valid year, else the current year (as slot_add
        # does), so a real row always carries a number.
        year = slot_page.year_param((query.get("year") or [None])[0], timezone.localdate().year)
        return PaletteOpen("popup", parts.path, "slot_add", employee, None, None, year)
    if name in _LEGACY_MODAL_PAGE:
        employee = _query_int(query, "employee")
        return PaletteOpen("legacy", reverse(_LEGACY_MODAL_PAGE[name]), None, employee, None, None, None)
    return page


def _pieces(text: str, words: list[str]) -> list[PalettePiece]:
    """The text cut into highlighted and plain pieces. With no typed words nothing is highlighted."""
    if not text:
        return []
    if not words:
        return [PalettePiece(text, False)]
    return [PalettePiece(piece, hit) for piece, hit in palette.highlight(text, words)]


def _row(
    key: str,
    kind: str,
    open_: PaletteOpen | None,
    title: list[PalettePiece],
    *,
    ref: str | None = None,
    lines: list[list[PalettePiece]] | None = None,
    day: str = "",
) -> PaletteRow:
    return PaletteRow(
        key=key,
        kind=kind,
        ref=ref,
        open=open_,
        title=title,
        code=[],
        lines=lines or [],
        initials="",
        left=False,
        day=day,
    )


def _page_row(key: str, kind: str, url: str, title: str, words: list[str], *, ref: str | None = None) -> PaletteRow:
    return _row(key, kind, open_target(url, False), _pieces(title, words), ref=ref)


def _person_row(key: str, hit: palette.PersonHit, words: list[str]) -> PaletteRow:
    employee = hit.employee
    lines: list[list[PalettePiece]] = []
    if hit.position:
        lines.append(_pieces(hit.position, words))
    if hit.department:
        lines.append(_pieces(hit.department, words))
    return PaletteRow(
        key=key,
        kind="person",
        ref=f"p:{employee.pk}",
        open=open_target(reverse("employees:detail", args=[employee.pk]), False),
        title=_pieces(employee.full_name, words),
        code=_pieces(employee.code or "", words),
        lines=lines,
        initials=hit.initials,
        left=hit.left,
        day="",
    )


def _action_row(key: str, action: palette.Action, words: list[str]) -> PaletteRow:
    return _row(key, "action", open_target(action.url, action.modal), _pieces(action.title, words))


def _group(
    key: str, title: str, count: int, rows: list[PaletteRow], total: int | None = None, note: str = ""
) -> PaletteGroup:
    shown_total = total if total is not None and total > count else None  # «count / total» only when some are left out
    return PaletteGroup(key=key, title=title, count=count, total=shown_total, rows=rows, note=note)


def empty(answer: PaletteAnswer) -> bool:
    """True when the template's empty rule holds: nothing in the current person's actions, recent items, people,
    orders, screens or quick actions. The person's own actions (person_actions) are not part of this rule."""
    return not (
        answer.current_actions or answer.recent or answer.people or answer.orders or answer.screens or answer.actions
    )


def groups(answer: PaletteAnswer, user: User) -> list[PaletteGroup]:
    """The non-empty groups of the answer, in the order of _palette_results.html: the current person's actions, the
    remembered items, the people (with «show all» or the cut note), the single person's actions, orders, screens and
    quick actions. The assistant's row is not here. Highlights are only for the typed words; recent rows have none.
    `user` is kept for the view's call; the rights are already applied in the answer."""
    words = answer.words
    out: list[PaletteGroup] = []

    if answer.current_actions and answer.current is not None:
        title = f"Үйлдэл · {answer.current.employee.full_name}"
        rows = [_action_row(f"current:{i}", action, words) for i, action in enumerate(answer.current_actions)]
        out.append(_group("current_actions", title, len(rows), rows))

    if answer.recent:
        rows = []
        for i, item in enumerate(answer.recent):
            key = f"recent:{i}"
            if item.person is not None:
                rows.append(_person_row(key, item.person, []))
            else:
                rows.append(_page_row(key, item.kind, item.url, item.title, [], ref=item.ref))
        out.append(_group("recent", "Сүүлд нээсэн", len(rows), rows))

    if answer.people:
        rows = [_person_row(f"people:{i}", hit, words) for i, hit in enumerate(answer.people)]
        note = ""
        if answer.people_more:
            more_title = [PalettePiece(f"Бүх {answer.people_total} хүнийг харуулах", False)]
            rows.append(_row("people:more", "more", None, more_title))
        elif answer.people_total > len(answer.people):
            note = f"Эхний {len(answer.people)} хүн харагдаж байна. Хайлтаа нарийсгана уу."
        out.append(_group("people", "Хүмүүс", len(answer.people), rows, total=answer.people_total, note=note))

    if answer.person_actions and answer.single is not None:
        title = f"Үйлдэл · {answer.single.employee.full_name}"
        rows = [_action_row(f"person:{i}", action, words) for i, action in enumerate(answer.person_actions)]
        out.append(_group("person_actions", title, len(rows), rows))

    if answer.orders:
        rows = [
            _row(
                f"orders:{i}",
                "order",
                open_target(order.url, True),
                _pieces(order.title, words),
                day=order.day,
            )
            for i, order in enumerate(answer.orders)
        ]
        out.append(_group("orders", "Тушаал", len(rows), rows))

    if answer.screens:
        rows = []
        for i, screen in enumerate(answer.screens):
            ref = f"s:{screen.url}" if screen.url in answer.fixed_urls else None
            rows.append(_page_row(f"screens:{i}", screen.kind, screen.url, screen.title, words, ref=ref))
        out.append(_group("screens", "Хуудас", len(rows), rows))

    if answer.actions:
        rows = [_action_row(f"actions:{i}", action, words) for i, action in enumerate(answer.actions)]
        out.append(_group("actions", "Үйлдэл", len(rows), rows))

    return out


def fallback(user: User) -> list[PaletteRow]:
    """The rows under «Эсвэл нээх:» when the answer is empty: the employee list (needs both the report and the employee
    view rights) and «Ажилтан нэмэх» (needs the employee management right). The caller shows FALLBACK_HEADING and
    EMPTY_TEXT."""
    rows: list[PaletteRow] = []
    if user.has_perm("reports.view_reports") and user.has_perm("macs.view_employees"):
        rows.append(_page_row("fallback:list", "page", reverse("employees:list"), "Ажилтнууд", []))
    if user.has_perm("macs.manage_employees"):
        rows.append(_page_row("fallback:add", "action", reverse("employees:add"), "Ажилтан нэмэх", []))
    return rows
