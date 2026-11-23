"""Self-form list and create under /api/v1/selfforms: the «Өөрөө бөглөх анкет» list screen as the React page reads it.

GET /selfforms answers the list rows, the count of submitted forms waiting for HR, the create form's description and the
page paragraph. POST /selfforms creates an invitation link through employees.selfform.service.create_invitation, after
the Django form employees.selfform.forms.SelfFormInvitationForm has checked the box values. A refused create (an invalid
form, a service refusal) answers 200 with ok false and nothing is written.

The rows come from employees.services.selfform_page; the HR decisions on one submission stay in api.hire
(selfform_router).
Only holders of macs.manage_employees may use these routes (403 "forbidden" for others, 401 for no login).
"""

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from accounts.models import User
from django import forms
from django.http import Http404, HttpRequest, HttpResponse
from django.urls import reverse
from django.utils import timezone
from employees import access
from employees.models import CompanySettings, SelfFormInvitation, SelfFormStatus
from employees.selfform import service
from employees.selfform.forms import MAX_HOURS, SelfFormInvitationForm
from employees.services import selfform_page
from ninja import Router, Schema
from ninja.security import django_auth

from api.errors import ApiError, form_error_payload
from api.popups import FORBIDDEN, request_user

selfform_list_router = Router(tags=["selfforms"])

# The page paragraph, copied from employees/selfform/list.html.
INTRO = (
    "Шинэ ажилтанд холбоос үүсгэж илгээнэ. Ажилтан утсаараа өөрийн мэдээллээ бөглөнө. "
    "Бөглөсөн маягт HR-ийн хяналтад хүлээгдэж, баталгаажсаны дараа л ажилтны бүртгэлд орно."
)
CREATED = "Холбоос үүсгэлээ. Энэ холбоосыг ажилтанд илгээнэ үү."  # the same text as the Django page's flash
_NO_BRANCH = "—"  # the list shows a dash for an invitation without a branch
_NOT_FOUND = "Хуудас олдсонгүй"  # the same message as the employee pages
_EXTENDED = "Холбоосын хугацааг сунгалаа."  # the same text as the Django page's flash
_REVOKED = "Холбоосыг цуцаллаа. Ажилтан энэ холбоосоор бөглөх боломжгүй болсон."  # the same text as the flash
_EXPIRES = "expires"
_SENT = "sent"


class SelfFormListRowOut(Schema):
    id: int
    label: str
    branch: str  # the branch name; «—» when none
    state: str  # the Mongolian state label
    badge: str  # the badge classes of the state
    when_label: str  # "" or "YYYY-MM-DD HH:MM" in local time
    when_kind: str  # "sent" (submitted: when is the submission time), "expires" (when is the expiry), "" for none
    show_path: str  # the invitation's page
    hire_path: str  # the hire page with this submission; "" unless submitted


class SelfFormBranchOut(Schema):
    value: int
    label: str


class SelfFormCreateLabelsOut(Schema):
    label: str
    branch: str
    hours: str


class SelfFormCreateHelpOut(Schema):
    label: str
    hours: str


class SelfFormCreateFormOut(Schema):
    branches: list[SelfFormBranchOut]  # the branches the user may pick, by name
    branch_required: bool  # a branch-limited user must pick one
    default_hours: int  # used when the hours box is empty
    max_hours: int
    labels: SelfFormCreateLabelsOut
    help: SelfFormCreateHelpOut


class SelfFormListOut(Schema):
    rows: list[SelfFormListRowOut]
    waiting: int  # submitted forms in the user's scope that wait for HR's decision
    form: SelfFormCreateFormOut
    intro: str


class SelfFormCreateIn(Schema):
    # Every box may be empty or null: the form answers with its own texts (React sends null for an empty box).
    label: str | None = None
    branch: int | None = None  # the Branch pk
    hours: int | None = None  # valid hours; None means the company default


class SelfFormNoticeOut(Schema):
    text: str


class SelfFormCreateOut(Schema):
    ok: bool
    id: int | None  # the new invitation's pk; None on a refusal
    show_path: str  # the new invitation's page; "" on a refusal
    field_errors: dict[str, list[str]]
    form_errors: list[str]
    notice: SelfFormNoticeOut | None  # the success text; None on a refusal


def _manager(request: HttpRequest) -> User:
    user = request_user(request)
    if not access.can_manage(user):
        raise ApiError(403, [FORBIDDEN], code="forbidden")
    return user


def _when_label(value: datetime | None) -> str:
    if value is None:
        return ""
    local = timezone.localtime(value) if timezone.is_aware(value) else value
    return local.strftime("%Y-%m-%d %H:%M")


def _row_out(row: selfform_page.ListRow) -> dict[str, object]:
    invitation = row.invitation
    submitted = invitation.status == SelfFormStatus.SUBMITTED  # the state key is "submitted" exactly then
    when_kind = "" if row.when is None else (_SENT if submitted else _EXPIRES)
    return {
        "id": invitation.pk,
        "label": invitation.label,
        "branch": invitation.branch.name if invitation.branch is not None else _NO_BRANCH,
        "state": row.state,
        "badge": row.badge,
        "when_label": _when_label(row.when),
        "when_kind": when_kind,
        "show_path": row.show_path,
        "hire_path": row.hire_path,
    }


def _create_form_out(user: User) -> dict[str, object]:
    form = SelfFormInvitationForm(user=user)
    branch = form.fields["branch"]
    assert isinstance(branch, forms.ModelChoiceField)
    return {
        "branches": [{"value": item.pk, "label": item.name} for item in branch.queryset],
        "branch_required": branch.required,
        "default_hours": CompanySettings.get().selfform_default_hours,
        "max_hours": MAX_HOURS,
        "labels": {
            "label": str(form.fields["label"].label),
            "branch": str(branch.label),
            "hours": str(form.fields["hours"].label),
        },
        "help": {
            "label": str(form.fields["label"].help_text),
            "hours": str(form.fields["hours"].help_text),
        },
    }


@selfform_list_router.get("", auth=django_auth, response=SelfFormListOut)
def selfform_list(request: HttpRequest) -> dict[str, object]:
    """The list rows (newest first, in the user's scope), the waiting count and the create form's description.
    403 without the manage right, 401 without a login."""
    user = _manager(request)
    return {
        "rows": [_row_out(row) for row in selfform_page.list_rows(user, timezone.now())],
        "waiting": service.waiting_count(user),
        "form": _create_form_out(user),
        "intro": INTRO,
    }


@selfform_list_router.post("", auth=django_auth, response=SelfFormCreateOut)
def selfform_create(request: HttpRequest, payload: SelfFormCreateIn) -> dict[str, object]:
    """Create an employee self-form link. Refused (ok false, status 200) when the form is invalid or the service
    refuses the create; nothing is written then. 403 without the manage right."""
    user = _manager(request)
    form = SelfFormInvitationForm(
        {"label": payload.label or "", "branch": payload.branch, "hours": payload.hours},
        user=user,
    )
    if not form.is_valid():
        return {"ok": False, "id": None, "show_path": "", "notice": None, **form_error_payload(form)}
    try:
        invitation = service.create_invitation(
            label=form.cleaned_data["label"],
            branch=form.cleaned_data["branch"],
            hours=form.cleaned_data["hours"],
            by=user,
        )
    except service.SelfFormError as error:
        return {
            "ok": False,
            "id": None,
            "show_path": "",
            "field_errors": {},
            "form_errors": [str(error)],
            "notice": None,
        }
    return {
        "ok": True,
        "id": invitation.pk,
        "show_path": reverse("employees:selfform_show", args=[invitation.pk]),
        "field_errors": {},
        "form_errors": [],
        "notice": {"text": CREATED},
    }


class SelfFormDecisionOut(Schema):
    reviewed_label: str  # "" or "YYYY-MM-DD HH:MM" in local time
    reviewed_by: str  # "" when nobody is recorded
    reject_reason: str  # filled for a rejected form only
    hr_note: str  # "" when HR wrote no note
    employee_path: str | None  # the employee's record, for a confirmed form with an employee


class SelfFormShowOut(Schema):
    id: int
    label: str
    state: str  # the Mongolian state label
    badge: str  # the badge classes of the state
    state_key: str  # "open", "expired", "submitted", "confirmed", "rejected" or "revoked"
    branch: str  # the branch name; «—» when none
    created_label: str  # "YYYY-MM-DD HH:MM" in local time
    when_label: str  # "" or "YYYY-MM-DD HH:MM": the submission time or the expiry
    when_title: Literal["Илгээсэн", "Дуусах", ""]  # the caption of when_label
    purged: bool  # the answers and the photo were cleared by the retention run
    link: str  # the link the employee opens; a secret
    qr_svg: str | None  # the QR code as inline SVG; None when it cannot be drawn
    can_extend: bool  # not purged, and open or expired
    can_revoke: bool  # not purged, and open
    default_hours: int  # used when the hours box is empty
    hire_path: str | None  # the hire page with this submission; only when submitted
    decision: SelfFormDecisionOut | None  # only for confirmed, rejected and revoked forms


class SelfFormExtendIn(Schema):
    hours: str | None = None  # typed hours; empty or null means the company default


class SelfFormActionNoticeOut(Schema):
    text: str
    tone: Literal["success", "error"]


class SelfFormActionOut(Schema):
    ok: bool
    notice: SelfFormActionNoticeOut
    show: SelfFormShowOut | None  # always the fresh state, so the page redraws from it


def _in_scope[T](lookup: Callable[[], T]) -> T:
    """Run a lookup of one invitation in the user's scope; one outside it is 404 with the code not_found."""
    try:
        return lookup()
    except Http404:
        raise ApiError(404, [_NOT_FOUND], code="not_found") from None


def _scoped_invitation(user: User, pk: int) -> SelfFormInvitation:
    return _in_scope(lambda: service.invitation_for(user, pk))


def _show_data(user: User, pk: int, request: HttpRequest) -> selfform_page.ShowData:
    return _in_scope(lambda: selfform_page.show_data(user, pk, request))


def _decision_out(data: selfform_page.ShowData) -> dict[str, object] | None:
    inv = data.invitation
    if data.state_key not in ("confirmed", "rejected", "revoked"):
        return None
    employee_path = None
    if data.state_key == "confirmed" and inv.employee_id is not None:
        employee_path = reverse("employees:detail", args=[inv.employee_id])
    return {
        "reviewed_label": _when_label(inv.reviewed_at),
        "reviewed_by": str(inv.reviewed_by) if inv.reviewed_by_id is not None else "",
        "reject_reason": inv.reject_reason if data.state_key == "rejected" else "",
        "hr_note": inv.hr_note or "",
        "employee_path": employee_path,
    }


def _show_out(data: selfform_page.ShowData) -> dict[str, object]:
    inv = data.invitation
    key = data.state_key
    submitted = key == "submitted"
    if submitted:
        when, title = _when_label(inv.submitted_at), "Илгээсэн"
    elif key in ("open", "expired"):
        when, title = _when_label(inv.expires_at), "Дуусах"
    else:
        when, title = "", ""
    return {
        "id": inv.pk,
        "label": inv.label,
        "state": data.state,
        "badge": data.badge,
        "state_key": key,
        "branch": inv.branch.name if inv.branch is not None else _NO_BRANCH,
        "created_label": _when_label(inv.created_at),
        "when_label": when,
        "when_title": title,
        "purged": data.purged,
        "link": data.url,
        "qr_svg": None if data.qr_svg is None else str(data.qr_svg),
        "can_extend": not data.purged and key in ("open", "expired"),
        "can_revoke": not data.purged and key == "open",
        "default_hours": data.default_hours,
        "hire_path": data.hire_path if submitted else None,
        "decision": _decision_out(data),
    }


def _action_out(
    user: User, pk: int, request: HttpRequest, *, ok: bool, text: str, tone: Literal["success", "error"]
) -> dict[str, object]:
    data = _show_data(user, pk, request)
    return {"ok": ok, "notice": {"text": text, "tone": tone}, "show": _show_out(data)}


@selfform_list_router.get("/{pk}", auth=django_auth, response=SelfFormShowOut)
def selfform_show_api(request: HttpRequest, response: HttpResponse, pk: int) -> dict[str, object]:
    """One self-form link with its state, the link itself (a secret, so the answer is no-store) and the HR decision.
    403 without the manage right, 404 (code not_found) outside the user's scope."""
    user = _manager(request)
    response["Cache-Control"] = "no-store"  # the link must not come back from the Back cache
    return _show_out(_show_data(user, pk, request))


@selfform_list_router.post("/{pk}/extend", auth=django_auth, response=SelfFormActionOut)
def selfform_extend_api(
    request: HttpRequest, response: HttpResponse, pk: int, payload: SelfFormExtendIn
) -> dict[str, object]:
    """Add hours to an open or expired link. A refusal (bad hours, not open, purged) answers ok false with the
    service's text and writes nothing. 403 without the manage right, 404 outside the user's scope."""
    user = _manager(request)
    response["Cache-Control"] = "no-store"  # the answer carries the link, a secret
    invitation = _scoped_invitation(user, pk)
    try:
        service.extend(invitation, hours=selfform_page.parse_hours(payload.hours or ""), by=user)
    except service.SelfFormError as error:
        return _action_out(user, pk, request, ok=False, text=str(error), tone="error")
    return _action_out(user, pk, request, ok=True, text=_EXTENDED, tone="success")


@selfform_list_router.post("/{pk}/revoke", auth=django_auth, response=SelfFormActionOut)
def selfform_revoke_api(request: HttpRequest, response: HttpResponse, pk: int) -> dict[str, object]:
    """Cancel the link so the employee cannot fill it any more. A refusal (already revoked, confirmed, ...) answers
    ok false with the service's text. 403 without the manage right, 404 outside the user's scope."""
    user = _manager(request)
    response["Cache-Control"] = "no-store"  # the answer carries the link, a secret
    invitation = _scoped_invitation(user, pk)
    try:
        service.revoke(invitation, by=user)
    except service.SelfFormError as error:
        return _action_out(user, pk, request, ok=False, text=str(error), tone="error")
    return _action_out(user, pk, request, ok=True, text=_REVOKED, tone="success")
