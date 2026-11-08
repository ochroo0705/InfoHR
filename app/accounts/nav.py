"""The top bar menu: groups of links worked out from the user's rights (drawn by `templates/base.html`).

A group with one link the user may open is drawn as that plain link; with two or more it is a drop-down menu under
the group's label. Hiding a link is not access control: every view checks its own right.
"""

from dataclasses import dataclass
from typing import Any

from django.http import HttpRequest
from django.urls import reverse

from accounts.models import User

SLOT_PAGES = ("slots", "slot_add", "slot_edit", "slot_delete")  # the position-slot screen (settings group)
# the employee self-form screens (employees/views_selfform.py)
SELFFORM_PAGES = ("selfforms", "selfform_new", "selfform_show", "selfform_revoke", "selfform_extend")


@dataclass(frozen=True)
class NavItem:
    label: str
    url: str
    active: bool = False
    badge: int = 0
    icon: str = "page"  # templates/_nav_icon.html: the icon tile shown in a drop-down menu
    hint: str = ""  # one grey line under the label in a drop-down menu


@dataclass(frozen=True)
class NavGroup:
    key: str
    label: str
    items: tuple[NavItem, ...]

    @property
    def active(self) -> bool:
        return any(item.active for item in self.items)

    @property
    def badge(self) -> int:
        return sum(item.badge for item in self.items)

    @property
    def single(self) -> NavItem | None:
        """The only link of the group, drawn as a plain link; None when the group is a drop-down menu."""
        return self.items[0] if len(self.items) == 1 else None


def _sees_recruitment(request: HttpRequest) -> bool:
    """Whether the «Ажилд авах» link shows: asked once per request (kept on the request), as the other nav checks."""
    cached: bool | None = getattr(request, "_sees_recruitment", None)
    if cached is None:
        from recruitment.services.visibility import sees_recruitment  # local import: recruitment imports accounts

        cached = bool(request.user.is_authenticated and sees_recruitment(request.user))
        request._sees_recruitment = cached  # type: ignore[attr-defined]
    return cached


def _selfform_waiting(request: HttpRequest) -> int:
    """How many submitted self-forms the user may see (the «Өөрөө бөглөх анкет» badge): one count per request, kept on
    the request. Asked only for a user who may manage employees."""
    cached: int | None = getattr(request, "_selfform_waiting", None)
    if cached is None:
        from employees.models import SelfFormStatus  # local import: employees imports accounts
        from employees.selfform.service import visible_invitations

        user = request.user
        cached = 0
        if isinstance(user, User):
            cached = visible_invitations(user).filter(status=SelfFormStatus.SUBMITTED).count()
        request._selfform_waiting = cached  # type: ignore[attr-defined]
    return cached


def top_nav(request: HttpRequest, own_record: bool, leave_requests: dict[str, Any]) -> list[NavGroup]:
    """The groups of the top bar for this user, in order; groups with no link the user may open are left out.

    `own_record` and `leave_requests` come from the cached template tags (`hr.own_record`, `leave_tags.requests_nav`)
    so the bar costs no query of its own.
    """
    user = request.user
    match = request.resolver_match
    app = match.app_name if match else ""
    name = match.url_name if match else ""
    sees_staff = user.has_perm("macs.view_employees")
    sees_recruitment = _sees_recruitment(request)

    def group(key: str, label: str, *items: NavItem | None) -> NavGroup | None:
        shown = tuple(item for item in items if item is not None)
        return NavGroup(key, label, shown) if shown else None

    groups = [
        # Staff without the HR right land on their own page, so it is their first link; HR finds it in the user menu.
        group("me", "Миний хуудас", NavItem("Миний хуудас", reverse("me"), name == "me"))
        if own_record and not sees_staff
        else None,
        group("today", "Өнөөдөр", NavItem("Өнөөдөр", reverse("employees:today"), name == "today"))
        if sees_staff
        else None,
        group(
            "employees",
            "Ажилтнууд",
            NavItem(
                "Ажилтнууд",
                reverse("employees:list"),
                app == "employees" and name not in ("today", "orders", "orders_print", *SLOT_PAGES, *SELFFORM_PAGES),
                icon="people",
                hint="Жагсаалт, хайлт, хувийн хэрэг",
            ),
            NavItem(
                "Тушаалын бүртгэл",
                reverse("employees:orders"),
                name in ("orders", "orders_print"),
                icon="order",
                hint="Бүх тушаал, дугаар, хэвлэх",
            )
            if sees_staff
            else None,
            NavItem(
                "Өөрөө бөглөх анкет",
                reverse("employees:selfforms"),
                app == "employees" and name in SELFFORM_PAGES,
                _selfform_waiting(request),
                icon="inbox",
                hint="Ажилтны бөглөсөн анкет, холбоос",
            )
            if user.has_perm("macs.manage_employees")
            else None,
        ),
        group(
            "leave",
            "Чөлөө, амралт",
            NavItem(
                "Чөлөө, амралт",
                reverse("leave:list"),
                app == "leave" and name not in ("requests", "request_detail"),
                icon="calendar",
                hint="Бүртгэл, үлдэгдэл, багийн хуанли",
            )
            if user.has_perm("leave.view_leave")
            else None,
            NavItem(
                "Хүсэлт",
                reverse("leave:requests"),
                app == "leave" and name in ("requests", "request_detail"),
                leave_requests["count"],
                icon="inbox",
                hint="Батлах хүлээж буй хүсэлтүүд",
            )
            if leave_requests["show"]
            else None,
        ),
        group(
            "recruitment",
            "Ажилд авах",
            NavItem(
                "Ажилд авах",
                reverse("recruitment:vacancies"),
                app == "recruitment",
                icon="people",
                hint="Ажлын байр, ажил хүсэгчид",
            )
            if sees_recruitment
            else None,
        ),
        group(
            "reports",
            "Тайлан",
            NavItem(
                "Тайлан",
                reverse("reports:catalogue"),
                app == "reports",
                icon="chart",
                hint="Тайлан харах, хэвлэх, Excel",
            )
            if user.has_perm("reports.view_reports")
            else None,
            NavItem(
                "Бүртгэл",
                reverse("logs:employee" if sees_staff else "logs:system"),
                app == "logs",
                icon="history",
                hint="Хэн, хэзээ, юу өөрчилсөн",
            )
            if sees_staff or user.has_perm("accounts.view_audit")
            else None,
        ),
        group(
            "settings",
            "Тохиргоо",
            NavItem("Жагсаалтууд", reverse("lists:index"), app == "lists", icon="list", hint="Сонголтын жагсаалтууд")
            if user.has_perm("lists.manage_lists")
            else None,
            NavItem(
                "Орон тооны төлөвлөгөө",
                reverse("employees:slots"),
                app == "employees" and name in SLOT_PAGES,
                icon="people",
                hint="Албан тушаал, салбар тус бүрийн орон тоо",
            )
            if user.has_perm("employees.manage_position_slots")
            else None,
            NavItem("Админ хэсэг", reverse("admin:index"), icon="gear", hint="Хэрэглэгч, эрх, тохиргоо")
            if getattr(user, "is_staff", False)
            else None,
        ),
    ]
    return [g for g in groups if g is not None]
