"""Self-form submission transitions: save draft, submit, send back, reject and mark confirmed."""

import base64
import json
from datetime import timedelta
from typing import Any

import pytest
from accounts import audit_context
from accounts.models import SystemLogEntry, User
from django.utils import timezone

from employees.models import CompanySettings, Employee, SelfFormInvitation, SelfFormStatus
from employees.selfform.answers import AnswerErrors
from employees.selfform.service import (
    SelfFormError,
    create_invitation,
    mark_confirmed,
    reject,
    revoke,
    save_draft,
    send_back,
    submit,
)

pytestmark = pytest.mark.django_db

COMPANY = "Тест ХХК"


def person(**extra: Any) -> dict[str, Any]:
    base = {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": "УБ99112233",
        "birth_date": "1999-11-22",
        "gender": "F",
        "work_phone": "99112233",
    }
    return base | extra


def final_answers(**extra: Any) -> dict[str, Any]:
    return {"person": person(), "education": [], "family": [], "contact": {}} | extra


def photo(text: bytes = b"\xff\xd8\xff photo") -> str:
    return base64.b64encode(text).decode("ascii")


@pytest.fixture
def company() -> CompanySettings:
    row = CompanySettings.get()
    row.name = COMPANY
    row.save(update_fields=["name"])
    return row


@pytest.fixture
def invitation(actor: User) -> SelfFormInvitation:
    return create_invitation(label="Сараа", branch=None, hours=None, by=actor)


def _stored(inv: SelfFormInvitation) -> SelfFormInvitation:
    return SelfFormInvitation.objects.get(pk=inv.pk)


def _expire(inv: SelfFormInvitation) -> None:
    inv.expires_at = timezone.now() - timedelta(minutes=1)
    inv.save(update_fields=["expires_at"])


def _submitted(inv: SelfFormInvitation, *, photo_b64: str = "") -> SelfFormInvitation:
    submit(inv, final_answers(), photo_b64=photo_b64, agreed_correct=True, consent=True)
    return inv


def test_submit_moves_to_submitted_and_stores_consent(invitation: SelfFormInvitation, company: CompanySettings) -> None:
    submit(invitation, final_answers(), photo_b64=photo(), agreed_correct=True, consent=True)

    stored = SelfFormInvitation.objects.get(pk=invitation.pk)
    assert stored.status == SelfFormStatus.SUBMITTED
    assert stored.consented_at is not None
    assert stored.submitted_at is not None
    assert COMPANY in stored.consent_text
    assert "30" in stored.consent_text
    assert json.loads(stored.answers)["person"]["register_no"] == "УБ99112233"
    assert stored.photo_b64 == photo()
    # The passed-in object reflects the new state too, so callers need not reload it.
    assert invitation.status == SelfFormStatus.SUBMITTED


def test_submit_twice_second_is_refused_and_one_audit_entry(invitation: SelfFormInvitation) -> None:
    submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True)
    with pytest.raises(SelfFormError):
        submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True)

    assert SystemLogEntry.objects.filter(action="selfform_submitted").count() == 1


def test_submit_needs_both_ticks(invitation: SelfFormInvitation) -> None:
    with pytest.raises(SelfFormError):
        submit(invitation, final_answers(), photo_b64="", agreed_correct=False, consent=True)
    with pytest.raises(SelfFormError):
        submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=False)

    assert SelfFormInvitation.objects.get(pk=invitation.pk).status == SelfFormStatus.OPEN


def test_submit_after_expiry_refused(invitation: SelfFormInvitation) -> None:
    _expire(invitation)
    with pytest.raises(SelfFormError):
        submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True)

    assert SelfFormInvitation.objects.get(pk=invitation.pk).status == SelfFormStatus.OPEN


def test_submit_refuses_invalid_answers_and_keeps_status_open(invitation: SelfFormInvitation) -> None:
    with pytest.raises(AnswerErrors):
        submit(invitation, {"person": {}}, photo_b64="", agreed_correct=True, consent=True)

    assert SelfFormInvitation.objects.get(pk=invitation.pk).status == SelfFormStatus.OPEN


def test_submit_empty_photo_keeps_the_stored_photo(invitation: SelfFormInvitation) -> None:
    invitation.photo_b64 = photo(b"earlier")
    invitation.save(update_fields=["photo_b64"])
    submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True)

    assert SelfFormInvitation.objects.get(pk=invitation.pk).photo_b64 == photo(b"earlier")


def test_submit_audit_has_no_actor(invitation: SelfFormInvitation) -> None:
    submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True)

    entry = SystemLogEntry.objects.get(action="selfform_submitted")
    assert entry.actor is None


def test_save_draft_trims_whitespace_around_text(invitation: SelfFormInvitation) -> None:
    save_draft(invitation, {"person": {"given_name": "  Сараа  "}})

    stored = SelfFormInvitation.objects.get(pk=invitation.pk)
    assert stored.status == SelfFormStatus.OPEN
    assert json.loads(stored.answers)["person"]["given_name"] == "Сараа"


def test_submit_by_signed_in_staff_is_audited_without_actor_but_keeps_visitor_ip(
    actor: User, invitation: SelfFormInvitation
) -> None:
    audit_context.set_context(actor, "10.0.0.7")
    try:
        submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True)
        # The request's own user is put back after the submit.
        assert audit_context.current_user() == actor
    finally:
        audit_context.clear_context()

    entry = SystemLogEntry.objects.get(action="selfform_submitted")
    assert entry.actor is None
    assert entry.ip == "10.0.0.7"


def test_submit_after_send_back_keeps_earlier_photo_and_stores_fresh_consent_time(
    actor: User, invitation: SelfFormInvitation
) -> None:
    first = timezone.now()
    submit(invitation, final_answers(), photo_b64=photo(b"earlier"), agreed_correct=True, consent=True, now=first)
    send_back(invitation, note="Дахин шалгана уу", by=actor)

    later = first + timedelta(hours=1)
    submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True, now=later)

    stored = SelfFormInvitation.objects.get(pk=invitation.pk)
    assert stored.status == SelfFormStatus.SUBMITTED
    assert stored.photo_b64 == photo(b"earlier")
    assert stored.consented_at == later


def test_refused_transition_leaves_callers_object_unchanged(actor: User, invitation: SelfFormInvitation) -> None:
    with pytest.raises(SelfFormError):
        reject(invitation, reason="Шалтгаан", by=actor)  # not submitted yet
    with pytest.raises(SelfFormError):
        submit(invitation, final_answers(), photo_b64="", agreed_correct=False, consent=True)

    assert invitation.status == SelfFormStatus.OPEN
    assert invitation.reject_reason == ""
    assert invitation.reviewed_by_id is None
    assert invitation.answers == "{}"
    assert invitation.consented_at is None


def test_save_draft_refused_when_not_open(actor: User, invitation: SelfFormInvitation) -> None:
    revoke(invitation, by=actor)
    with pytest.raises(SelfFormError):
        save_draft(invitation, {"person": {}})


def test_send_back_reopens_with_note_and_fresh_72_hours_even_if_it_had_expired(
    actor: User, invitation: SelfFormInvitation
) -> None:
    _submitted(invitation)
    _expire(invitation)

    send_back(invitation, note="Регистрийн дугаараа шалгана уу", by=actor)

    stored = SelfFormInvitation.objects.get(pk=invitation.pk)
    assert stored.status == SelfFormStatus.OPEN
    assert stored.hr_note == "Регистрийн дугаараа шалгана уу"
    assert abs((stored.expires_at - (timezone.now() + timedelta(hours=72))).total_seconds()) < 5
    assert SystemLogEntry.objects.filter(action="selfform_sent_back").exists()


def test_send_back_requires_a_note(actor: User, invitation: SelfFormInvitation) -> None:
    _submitted(invitation)
    with pytest.raises(SelfFormError):
        send_back(invitation, note="   ", by=actor)

    assert SelfFormInvitation.objects.get(pk=invitation.pk).status == SelfFormStatus.SUBMITTED


def test_reject_requires_reason(actor: User, invitation: SelfFormInvitation) -> None:
    _submitted(invitation)
    with pytest.raises(SelfFormError):
        reject(invitation, reason="", by=actor)

    assert SelfFormInvitation.objects.get(pk=invitation.pk).status == SelfFormStatus.SUBMITTED


def test_reject_moves_submitted_to_rejected(actor: User, invitation: SelfFormInvitation) -> None:
    _submitted(invitation)
    reject(invitation, reason="Хуурамч мэдээлэл", by=actor)

    stored = SelfFormInvitation.objects.get(pk=invitation.pk)
    assert stored.status == SelfFormStatus.REJECTED
    assert stored.reject_reason == "Хуурамч мэдээлэл"
    assert SystemLogEntry.objects.filter(action="selfform_rejected").exists()


def test_mark_confirmed_sets_employee_and_reviewer(
    actor: User, invitation: SelfFormInvitation, hired: Employee
) -> None:
    _submitted(invitation)
    mark_confirmed(invitation.pk, hired, actor)

    stored = SelfFormInvitation.objects.get(pk=invitation.pk)
    assert stored.status == SelfFormStatus.CONFIRMED
    assert stored.employee_id == hired.pk
    assert stored.reviewed_by_id == actor.pk
    assert stored.reviewed_at is not None


def test_mark_confirmed_twice_second_raises(actor: User, invitation: SelfFormInvitation, hired: Employee) -> None:
    _submitted(invitation)
    mark_confirmed(invitation.pk, hired, actor)
    with pytest.raises(SelfFormError):
        mark_confirmed(invitation.pk, hired, actor)


def test_mark_confirmed_refused_when_not_submitted(
    actor: User, invitation: SelfFormInvitation, hired: Employee
) -> None:
    with pytest.raises(SelfFormError):
        mark_confirmed(invitation.pk, hired, actor)


def test_submit_with_the_digest_of_the_current_notice_is_accepted(
    invitation: SelfFormInvitation, company: CompanySettings
) -> None:
    from employees.selfform.notice import notice_digest, notice_for

    digest = notice_digest(notice_for(CompanySettings.get()))
    submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True, notice_digest=digest)

    assert _stored(invitation).status == SelfFormStatus.SUBMITTED


def test_submit_with_a_stale_notice_digest_is_refused_and_stores_nothing(
    invitation: SelfFormInvitation, company: CompanySettings
) -> None:
    from employees.selfform.notice import notice_digest, notice_for
    from employees.selfform.service import NoticeChangedError

    old_digest = notice_digest(notice_for(CompanySettings.get()))
    company.selfform_notice = "Шинэ текст: {company} {days} хоног."
    company.save(update_fields=["selfform_notice"])

    with pytest.raises(NoticeChangedError):
        submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True, notice_digest=old_digest)

    stored = _stored(invitation)
    assert stored.status == SelfFormStatus.OPEN
    assert stored.consent_text == ""
    assert stored.consented_at is None
