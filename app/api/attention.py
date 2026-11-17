"""The "needs attention" box as the API sends it: the groups, their items, the tiers, and the /attention routes."""

from typing import Any, Literal

from accounts.models import User
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils import timezone
from employees import access, attention
from employees import today as facts
from employees.listing import employee_rows
from ninja import Query, Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

attention_router = Router(tags=["attention"])


class EmployeeRefOut(Schema):
    id: int
    full_name: str
    short_name: str
    code: str


class ItemOut(Schema):
    key: str
    text: str
    urgency: int
    employee: EmployeeRefOut | None
    url: str  # the employee's page, or the system item's own page
    anchor: str  # the employee-page tab (#hash) where the item is fixed; "" opens the default tab
    clash: bool  # the short name is shared in its group, so the chip shows the code too
    can_dismiss: bool  # an employee item can be hidden; a system reminder stays until it is fixed


class GroupOut(Schema):
    kind: str
    urgency: int
    label: str
    count: int
    nearest: str | None  # the earliest date of the group, YYYY-MM-DD
    url: str  # the page that lists the group in full; "" when the kind has no page
    dated: bool  # dated items show one line each; the rest show as name chips
    open: bool  # overdue group, shown open by default
    shown: list[ItemOut]  # the first GROUP_LIMIT items
    more: int  # how many items sit behind «Бүгдийг харах»
    keys: list[str]  # the keys of every item in the group


class AttentionBoxOut(Schema):
    tone: str  # "urgent" | "soon" | "calm"
    urgent_count: int
    soon_count: int
    gap_count: int
    urgent: list[GroupOut]
    soon: list[GroupOut]
    gaps: list[GroupOut]
    hidden: list[ItemOut]


def item_out(item: attention.Attention, clash: bool) -> dict[str, object]:
    """One item as the box sends it. An employee item links to the employee's page, a system item to its own url."""
    person = item.employee
    return {
        "key": item.key,
        "text": item.text,
        "urgency": item.urgency,
        "employee": (
            {"id": person.pk, "full_name": person.full_name, "short_name": person.short_name, "code": person.code or ""}
            if person is not None
            else None
        ),
        "url": reverse("employees:detail", args=[person.pk]) if person is not None else item.url,
        "anchor": item.anchor,
        "clash": clash,
        "can_dismiss": person is not None,
    }


def group_out(group: attention.Group) -> dict[str, object]:
    clashes = group.clashes
    return {
        "kind": group.kind,
        "urgency": group.urgency,
        "label": group.label,
        "count": len(group.items),
        "nearest": group.nearest.isoformat() if group.nearest is not None else None,
        "url": group.url,
        "dated": group.dated,
        "open": group.urgency == attention.OVERDUE,
        "shown": [item_out(a, a.employee is not None and a.employee.pk in clashes) for a in group.shown],
        "more": group.more,
        "keys": [a.key for a in group.items],
    }


def box_out(box: attention.Box) -> dict[str, object]:
    """The whole attention box. Hidden items show no chips, so they never carry a clash."""
    tiers = box.tiers
    return {
        "tone": box.tone,
        "urgent_count": tiers.urgent_count,
        "soon_count": tiers.soon_count,
        "gap_count": tiers.gap_count,
        "urgent": [group_out(g) for g in tiers.urgent],
        "soon": [group_out(g) for g in tiers.soon],
        "gaps": [group_out(g) for g in tiers.gaps],
        "hidden": [item_out(a, clash=False) for a in box.hidden],
    }


class ToggleIn(Schema):
    keys: list[str]  # the item keys to act on (one item, or a whole group for "dismiss_all")
    action: Literal["dismiss", "dismiss_all", "restore"]


class ToggleOut(Schema):
    box: AttentionBoxOut


class AttentionMoreOut(Schema):
    dated: bool  # dated groups answer every item after the first GROUP_LIMIT at once
    items: list[ItemOut]
    more: int  # how many people are still behind this page (gap groups only)
    next_offset: int  # where the next page starts (gap groups only; 0 otherwise)


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


@attention_router.get("", auth=django_auth, response=AttentionBoxOut)
def attention_box(request: HttpRequest) -> dict[str, object]:
    """The attention box for the signed-in user, as the Today page builds it (only employees with an HR row)."""
    user, today = _user(request), timezone.localdate()
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    facts.prime_exts(rows)  # one query for every HR row: the attention rules read it per person
    return box_out(attention.box(user, attention.items(user, rows, today)))


@attention_router.post("/toggle", auth=django_auth, response=ToggleOut)
def attention_toggle(request: HttpRequest, payload: ToggleIn) -> dict[str, object]:
    """ "Мэдлээ" / "Дахин харуулах" on one Анхаарах item or a whole group; answers with the box."""
    user, today = _user(request), timezone.localdate()
    rows = employee_rows(access.visible_employees(user), today)
    facts.prime_exts(rows)  # one query for every HR row: the attention rules read it per person
    found = attention.items(user, rows, today)
    keys = set(payload.keys)
    picked = [a for a in found if a.key in keys]
    if not picked:
        raise HttpError(404, "Хуудас олдсонгүй")
    for item in picked:
        if payload.action == "restore":
            attention.restore(user, item)
        else:  # "dismiss" (one item) or "dismiss_all" (a whole group)
            attention.dismiss(user, item)
    return {"box": box_out(attention.box(user, found))}


@attention_router.get("/more", auth=django_auth, response=AttentionMoreOut)
def attention_more(
    request: HttpRequest,
    response: HttpResponse,
    kind: str = "",
    urgency: str = "",
    all_: str = Query("0", alias="all"),
    offset: str = "0",
) -> dict[str, Any]:
    """The items of one Анхаарах group past the first GROUP_LIMIT, or a page of a gap group with `all=1`."""
    user, today = _user(request), timezone.localdate()
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    facts.prime_exts(rows)  # one query for every HR row: the attention rules read it per person
    box = attention.box(user, attention.items(user, rows, today))
    found = next((g for g in box.groups if g.kind == kind and str(g.urgency) == urgency), None)
    if found is None:
        raise HttpError(404, "Хуудас олдсонгүй")
    try:
        start = max(0, int(offset))
    except ValueError:
        start = 0
    clashes = found.clashes
    if all_ == "1" and not found.dated:  # a missing-data row: its people a page at a time
        page_end = start + attention.GAP_PAGE
        page = found.items[start:page_end]
        more, next_offset = max(0, len(found.items) - page_end), page_end
    else:
        page = found.items[attention.GROUP_LIMIT :]
        more, next_offset = 0, 0
    response["Cache-Control"] = "no-store"  # the page must not come back from the Back cache
    return {
        "dated": found.dated,
        "items": [item_out(a, a.employee is not None and a.employee.pk in clashes) for a in page],
        "more": more,
        "next_offset": next_offset,
    }
