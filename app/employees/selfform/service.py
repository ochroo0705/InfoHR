"""Employee self-form invitations: create, look up by token, expiry, visibility, revoke and extend.

Spec: docs/superpowers/specs/2026-11-08-employee-self-form-design.md
"""

import json
import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from typing import Any

from accounts import audit_context
from accounts.audit import Category, record_safe
from accounts.models import User
from django.db import transaction
from django.db.models import QuerySet
from django.http import Http404, HttpRequest
from django.urls import reverse
from django.utils import timezone
from macs.models import Branch

from employees.access import branch_choices, branch_required, can_manage
from employees.models import CompanySettings, Employee, SelfFormInvitation, SelfFormStatus
from employees.selfform.answers import validate_answers
from employees.selfform.notice import notice_digest as digest_of_notice
from employees.selfform.notice import notice_for

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
_BIG_COLUMNS = ("photo_b64", "answers")  # long text columns; list queries leave them out
_TARGET_TYPE = "Ажилтны маягт"
_MAX_HOURS = 24 * 365  # one year: keeps timedelta and datetime arithmetic far from overflow
_NOT_FILLABLE = "Энэ маягтыг одоо бөглөх боломжгүй байна."
_NOT_SUBMITTED = "Зөвхөн илгээсэн маягтад энэ үйлдлийг хийнэ."
_NOTICE_CHANGED = "Зөвшөөрлийн текст өөрчлөгдсөн байна. Хуудсыг дахин ачаалж, текстийг дахин уншина уу."
_PURGED = "Хариулт устгагдсан тул энэ холбоосыг сунгах, дахин нээх боломжгүй. Шинэ урилга үүсгэнэ үү."
_REVIEW_FIELDS = ("status", "reviewed_by", "reviewed_at")


class SelfFormError(Exception):
    """A refusal the user should see; the message is shown as it is."""


class NoticeChangedError(SelfFormError):
    """The consent text changed after the person read it: the form must be read again before sending."""


def _hours_or_default(hours: int | None) -> int:
    value = CompanySettings.get().selfform_default_hours if hours is None else hours
    if value < 1:
        raise SelfFormError("Хугацаа дор хаяж 1 цаг байх ёстой.")
    if value > _MAX_HOURS:
        raise SelfFormError(f"Хугацаа {_MAX_HOURS} цагаас (нэг жил) хэтрэхгүй байх ёстой.")
    return value


def create_invitation(*, label: str, branch: Branch | None, hours: int | None, by: User) -> SelfFormInvitation:
    label = label.strip()
    if not label:
        raise SelfFormError("Ажилтны нэрийг оруулна уу.")
    if branch is None and branch_required(by):
        raise SelfFormError("Салбараа сонгоно уу.")
    if branch is not None and not branch_choices(by).filter(pk=branch.pk).exists():
        raise SelfFormError("Энэ салбарт маягт илгээх эрх байхгүй.")
    expires_at = timezone.now() + timedelta(hours=_hours_or_default(hours))
    invitation = SelfFormInvitation.objects.create(
        token=secrets.token_urlsafe(24),
        label=label,
        branch=branch,
        created_by=by,
        expires_at=expires_at,
    )
    record_safe(Category.HR, "selfform_created", actor=by, target_type=_TARGET_TYPE, target_label=label)
    return invitation


def get_for_token(token: str) -> SelfFormInvitation | None:
    if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
        return None
    return SelfFormInvitation.objects.filter(token=token).first()


def is_expired(inv: SelfFormInvitation, now: datetime | None = None) -> bool:
    now = now or timezone.now()
    return inv.status == SelfFormStatus.OPEN and inv.expires_at <= now


def is_fillable(inv: SelfFormInvitation, now: datetime | None = None) -> bool:
    # A purged row has empty answers: it must never be filled in again.
    return inv.status == SelfFormStatus.OPEN and inv.purged_at is None and not is_expired(inv, now)


def _scoped(user: User) -> QuerySet[SelfFormInvitation]:
    """Every invitation the user may see: all, or only those in their branches when they are branch-limited."""
    invitations = SelfFormInvitation.objects.all()
    if branch_required(user):
        invitations = invitations.filter(branch__in=branch_choices(user))
    return invitations


def visible_invitations(user: User) -> QuerySet[SelfFormInvitation]:
    return _scoped(user).defer(*_BIG_COLUMNS)


def invitation_for(user: User, pk: int) -> SelfFormInvitation:
    """One invitation in the user's scope, without the answers and the photo (no HR screen that uses them reads
    them here; the hire page reads the full row through reviewable_submission)."""
    invitation = _scoped(user).defer(*_BIG_COLUMNS).filter(pk=pk).first()
    if invitation is None:
        raise Http404
    return invitation


def positive_id(raw: str | None) -> int | None:
    """A positive integer id from posted or typed text, or None for anything else (garbage, zero, negatives)."""
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdigit() or len(raw) > 18:
        return None
    value = int(raw)
    return value if value > 0 else None


def reviewable_submission(user: User, raw: str | None) -> SelfFormInvitation | None:
    """The full submitted row HR may review now, or None. A bad, foreign or not-submitted value is ignored silently."""
    pk = positive_id(raw)
    if pk is None or not can_manage(user):
        return None
    return _scoped(user).filter(pk=pk, status=SelfFormStatus.SUBMITTED).first()


def waiting_count(user: User) -> int:
    """How many submitted invitations in the user's scope wait for HR's decision (one COUNT query)."""
    return _scoped(user).filter(status=SelfFormStatus.SUBMITTED).count()


def visible_status(user: User, raw: str | None) -> str | None:
    """The status of the invitation when it is in the user's scope; None for a bad, foreign or unknown value."""
    pk = positive_id(raw)
    if pk is None:
        return None
    found = _scoped(user).filter(pk=pk).only("status").first()
    return None if found is None else str(found.status)


def revoke(inv: SelfFormInvitation, *, by: User) -> None:
    with transaction.atomic():
        locked = _locked(inv.pk)
        if locked.status not in (SelfFormStatus.OPEN, SelfFormStatus.SUBMITTED):
            raise SelfFormError("Энэ маягтын холбоосыг цуцлах боломжгүй.")
        # HR's cancel is a decision: it starts the retention clock (purge_old counts revoked rows from reviewed_at).
        locked.status = SelfFormStatus.REVOKED
        locked.reviewed_by = by
        locked.reviewed_at = timezone.now()
        locked.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        record_safe(Category.HR, "selfform_revoked", actor=by, target_type=_TARGET_TYPE, target_label=locked.label)
    _sync(inv, locked, _REVIEW_FIELDS)


def extend(inv: SelfFormInvitation, *, hours: int | None, by: User) -> None:
    with transaction.atomic():
        locked = _locked(inv.pk)
        if locked.purged_at is not None:
            raise SelfFormError(_PURGED)
        if locked.status != SelfFormStatus.OPEN:
            raise SelfFormError("Зөвхөн нээлттэй холбоосын хугацааг сунгана.")
        locked.expires_at = timezone.now() + timedelta(hours=_hours_or_default(hours))
        locked.save(update_fields=["expires_at"])
        record_safe(Category.HR, "selfform_extended", actor=by, target_type=_TARGET_TYPE, target_label=locked.label)
    _sync(inv, locked, ("expires_at",))


def invitation_url(inv: SelfFormInvitation, request: HttpRequest) -> str:
    # The URL name apply:form is created by a later task, so reverse() runs only when this is called.
    path = reverse("apply:form", args=[inv.token])
    base = CompanySettings.get().selfform_base_url.strip().rstrip("/")
    return base + path if base else request.build_absolute_uri(path)


def qr_svg(url: str) -> str:
    """The QR code of `url` as an inline SVG string (no XML header, no external references). segno is imported
    here so that a missing package fails only the screens that draw a code, not the whole app."""
    import segno  # lazy: the package is needed only where a code is drawn

    return str(segno.make(url, error="m").svg_inline(scale=8, border=2))


def purge_old(today: date) -> int:
    """Clear the stored answers and photo of invitations whose outcome is older than the retention period.

    The outcome date (the date from which the retention period counts) is:
    - confirmed, rejected, revoked: reviewed_at (the day HR decided, or the day HR cancelled the link; revoke()
      stamps it);
    - open: expires_at. An abandoned draft counts from its expiry; this includes an invitation HR sent back that
      the employee never finished. An open invitation that has not expired yet is never purged.
    - submitted: never purged. The employee sent it and HR has not decided yet; wiping it would lose data.

    Only answers and photo_b64 are cleared. Who, when, the outcome, the label and the consent text stay.
    Rows already purged are skipped, so a second run purges nothing. One audit entry is written when any row is.
    Returns the number of rows purged.
    """
    days = CompanySettings.get().selfform_retention_days
    # "Older than N days before today": the outcome must fall before the start of the day N days ago.
    cutoff = timezone.make_aware(datetime.combine(today - timedelta(days=days), time.min))
    cleared = {"answers": "{}", "photo_b64": "", "purged_at": timezone.now()}
    live = SelfFormInvitation.objects.filter(purged_at__isnull=True)
    with audit_context.system(), transaction.atomic():
        purged = live.filter(status=SelfFormStatus.CONFIRMED, reviewed_at__lt=cutoff).update(**cleared)
        purged += live.filter(status=SelfFormStatus.REJECTED, reviewed_at__lt=cutoff).update(**cleared)
        purged += live.filter(status=SelfFormStatus.REVOKED, reviewed_at__lt=cutoff).update(**cleared)
        purged += live.filter(status=SelfFormStatus.OPEN, expires_at__lt=cutoff).update(**cleared)
        if purged:
            record_safe(
                Category.HR,
                "selfform_purged",
                actor=None,
                message=f"{purged} маягтын хадгалсан хариулт, зургийг устгасан",
            )
    return purged


def _locked(pk: int) -> SelfFormInvitation:
    """The row, locked for the rest of the surrounding transaction. Decide on this copy, not on the caller's object."""
    return SelfFormInvitation.objects.select_for_update().get(pk=pk)


@contextmanager
def _no_logged_in_user() -> Iterator[None]:
    """Audit entries written inside this block have no actor. "System" here only means "no logged-in user": the
    visitor's IP stays on the entry. (audit_context.system() would clear the IP as well, so it is not used.)"""
    user = audit_context.current_user()
    ip = audit_context.current_ip()
    audit_context.set_context(None, ip)
    try:
        yield
    finally:
        audit_context.set_context(user, ip)


def _sync(inv: SelfFormInvitation, locked: SelfFormInvitation, names: tuple[str, ...]) -> None:
    """Copy the new state onto the caller's object so it does not show a stale status."""
    for name in names:
        setattr(inv, name, getattr(locked, name))


def save_draft(inv: SelfFormInvitation, answers: dict[str, Any]) -> None:
    """Keep what the employee has typed so far. Field errors do not refuse a draft; the status does not change."""
    with transaction.atomic():
        locked = _locked(inv.pk)
        if not is_fillable(locked):
            raise SelfFormError(_NOT_FILLABLE)
        cleaned = validate_answers(answers, final=False)
        locked.answers = json.dumps(cleaned, ensure_ascii=False)
        locked.save(update_fields=["answers"])
    _sync(inv, locked, ("answers",))


def submit(
    inv: SelfFormInvitation,
    answers: dict[str, Any],
    *,
    photo_b64: str,
    agreed_correct: bool,
    consent: bool,
    notice_digest: str | None = None,
    now: datetime | None = None,
) -> None:
    """The employee's final submit. An empty photo_b64 keeps the photo already stored (a send-back case).

    notice_digest is the digest of the consent text the person read (the hidden input of the form). When given and it
    is not the digest of the text in force now, the submit is refused, so the consent stored is the text they saw.
    """
    with transaction.atomic():
        locked = _locked(inv.pk)
        if not is_fillable(locked, now):
            raise SelfFormError(_NOT_FILLABLE)
        if not (agreed_correct and consent):
            raise SelfFormError("Хоёр зөвшөөрлийн нүдийг тэмдэглэнэ үү.")
        notice = notice_for(CompanySettings.get())
        if notice_digest is not None and notice_digest != digest_of_notice(notice):
            raise NoticeChangedError(_NOTICE_CHANGED)
        cleaned = validate_answers(answers, final=True)
        moment = now or timezone.now()
        locked.answers = json.dumps(cleaned, ensure_ascii=False)
        if photo_b64:
            locked.photo_b64 = photo_b64
        locked.consent_text = notice
        locked.consented_at = moment
        locked.submitted_at = moment
        locked.status = SelfFormStatus.SUBMITTED
        locked.save(update_fields=["answers", "photo_b64", "consent_text", "consented_at", "submitted_at", "status"])
        # The public form has no login: the entry gets no actor even when a staff member is signed in on this
        # browser. The visitor's IP is kept.
        ip = audit_context.current_ip()
        with _no_logged_in_user():
            record_safe(
                Category.HR,
                "selfform_submitted",
                actor=None,
                ip=ip,
                target_type=_TARGET_TYPE,
                target_label=locked.label,
            )
    _sync(inv, locked, ("answers", "photo_b64", "consent_text", "consented_at", "submitted_at", "status"))


def send_back(inv: SelfFormInvitation, *, note: str, by: User) -> None:
    """HR sends a submitted form back to the employee: open again, with a note and fresh default hours."""
    note = note.strip()
    if not note:
        raise SelfFormError("Засах шалтгаанаа бичнэ үү.")
    with transaction.atomic():
        locked = _locked(inv.pk)
        if locked.purged_at is not None:
            raise SelfFormError(_PURGED)
        if locked.status != SelfFormStatus.SUBMITTED:
            raise SelfFormError(_NOT_SUBMITTED)
        moment = timezone.now()
        locked.status = SelfFormStatus.OPEN
        locked.hr_note = note
        locked.expires_at = moment + timedelta(hours=_hours_or_default(None))
        locked.reviewed_by = by
        locked.reviewed_at = moment
        locked.save(update_fields=["status", "hr_note", "expires_at", "reviewed_by", "reviewed_at"])
        record_safe(Category.HR, "selfform_sent_back", actor=by, target_type=_TARGET_TYPE, target_label=locked.label)
    _sync(inv, locked, ("status", "hr_note", "expires_at", "reviewed_by", "reviewed_at"))


def reject(inv: SelfFormInvitation, *, reason: str, by: User) -> None:
    reason = reason.strip()
    if not reason:
        raise SelfFormError("Татгалзсан шалтгаанаа бичнэ үү.")
    with transaction.atomic():
        locked = _locked(inv.pk)
        if locked.status != SelfFormStatus.SUBMITTED:
            raise SelfFormError(_NOT_SUBMITTED)
        locked.status = SelfFormStatus.REJECTED
        locked.reject_reason = reason
        locked.reviewed_by = by
        locked.reviewed_at = timezone.now()
        locked.save(update_fields=["status", "reject_reason", "reviewed_by", "reviewed_at"])
        record_safe(Category.HR, "selfform_rejected", actor=by, target_type=_TARGET_TYPE, target_label=locked.label)
    _sync(inv, locked, _REVIEW_FIELDS + ("reject_reason",))


def mark_confirmed(inv_id: int, employee: Employee, by: User) -> SelfFormInvitation:
    """Called by the hire view inside the hire transaction: the submitted form is now this employee's record.

    Returns the locked row as it is now, so the caller can check it still matches what the page showed.
    """
    with transaction.atomic():
        locked = _locked(inv_id)
        if locked.status != SelfFormStatus.SUBMITTED:
            raise SelfFormError(_NOT_SUBMITTED)
        locked.status = SelfFormStatus.CONFIRMED
        locked.employee = employee
        locked.reviewed_by = by
        locked.reviewed_at = timezone.now()
        locked.save(update_fields=["status", "employee", "reviewed_by", "reviewed_at"])
        record_safe(Category.HR, "selfform_confirmed", actor=by, target_type=_TARGET_TYPE, target_label=locked.label)
        return locked
