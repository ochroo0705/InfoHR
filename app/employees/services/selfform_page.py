"""The request-free part of the employee self-form HR screens («Өөрөө бөглөх анкет»): the badge table, the state of an
invitation, the rows of the list, the link page's data (the QR code is drawn here, the link is built from the request
only through `service.invitation_url`), and the reading of the hours typed on the extend form.

The rules themselves live in employees.selfform.service. The Django views (employees.views_selfform) and the API
routes call these functions.
"""

from dataclasses import dataclass
from datetime import datetime

from accounts.models import User
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import SafeString, mark_safe

from employees.models import CompanySettings, SelfFormInvitation, SelfFormStatus
from employees.selfform import service

# state key -> (Mongolian label, badge classes). The classes are the ones employees/_state.html already uses.
BADGES: dict[str, tuple[str, str]] = {
    "open": ("Нээлттэй", "bg-sky-100 text-sky-900 ring-1 ring-inset ring-sky-300"),
    "expired": ("Хугацаа дууссан", "bg-slate-200 text-slate-700"),
    "submitted": ("Хянах хүлээж байна", "bg-amber-100 text-amber-900 ring-1 ring-inset ring-amber-300"),
    "confirmed": ("Баталгаажсан", "bg-emerald-100 text-emerald-800"),
    "rejected": ("Татгалзсан", "bg-slate-200 text-slate-700"),
    "revoked": ("Цуцалсан", "bg-slate-200 text-slate-700"),
}
_MAX_HOURS_DIGITS = 6  # a longer number is refused before it is turned into an int


@dataclass(frozen=True)
class ListRow:
    invitation: SelfFormInvitation
    state: str
    badge: str
    when: datetime | None  # expiry while open, submission time once submitted
    show_path: str
    hire_path: str  # the hire page with this submission; empty unless submitted


@dataclass(frozen=True)
class ShowData:
    invitation: SelfFormInvitation
    state: str
    badge: str
    state_key: str
    purged: bool  # the answers and the photo were cleared by the retention run
    url: str  # the link the employee opens
    qr_svg: SafeString | None  # the QR code of the link, or None when it cannot be drawn
    default_hours: int
    hire_path: str


def state_key(inv: SelfFormInvitation, now: datetime) -> str:
    if inv.status == SelfFormStatus.OPEN:
        return "expired" if service.is_expired(inv, now) else "open"
    return str(inv.status)


def list_rows(user: User, now: datetime) -> list[ListRow]:
    invitations = service.visible_invitations(user).select_related("branch").order_by("-created_at")
    return [_row(inv, now) for inv in invitations]


def _row(inv: SelfFormInvitation, now: datetime) -> ListRow:
    key = state_key(inv, now)
    label, badge = BADGES[key]
    submitted = inv.status == SelfFormStatus.SUBMITTED
    return ListRow(
        invitation=inv,
        state=label,
        badge=badge,
        when=inv.submitted_at if submitted else inv.expires_at,
        show_path=reverse("employees:selfform_show", args=[inv.pk]),
        hire_path=f"{reverse('employees:add')}?submission={inv.pk}" if submitted else "",
    )


def show_data(user: User, pk: int, request: HttpRequest) -> ShowData:
    invitation = service.invitation_for(user, pk)
    url = service.invitation_url(invitation, request)
    key = state_key(invitation, timezone.now())
    state, badge = BADGES[key]
    return ShowData(
        invitation=invitation,
        state=state,
        badge=badge,
        state_key=key,
        purged=invitation.purged_at is not None,
        url=url,
        qr_svg=qr_or_none(url),
        default_hours=CompanySettings.get().selfform_default_hours,
        hire_path=f"{reverse('employees:add')}?submission={invitation.pk}",
    )


def qr_or_none(url: str) -> SafeString | None:
    """The QR code as inline SVG, or None when segno is not installed or the link is too long for a code
    (the link is still shown)."""
    try:
        import segno  # lazy, as in service.qr_svg; a missing package is the ImportError case below

        svg = service.qr_svg(url)
    except ImportError:
        return None
    except segno.DataOverflowError:  # the configured base address makes the link too long for a code
        return None
    # segno writes the SVG itself from a URL we build (base address plus token); the code is path data only.
    return mark_safe(svg)  # noqa: S308


def parse_hours(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    if not (raw.isdecimal() and len(raw) <= _MAX_HOURS_DIGITS):
        raise service.SelfFormError("Хугацааг цагаар бүхэл тоогоор бичнэ үү.")
    return int(raw)
