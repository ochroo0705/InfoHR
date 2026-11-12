"""The top bar menu: groups of links worked out from the user's rights (drawn by `templates/base.html`).

A group with one link the user may open is drawn as that plain link; with two or more it is a drop-down menu under
the group's label. Hiding a link is not access control: every view checks its own right.
"""

import logging
from dataclasses import dataclass
from typing import Any

from django.http import HttpRequest
from django.urls import reverse

from accounts.models import User

logger = logging.getLogger(__name__)

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
    compact: bool = False  # a small one-line row (no icon tile, no hint) for a long list of shortcuts
    section: str = ""  # a small grey heading drawn above this item (the first of a run of compact rows)


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


def _sees_workspace(request: HttpRequest) -> bool:
    """Whether the «Асуулт, хүснэгт» link (workspace) shows: the workspace gate (assistant/ws_views.py), asked once per request."""
    cached: bool | None = getattr(request, "_sees_workspace", None)
    if cached is None:
        try:
            from assistant.ws_views import can_use_workspace  # local import: assistant imports accounts

            cached = bool(can_use_workspace(request.user))
        except Exception as exc:  # the top bar is on every page: a failed check means no entry, never a 500
            logger.warning("workspace nav check failed: %s", type(exc).__name__)
            cached = False
        request._sees_workspace = cached  # type: ignore[attr-defined]
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


# The staff types the old program listed separately (reports.filters.EMPTYPES codes), as shortcuts into the staff list.
STAFF_TYPE_SHORTCUTS: tuple[tuple[int, str], ...] = (
    (6, "Өндөр настан"),
    (5, "Гэрээт ажилтан"),
    (9, "Туршилтын хугацаатай"),
    (8, "Хөлсөөр ажиллах гэрээтэй"),
    (2, "Гадаад нөөц"),
    (4, "Орохоор бүртгүүлсэн"),
    (3, "Ажиллаж байсан"),
)


def _staff_type_items(request: HttpRequest, user: User) -> list[NavItem]:
    """One compact shortcut per staff type, each opening the staff list report already filtered to that type. Only for
    a user who may open that report; the report page checks the right again."""
    from reports import registry  # local import: reports imports accounts

    report = registry.REPORTS.get("staff-list")
    if report is None or not registry.can_open(user, report):
        return []
    match = request.resolver_match
    on_report = bool(match and match.app_name == "reports" and match.kwargs.get("key") == "staff-list")
    current = request.GET.get("emptype", "") if on_report else ""
    base = reverse("reports:report", args=["staff-list"])
    return [
        NavItem(
            label,
            f"{base}?emptype={code}",
            current == str(code),
            compact=True,
            section="Ажилтны ангилал" if index == 0 else "",
        )
        for index, (code, label) in enumerate(STAFF_TYPE_SHORTCUTS)
    ]


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
    from reports import registry  # local import: reports imports accounts

    staff_report = registry.REPORTS.get("staff-list")  # the employees screen is this report
    sees_staff_report = staff_report is not None and registry.can_open(user, staff_report)

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
                reverse("reports:report", args=["staff-list"]),
                (
                    app == "employees"
                    and name not in ("today", "orders", "orders_print", "company", *SLOT_PAGES, *SELFFORM_PAGES)
                )
                or (app == "reports" and match.kwargs.get("key") == "staff-list" and not request.GET.get("emptype")),
                icon="people",
                hint="Жагсаалт, хайлт, хувийн хэрэг",
            )
            if sees_staff_report
            else None,
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
            *_staff_type_items(request, user),
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
                "Компанийн байдал",
                reverse("employees:company"),
                app == "employees" and name == "company",
                icon="chart",
                hint="Ажилтны тоо, эргэлт, хэлтэс, ажилласан хугацаа",
            )
            if sees_staff
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
            "assistant",
            "Туслах",
            NavItem(
                "Асуулт, хүснэгт",
                reverse("assistant:workspace"),
                app == "assistant" and name in ("workspace", "workspace_tab"),
                icon="chart",
                hint="Асуултаар хүснэгт гаргах, шүүх, Excel",
            )
            if _sees_workspace(request)
            else None,
            NavItem(
                "Хадгалсан хүснэгт",
                reverse("assistant:saved_list"),
                app == "assistant" and name.startswith("saved"),
                icon="chart",
                hint="Асуултаар гаргаад хадгалсан хүснэгтүүд",
            )
            if _sees_workspace(request)
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
