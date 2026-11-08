"""The HR screens of the employee self-form («Өөрөө бөглөх анкет»): the invitation list with its create form, the link
page with the QR code, and revoke and extend. The rules live in `employees.selfform.service`; this module draws the
pages and turns the form posts into service calls. Every view needs `macs.manage_employees`.
"""

from dataclasses import dataclass
from datetime import datetime

from accounts.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import SafeString, mark_safe
from django.views.decorators.http import require_POST

from employees import access
from employees.models import CompanySettings, SelfFormInvitation, SelfFormStatus
from employees.selfform import service
from employees.selfform.forms import SelfFormInvitationForm

# state key -> (Mongolian label, badge classes). The classes are the ones employees/_state.html already uses.
_BADGES: dict[str, tuple[str, str]] = {
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
    show_url: str
    hire_url: str  # the hire page with this submission; empty unless submitted


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _require(allowed: bool) -> None:
    if not allowed:
        raise PermissionDenied


def _state_key(inv: SelfFormInvitation, now: datetime) -> str:
    if inv.status == SelfFormStatus.OPEN:
        return "expired" if service.is_expired(inv, now) else "open"
    return str(inv.status)


def _row(inv: SelfFormInvitation, now: datetime) -> ListRow:
    key = _state_key(inv, now)
    label, badge = _BADGES[key]
    submitted = inv.status == SelfFormStatus.SUBMITTED
    return ListRow(
        invitation=inv,
        state=label,
        badge=badge,
        when=inv.submitted_at if submitted else inv.expires_at,
        show_url=reverse("employees:selfform_show", args=[inv.pk]),
        hire_url=f"{reverse('employees:add')}?submission={inv.pk}" if submitted else "",
    )


def _render_list(request: HttpRequest, form: SelfFormInvitationForm, error: str = "") -> HttpResponse:
    user = _user(request)
    now = timezone.now()
    invitations = service.visible_invitations(user).select_related("branch").order_by("-created_at")
    context = {
        "rows": [_row(inv, now) for inv in invitations],
        "waiting": service.waiting_count(user),
        "form": form,
        "error": error,
    }
    return render(request, "employees/selfform/list.html", context)


def _qr(url: str) -> SafeString | None:
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


def _hours_from(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    if not (raw.isdecimal() and len(raw) <= _MAX_HOURS_DIGITS):
        raise service.SelfFormError("Хугацааг цагаар бүхэл тоогоор бичнэ үү.")
    return int(raw)


@login_required
def selfform_list(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage(user))
    return _render_list(request, SelfFormInvitationForm(user=user))


@login_required
@require_POST
def selfform_new(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage(user))
    form = SelfFormInvitationForm(request.POST, user=user)
    if not form.is_valid():
        return _render_list(request, form)
    try:
        invitation = service.create_invitation(
            label=form.cleaned_data["label"],
            branch=form.cleaned_data["branch"],
            hours=form.cleaned_data["hours"],
            by=user,
        )
    except service.SelfFormError as error:
        return _render_list(request, form, error=str(error))
    messages.success(request, "Холбоос үүсгэлээ. Энэ холбоосыг ажилтанд илгээнэ үү.")
    return redirect("employees:selfform_show", pk=invitation.pk)


@login_required
def selfform_show(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage(user))
    invitation = service.invitation_for(user, pk)
    url = service.invitation_url(invitation, request)
    key = _state_key(invitation, timezone.now())
    state, badge = _BADGES[key]
    context = {
        "inv": invitation,
        "state": state,
        "badge": badge,
        "state_key": key,
        "purged": invitation.purged_at is not None,
        "url": url,
        "qr": _qr(url),
        "default_hours": CompanySettings.get().selfform_default_hours,
        "hire_url": f"{reverse('employees:add')}?submission={invitation.pk}",
    }
    return render(request, "employees/selfform/show.html", context)


@login_required
@require_POST
def selfform_revoke(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage(user))
    invitation = service.invitation_for(user, pk)
    try:
        service.revoke(invitation, by=user)
    except service.SelfFormError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Холбоосыг цуцаллаа. Ажилтан энэ холбоосоор бөглөх боломжгүй болсон.")
    return redirect("employees:selfform_show", pk=pk)


@login_required
@require_POST
def selfform_extend(request: HttpRequest, pk: int) -> HttpResponse:
    user = _user(request)
    _require(access.can_manage(user))
    invitation = service.invitation_for(user, pk)
    try:
        service.extend(invitation, hours=_hours_from(request.POST.get("hours", "")), by=user)
    except service.SelfFormError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Холбоосын хугацааг сунгалаа.")
    return redirect("employees:selfform_show", pk=pk)


# The same texts as the service's own checks; the blank case is answered here, back on the hire page.
_NOTE_NEEDED = "Засах шалтгаанаа бичнэ үү."
_REASON_NEEDED = "Татгалзсан шалтгаанаа бичнэ үү."


@login_required
@require_POST
def selfform_send_back(request: HttpRequest, pk: int) -> HttpResponse:
    """HR sends the submitted form back to the employee with a note; the hire page is where HR came from."""
    user = _user(request)
    _require(access.can_manage(user))
    invitation = service.invitation_for(user, pk)
    note = request.POST.get("note", "")
    if not note.strip():
        messages.error(request, _NOTE_NEEDED)
        return redirect(f"{reverse('employees:add')}?submission={pk}")
    try:
        service.send_back(invitation, note=note, by=user)
    except service.SelfFormError as error:
        messages.error(request, str(error))
        return redirect("employees:selfforms")
    messages.success(request, "Анкетыг ажилтанд буцаалаа. Ажилтан засаад дахин илгээнэ.")
    return redirect("employees:selfforms")


@login_required
@require_POST
def selfform_reject(request: HttpRequest, pk: int) -> HttpResponse:
    """HR rejects the submitted form for good; the reason is kept on the invitation."""
    user = _user(request)
    _require(access.can_manage(user))
    invitation = service.invitation_for(user, pk)
    reason = request.POST.get("reason", "")
    if not reason.strip():
        messages.error(request, _REASON_NEEDED)
        return redirect(f"{reverse('employees:add')}?submission={pk}")
    try:
        service.reject(invitation, reason=reason, by=user)
    except service.SelfFormError as error:
        messages.error(request, str(error))
        return redirect("employees:selfforms")
    messages.success(request, "Анкетыг татгалзлаа. Ажилтан дахин бөглөх боломжгүй болсон.")
    return redirect("employees:selfforms")
