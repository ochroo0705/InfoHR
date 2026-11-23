"""The request-free answer of the Ctrl+K command palette: who, what and which screens a typed query finds for one user.

The matching rules live in employees.palette; this module only puts them together in the order the palette shows
them. The Django view (employees.views.palette_search) reads the request, calls `answer`, adds the assistant's row and
renders the template. Nothing here reads an HttpRequest.
"""

from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.urls import Resolver404, resolve

from employees import palette
from employees.palette import Action, OrderHit, PersonHit, Recent, Screen


@dataclass(frozen=True)
class PaletteAnswer:
    words: list[str]  # the typed words that are read (highlighted in the rows); empty for the empty box
    people: list[PersonHit]  # the people shown (at most PEOPLE_LIMIT, or PEOPLE_MORE_LIMIT after «show all»)
    people_total: int  # every person who matches, shown or not
    people_more: bool  # the «show all» link is offered
    recent: list[Recent]  # the remembered items, only for the empty box
    current: PersonHit | None  # the person whose record page the palette was opened on, only for the empty box
    current_actions: list[Action]  # that person's actions
    single: PersonHit | None  # the one person the query matched, when exactly one matched
    person_actions: list[Action]  # that person's actions
    orders: list[OrderHit]
    screens: list[Screen]
    actions: list[Action]
    fixed_urls: set[str]  # the URLs of the fixed screens: only these pages can be remembered


def page_pk(from_path: str) -> int | None:
    """The pk of the employee record the palette was opened on, from the page path the browser sends. Only the
    employee detail page counts (matched by the resolver, not by the text); anything else is None."""
    if not from_path or len(from_path) > palette.FROM_LIMIT:
        return None
    try:
        match = resolve(from_path)
    except Resolver404:
        return None
    if match.app_name != "employees" or match.url_name != "detail":
        return None
    pk = match.kwargs.get("pk")
    return pk if isinstance(pk, int) else None


def answer(user: User, *, q: str, more: bool, recent_raw: str, from_path: str, today: date) -> PaletteAnswer:
    """The palette's groups for the typed query `q`. `more` is «show all»; `recent_raw` is the browser's remembered
    references and `from_path` the page the palette was opened on (both are re-checked here, see palette.recent)."""
    people, people_total = palette.find_people(
        user, q, today, palette.PEOPLE_MORE_LIMIT if more else palette.PEOPLE_LIMIT
    )
    single = people[0] if len(people) == 1 else None  # the person's own actions only when exactly one person matched
    # The remembered items and the page's person are shown only in the empty box.
    typed = bool(q.split())
    recent = palette.recent(user, palette.parse_refs(recent_raw), today) if not typed else []
    pk = None if typed else page_pk(from_path)
    current = palette.current(user, pk, today) if pk is not None else None
    return PaletteAnswer(
        words=q[: palette.QUERY_LIMIT].split(),
        people=people,
        people_total=people_total,
        people_more=not more and people_total > len(people),  # offer «show all»
        recent=recent,
        current=current,
        current_actions=palette.person_actions(user, current) if current else [],
        single=single,
        person_actions=palette.person_actions(user, single) if single else [],
        orders=palette.orders(user, q),
        screens=palette.screens(user, q),
        actions=palette.actions(user, q),
        fixed_urls=palette.fixed_urls(user),  # only these pages get a data-palette-ref (what can be recalled)
    )
