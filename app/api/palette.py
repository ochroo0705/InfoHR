"""The Ctrl+K command palette's answer under /api/v1/palette: the groups the palette shows for a typed query.

GET /palette?q=&more=&recent=&from= answers the groups of employees.services.palette_answer (people, orders, screens and
quick actions, the remembered items and the current person's actions in the empty box), grouped and ordered by
employees.services.palette_rows. `more=1` is «show all» for people, `recent` is the browser's remembered references
and `from` the page path the palette was opened on. `fallback` is filled only when the answer is empty, as the Django
fragment shows it.

The assistant's «Асуух» row is not in this answer. The Django fragment adds it in employees.views.palette_search; the
React palette adds it itself (step 6 of the frontend split), so this route never reads the assistant app.

Every answer is `Cache-Control: no-store`: what a user may see depends on who asks. Only a signed-in user gets an
answer. A 401 (no login) goes through the API's error handler and carries no Cache-Control: it has no answer data.
The rights are applied in employees.palette, not here. The query is passed in full: the service cuts it where the
Django view does (palette.QUERY_LIMIT).
"""

from dataclasses import asdict
from typing import Literal

from accounts.models import User
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from employees.services import palette_answer, palette_rows
from ninja import Query, Router, Schema
from ninja.security import django_auth

from api.popups import request_user

palette_router = Router(tags=["palette"])


class PalettePieceOut(Schema):
    text: str
    hit: bool  # the letters a typed word matches (highlighted)


class PaletteOpenOut(Schema):
    kind: Literal["page", "popup", "legacy"]
    path: str  # a page: its URL (with query); a pop-up: its path; a legacy target: the list page's path
    popup: Literal["order_detail", "event", "slot_add", "leave_add", "leave_request"] | None
    employee: int | None
    order: int | None
    event_type: str | None
    year: int | None


class PaletteRowOut(Schema):
    key: str  # unique inside its group
    kind: Literal["person", "page", "calendar", "action", "order", "more"]  # the icon
    ref: str | None  # what the browser may remember: `p:<pk>` for a person, `s:<path>` for a fixed page
    open: PaletteOpenOut | None  # None for the «show all» row, which does not navigate
    title: list[PalettePieceOut]
    code: list[PalettePieceOut]
    lines: list[list[PalettePieceOut]]  # a person's position and department
    initials: str
    left: bool  # the person has left the company
    day: str  # an order's date as YYYY-MM-DD, "" when none


class PaletteGroupOut(Schema):
    key: str
    title: str
    count: int  # the items of the group (the «show all» row is not counted)
    total: int | None  # every match, only when it is more than count
    rows: list[PaletteRowOut]
    note: str  # a line under the rows, "" when none


class PaletteOut(Schema):
    groups: list[PaletteGroupOut]
    empty: bool  # true when the empty box's fallback applies
    empty_text: str  # the line shown when nothing matches
    fallback_heading: str  # the line above the fallback rows
    fallback: list[PaletteRowOut]  # the rows under the heading; [] unless empty


@palette_router.get("", response=PaletteOut, auth=django_auth)
def palette_answer_api(
    request: HttpRequest,
    response: HttpResponse,
    q: str = "",
    more: str = "",
    recent: str = "",
    from_path: str = Query("", alias="from"),
) -> dict[str, object]:
    """The palette's groups for the typed query. `more` is «show all» only when it is "1"; `recent` and `from` are
    re-checked by the service."""
    user: User = request_user(request)
    result = palette_answer.answer(
        user,
        q=q,
        more=more == "1",
        recent_raw=recent,
        from_path=from_path,
        today=timezone.localdate(),
    )
    empty = palette_rows.empty(result)
    response["Cache-Control"] = "no-store"  # the answer depends on who asks
    return {
        "groups": [asdict(group) for group in palette_rows.groups(result, user)],
        "empty": empty,
        "empty_text": palette_rows.EMPTY_TEXT,
        "fallback_heading": palette_rows.FALLBACK_HEADING,
        "fallback": [asdict(row) for row in palette_rows.fallback(user)] if empty else [],
    }
