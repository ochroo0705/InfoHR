"""The HR screens of the employee self-form («Өөрөө бөглөх анкет»): the invitation list with its create form, the link
page with the QR code, and revoke and extend. The rules live in `employees.selfform.service`, the request-free screen
data in `employees.services.selfform_page`; this module draws the pages and turns the form posts into service calls.
Every view needs `macs.manage_employees`.
"""

from accounts.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from employees import access
from employees.selfform import service
from employees.selfform.forms import SelfFormInvitationForm
from employees.services import selfform_page


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _require(allowed: bool) -> None:
    if not allowed:
        raise PermissionDenied


def _render_list(request: HttpRequest, form: SelfFormInvitationForm, error: str = "") -> HttpResponse:
    user = _user(request)
    context = {
        "rows": selfform_page.list_rows(user, timezone.now()),
        "waiting": service.waiting_count(user),
        "form": form,
        "error": error,
    }
    return render(request, "employees/selfform/list.html", context)


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
    data = selfform_page.show_data(user, pk, request)
    context = {
        "inv": data.invitation,
        "state": data.state,
        "badge": data.badge,
        "state_key": data.state_key,
        "purged": data.purged,
        "url": data.url,
        "qr": data.qr_svg,
        "default_hours": data.default_hours,
        "hire_path": data.hire_path,
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
        service.extend(invitation, hours=selfform_page.parse_hours(request.POST.get("hours", "")), by=user)
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
