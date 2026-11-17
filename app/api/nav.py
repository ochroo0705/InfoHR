"""GET /api/v1/nav: the top bar's menu groups for the signed-in user, the same list the server template draws."""

from urllib.parse import urlsplit

from accounts.nav import NavGroup, top_nav
from django.http import HttpRequest
from django.urls import Resolver404, resolve
from employees.templatetags.hr import own_record
from leave.templatetags.leave_tags import requests_nav
from ninja import Router, Schema
from ninja.security import django_auth

nav_router = Router(tags=["nav"])


class NavItemOut(Schema):
    label: str
    url: str
    active: bool
    badge: int
    icon: str
    hint: str
    compact: bool
    section: str


class NavGroupOut(Schema):
    key: str
    label: str
    active: bool
    badge: int
    items: list[NavItemOut]


def _match_path(request: HttpRequest, path: str) -> None:
    """Set the request's resolver match from the SPA path, so the existing `active` rules work unchanged.
    A path that resolves to no page leaves nothing active."""
    try:
        request.resolver_match = resolve(urlsplit(path).path)
    except (Resolver404, ValueError):
        request.resolver_match = None


def _group_out(group: NavGroup) -> dict[str, object]:
    return {
        "key": group.key,
        "label": group.label,
        "active": group.active,
        "badge": group.badge,
        "items": [
            {
                "label": item.label,
                "url": item.url,
                "active": item.active,
                "badge": item.badge,
                "icon": item.icon,
                "hint": item.hint,
                "compact": item.compact,
                "section": item.section,
            }
            for item in group.items
        ],
    }


@nav_router.get("", auth=django_auth, response=list[NavGroupOut])
def nav(request: HttpRequest, path: str = "") -> list[dict[str, object]]:
    _match_path(request, path)
    context = {"request": request}
    groups = top_nav(request, bool(own_record(context)), requests_nav(context))
    return [_group_out(group) for group in groups]
