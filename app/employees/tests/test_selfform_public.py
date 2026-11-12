"""The public employee form: anonymous pages, the draft autosave, the final submit and the closed states."""

import json
import re
import secrets
from datetime import timedelta
from typing import Any

import pytest
from accounts.models import SystemLogEntry, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from macs.models import EducationLevel, FamilyRelation, ProfessionType

from employees.models import Employee, SelfFormInvitation, SelfFormStatus
from employees.selfform.answers import MAX_BODY_BYTES, MAX_PHOTO_BYTES, MSG_PHOTO_NOT_IMAGE, MSG_PHOTO_TOO_LARGE
from employees.selfform.service import create_invitation, mark_confirmed, revoke, send_back, submit

from .conftest import named

pytestmark = pytest.mark.django_db

REGISTER = "УБ99112233"
CLOSED_TEXT = "Энэ холбоос хаагдсан байна"
NOT_FOUND_TEXT = "Холбоос олдсонгүй"
DONE_TEXT = "Баярлалаа"
TICKS_TEXT = "Хоёр зөвшөөрлийн нүдийг тэмдэглэнэ үү."


@pytest.fixture(autouse=True)
def _fresh_throttle() -> None:
    cache.clear()


@pytest.fixture
def visitor() -> Client:
    return Client(enforce_csrf_checks=False)


@pytest.fixture
def invitation(actor: User) -> SelfFormInvitation:
    return create_invitation(label="Сараа", branch=None, hours=None, by=actor)


def form_url(token: str) -> str:
    return reverse("apply:form", args=[token])


def draft_url(token: str) -> str:
    return reverse("apply:draft", args=[token])


def person_values(**extra: Any) -> dict[str, Any]:
    base = {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": REGISTER,
        "birth_date": "1999-11-22",
        "gender": "F",
        "work_phone": "99112233",
    }
    return base | extra


def final_answers() -> dict[str, Any]:
    return {"person": person_values(), "education": [], "family": [], "contact": {}}


def full_post(*drop: str, **changes: Any) -> dict[str, Any]:
    """A complete, valid final submit as the browser sends it (form field names, both ticks)."""
    level = named(EducationLevel, "Бакалавр")
    profession = named(ProfessionType, "Нягтлан")
    relation = named(FamilyRelation, "Хүү")
    data: dict[str, Any] = {
        "person-family_name": "Батын",
        "person-given_name": "Сараа",
        "person-register_no": REGISTER,
        "person-birth_date": "1999-11-22",
        "person-gender": "F",
        "person-work_phone": "99112233",
        "person-clan_name": "",
        "person-email": "",
        "edu-0-org_name": "Монгол улсын их сургууль",
        "edu-0-start_year": "2010",
        "edu-0-end_year": "2014",
        "edu-0-edu_level": str(level.pk),
        "edu-0-profession_type": str(profession.pk),
        "fam-0-relation": str(relation.pk),
        "fam-0-given_name": "Бат",
        "fam-0-birth_date": "1970-01-01",
        "agreed_correct": "on",
        "consent": "on",
    }
    data |= changes
    for name in drop:
        data.pop(name, None)
    return data


def _expire(inv: SelfFormInvitation) -> None:
    inv.expires_at = timezone.now() - timedelta(minutes=1)
    inv.save(update_fields=["expires_at"])


def _stored(inv: SelfFormInvitation) -> SelfFormInvitation:
    return SelfFormInvitation.objects.get(pk=inv.pk)


def test_unknown_token_is_404(visitor: Client) -> None:
    response = visitor.get(form_url(secrets.token_urlsafe(24)))

    assert response.status_code == 404
    assert NOT_FOUND_TEXT in response.content.decode()
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "same-origin"


@pytest.mark.parametrize("token", ["a", "%20", "a" * 10_000])
def test_garbled_tokens_are_404_not_500(visitor: Client, token: str) -> None:
    response = visitor.get(f"/apply/{token}/")

    assert response.status_code == 404


def test_throttle_stops_token_guessing(visitor: Client) -> None:
    for _ in range(20):
        assert visitor.get(form_url(secrets.token_urlsafe(24))).status_code == 404

    response = visitor.get(form_url(secrets.token_urlsafe(24)))

    assert response.status_code == 429
    assert response["Cache-Control"] == "no-store"


def test_open_link_shows_form_without_login_and_no_store_headers(
    visitor: Client, invitation: SelfFormInvitation
) -> None:
    response = visitor.get(form_url(invitation.token))

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "same-origin"
    body = response.content.decode()
    assert '<form method="post"' in body
    assert 'name="csrfmiddlewaretoken"' in body
    assert 'name="person-given_name"' in body
    assert 'name="edu-0-org_name"' in body
    assert 'name="fam-0-given_name"' in body
    assert 'name="photo"' in body


def test_page_never_contains_other_employee_data(
    visitor: Client, invitation: SelfFormInvitation, hired: Employee
) -> None:
    body = visitor.get(form_url(invitation.token)).content.decode()

    assert REGISTER not in body
    assert "Батын" not in body
    assert "Сараа" not in body


@pytest.mark.parametrize("state", ["submitted", "revoked", "expired", "confirmed"])
def test_closed_page_for_submitted_revoked_expired_confirmed(
    visitor: Client, actor: User, invitation: SelfFormInvitation, hired: Employee, state: str
) -> None:
    if state in ("submitted", "confirmed"):
        submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True)
    if state == "confirmed":
        mark_confirmed(invitation.pk, hired, actor)
    if state == "revoked":
        revoke(invitation, by=actor)
    if state == "expired":
        _expire(invitation)
    stored_before = _stored(invitation)

    response = visitor.get(form_url(invitation.token))

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = response.content.decode()
    assert CLOSED_TEXT in body
    assert REGISTER not in body
    assert 'name="person-given_name"' not in body

    posted = visitor.post(form_url(invitation.token), full_post(**{"person-given_name": "Хакер"}))

    assert posted.status_code == 200
    if state == "submitted":  # a repeated send of a form already in: the done page, and the first answers stay
        assert DONE_TEXT in posted.content.decode()
    else:
        assert CLOSED_TEXT in posted.content.decode()
    assert "Хакер" not in posted.content.decode()
    assert _stored(invitation).answers == stored_before.answers
    assert _stored(invitation).status == stored_before.status


def test_draft_saves_and_reload_shows_it(visitor: Client, invitation: SelfFormInvitation) -> None:
    response = visitor.post(
        draft_url(invitation.token),
        {
            "person-given_name": "Сараа",
            "person-register_no": REGISTER,
            "edu-0-org_name": "Сургууль",
            "fam-0-given_name": "Бат",
        },
    )

    assert response.status_code == 204
    stored = json.loads(_stored(invitation).answers)
    assert stored["person"]["given_name"] == "Сараа"
    assert stored["education"][0]["org_name"] == "Сургууль"
    assert stored["family"][0]["given_name"] == "Бат"

    page = visitor.get(form_url(invitation.token)).content.decode()
    assert 'value="Сараа"' in page
    assert 'value="Сургууль"' in page


def test_draft_is_refused_without_csrf_token_and_accepted_with_it(invitation: SelfFormInvitation) -> None:
    strict = Client(enforce_csrf_checks=True)

    refused = strict.post(draft_url(invitation.token), {"person-given_name": "Бат"})
    assert refused.status_code == 403

    page = strict.get(form_url(invitation.token)).content.decode()
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
    assert match is not None
    accepted = strict.post(
        draft_url(invitation.token), {"csrfmiddlewaretoken": match.group(1), "person-given_name": "Бат"}
    )
    assert accepted.status_code == 204


def test_draft_rejects_oversized_body_and_too_many_rows(visitor: Client, invitation: SelfFormInvitation) -> None:
    too_big = visitor.post(
        draft_url(invitation.token), {"person-given_name": "Бат"}, CONTENT_LENGTH=str(MAX_BODY_BYTES + 1)
    )

    assert too_big.status_code == 413
    assert too_big.json() == {"error": "too_large"}

    many = {f"fam-{index}-given_name": "Бат" for index in range(500)}
    response = visitor.post(draft_url(invitation.token), many)

    assert response.status_code == 400
    assert "family" in response.json()["errors"]
    assert json.loads(_stored(invitation).answers) == {}


def test_draft_on_closed_invitation_is_409(visitor: Client, actor: User, invitation: SelfFormInvitation) -> None:
    revoke(invitation, by=actor)

    response = visitor.post(draft_url(invitation.token), {"person-given_name": "Бат"})

    assert response.status_code == 409
    assert response.json() == {"error": "closed"}


def test_submit_needs_both_ticks_in_the_post(visitor: Client, invitation: SelfFormInvitation) -> None:
    response = visitor.post(form_url(invitation.token), full_post("consent"))

    assert response.status_code == 400
    assert TICKS_TEXT in response.content.decode()
    assert _stored(invitation).status == SelfFormStatus.OPEN


def test_submit_success_creates_nothing_in_employee_table(visitor: Client, invitation: SelfFormInvitation) -> None:
    employees_before = Employee.objects.count()

    response = visitor.post(form_url(invitation.token), full_post())

    assert response.status_code == 200
    assert DONE_TEXT in response.content.decode()
    assert Employee.objects.count() == employees_before
    stored = _stored(invitation)
    assert stored.status == SelfFormStatus.SUBMITTED
    answers = json.loads(stored.answers)
    assert len(answers["education"]) == 1
    assert len(answers["family"]) == 1


def test_photo_upload_non_image_rejected_and_nothing_stored(visitor: Client, invitation: SelfFormInvitation) -> None:
    photo = SimpleUploadedFile("a.jpg", b"hello", content_type="image/jpeg")

    response = visitor.post(form_url(invitation.token), full_post(photo=photo))

    assert response.status_code == 400
    assert MSG_PHOTO_NOT_IMAGE in response.content.decode()
    stored = _stored(invitation)
    assert stored.status == SelfFormStatus.OPEN
    assert stored.photo_b64 == ""


def test_oversized_photo_rejected(visitor: Client, invitation: SelfFormInvitation) -> None:
    photo = SimpleUploadedFile("a.jpg", b"0" * (MAX_PHOTO_BYTES + 1), content_type="image/jpeg")

    response = visitor.post(form_url(invitation.token), full_post(photo=photo))

    assert response.status_code == 400
    assert MSG_PHOTO_TOO_LARGE in response.content.decode()
    assert _stored(invitation).photo_b64 == ""


def test_send_back_shows_original_answers_and_hr_note(
    visitor: Client, actor: User, invitation: SelfFormInvitation
) -> None:
    submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True)
    send_back(invitation, note="Регистрийн дугаараа шалгана уу", by=actor)

    body = visitor.get(form_url(invitation.token)).content.decode()

    assert "Регистрийн дугаараа шалгана уу" in body
    assert f'value="{REGISTER}"' in body
    assert 'value="Сараа"' in body


def test_submit_by_signed_in_user_is_audited_without_actor(
    visitor: Client, actor: User, invitation: SelfFormInvitation
) -> None:
    visitor.force_login(actor)

    response = visitor.post(form_url(invitation.token), full_post())

    assert response.status_code == 200
    entry = SystemLogEntry.objects.get(action="selfform_submitted")
    assert entry.actor is None
    assert entry.ip == "127.0.0.1"


def _assert_headers(response: Any) -> None:
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "same-origin"


def test_malformed_and_unknown_tokens_get_identical_404_with_headers(visitor: Client) -> None:
    unknown = visitor.get(form_url(secrets.token_urlsafe(24)))
    assert unknown.status_code == 404
    _assert_headers(unknown)

    for path in ("/apply/a/b/", "/apply/a%20b/", "/apply/" + "a%25" * 20 + "/"):
        response = visitor.get(path)
        assert response.status_code == 404
        assert response.content == unknown.content
        _assert_headers(response)


def test_csrf_refusal_and_method_refusal_carry_the_headers(invitation: SelfFormInvitation) -> None:
    refused = Client(enforce_csrf_checks=True).post(draft_url(invitation.token), {"person-given_name": "Бат"})
    assert refused.status_code == 403
    _assert_headers(refused)

    wrong_method = Client(enforce_csrf_checks=False).get(draft_url(invitation.token))
    assert wrong_method.status_code == 405
    _assert_headers(wrong_method)


def test_throttled_429_body_carries_the_headers(visitor: Client) -> None:
    for _ in range(20):
        visitor.get(form_url(secrets.token_urlsafe(24)))

    response = visitor.get(form_url(secrets.token_urlsafe(24)))

    assert response.status_code == 429
    assert "Хэт олон оролдлого" in response.content.decode()
    _assert_headers(response)


def test_too_many_fields_is_413_and_nothing_is_stored(
    visitor: Client, invitation: SelfFormInvitation, settings: Any
) -> None:
    settings.DATA_UPLOAD_MAX_NUMBER_FIELDS = 5

    draft = visitor.post(draft_url(invitation.token), {f"fam-{index}-given_name": "Бат" for index in range(10)})
    assert draft.status_code == 413
    assert draft.json() == {"error": "too_large"}
    _assert_headers(draft)

    final = visitor.post(form_url(invitation.token), full_post())
    assert final.status_code == 413
    assert "Оруулсан мэдээлэл хэт их байна" in final.content.decode()
    _assert_headers(final)
    stored = _stored(invitation)
    assert stored.status == SelfFormStatus.OPEN
    assert json.loads(stored.answers) == {}


def test_closed_page_hides_the_label_and_the_family_name(visitor: Client, actor: User) -> None:
    inv = create_invitation(label="Тестийн-Ажилтан-7731", branch=None, hours=None, by=actor)
    submit(inv, final_answers(), photo_b64="", agreed_correct=True, consent=True)

    body = visitor.get(form_url(inv.token)).content.decode()

    assert CLOSED_TEXT in body
    assert "Тестийн-Ажилтан-7731" not in body
    assert "Батын" not in body
    assert final_answers()["person"]["family_name"] == "Батын"


@pytest.mark.parametrize("state", ["expired", "submitted"])
def test_draft_after_expiry_or_submit_is_409(
    visitor: Client, actor: User, invitation: SelfFormInvitation, state: str
) -> None:
    if state == "expired":
        _expire(invitation)
    else:
        submit(invitation, final_answers(), photo_b64="", agreed_correct=True, consent=True)
    stored_before = _stored(invitation).answers

    response = visitor.post(draft_url(invitation.token), {"person-given_name": "Хакер"})

    assert response.status_code == 409
    assert response.json() == {"error": "closed"}
    _assert_headers(response)
    assert _stored(invitation).answers == stored_before


def test_final_post_without_csrf_token_is_refused_and_stores_nothing(invitation: SelfFormInvitation) -> None:
    strict = Client(enforce_csrf_checks=True)

    response = strict.post(form_url(invitation.token), full_post())

    assert response.status_code == 403
    _assert_headers(response)
    stored = _stored(invitation)
    assert stored.status == SelfFormStatus.OPEN
    assert json.loads(stored.answers) == {}


def test_final_post_with_csrf_token_submits(invitation: SelfFormInvitation) -> None:
    strict = Client(enforce_csrf_checks=True)
    page = strict.get(form_url(invitation.token)).content.decode()
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
    assert match is not None

    response = strict.post(form_url(invitation.token), full_post(csrfmiddlewaretoken=match.group(1)))

    assert response.status_code == 200
    assert DONE_TEXT in response.content.decode()
    assert _stored(invitation).status == SelfFormStatus.SUBMITTED


@pytest.mark.parametrize("path", ["/apply/a%2Fb/", "/apply/a/b%0A/"])
def test_encoded_slash_and_newline_paths_get_the_unknown_token_answer(visitor: Client, path: str) -> None:
    unknown = visitor.get(form_url(secrets.token_urlsafe(24)))

    response = visitor.get(path)

    assert response.status_code == 404
    assert response.content == unknown.content
    _assert_headers(response)


def test_public_pages_send_exact_same_origin_referrer_policy(visitor: Client, actor: User) -> None:
    """The exact header value on every public page kind: form, draft, unknown token and closed invitation."""
    inv = create_invitation(label="Сараа", branch=None, hours=None, by=actor)
    form = visitor.get(form_url(inv.token))
    draft = visitor.post(draft_url(inv.token), {"person-given_name": "Бат"})
    unknown = visitor.get(form_url(secrets.token_urlsafe(24)))
    revoke(inv, by=actor)
    closed = visitor.get(form_url(inv.token))

    for response in (form, draft, unknown, closed):
        assert response["Referrer-Policy"] == "same-origin"
        assert response["Cache-Control"] == "no-store"


def test_form_post_from_the_browser_origin_is_accepted_and_null_origin_is_refused(
    invitation: SelfFormInvitation,
) -> None:
    """Models the browser: with no-referrer the Send POST carried Origin: null and was refused with 403 by Django's
    CSRF origin check. With same-origin the browser sends the real origin, and the POST is accepted."""
    strict = Client(enforce_csrf_checks=True)
    page = strict.get(form_url(invitation.token)).content.decode()
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
    assert match is not None
    token = match.group(1)

    refused = strict.post(form_url(invitation.token), full_post(csrfmiddlewaretoken=token), HTTP_ORIGIN="null")

    assert refused.status_code == 403
    assert _stored(invitation).status == SelfFormStatus.OPEN

    accepted = strict.post(
        form_url(invitation.token),
        full_post(csrfmiddlewaretoken=token),
        HTTP_ORIGIN="http://testserver",
    )

    assert accepted.status_code == 200
    assert DONE_TEXT in accepted.content.decode()
    assert _stored(invitation).status == SelfFormStatus.SUBMITTED


def test_too_many_fields_under_csrf_is_django_400_with_headers_and_nothing_stored(
    invitation: SelfFormInvitation, settings: Any
) -> None:
    """Accepted behaviour: with CSRF enforced, CsrfViewMiddleware reads the POST before the view, so a body with too
    many fields gets Django's own bare 400 (the view's 413 branch is not reached). The headers are still added and
    nothing is stored."""
    settings.DATA_UPLOAD_MAX_NUMBER_FIELDS = 50
    strict = Client(enforce_csrf_checks=True)
    page = strict.get(form_url(invitation.token)).content.decode()
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
    assert match is not None
    many = {f"fam-{index}-given_name": "Бат" for index in range(60)} | {"csrfmiddlewaretoken": match.group(1)}

    for url in (draft_url(invitation.token), form_url(invitation.token)):
        response = strict.post(url, many)
        assert response.status_code == 400
        _assert_headers(response)

    stored = _stored(invitation)
    assert stored.status == SelfFormStatus.OPEN
    assert json.loads(stored.answers) == {}


def test_form_page_loads_the_stepper_script_deferred(visitor: Client, invitation: SelfFormInvitation) -> None:
    body = visitor.get(form_url(invitation.token)).content.decode()

    assert re.search(r'<script src="[^"]*selfform_apply\.js(\?[^"]*)?" defer></script>', body)


def test_form_page_loads_the_date_picker_before_the_stepper(visitor: Client, invitation: SelfFormInvitation) -> None:
    """The page does not extend base.html, so without this tag its date boxes show the browser's own popup."""
    body = visitor.get(form_url(invitation.token)).content.decode()

    assert re.search(r'<script src="[^"]*datepicker\.js(\?[^"]*)?" defer></script>', body)
    assert body.index("datepicker.js") < body.index("selfform_apply.js")


def test_form_page_names_the_draft_url_for_this_token(visitor: Client, invitation: SelfFormInvitation) -> None:
    body = visitor.get(form_url(invitation.token)).content.decode()

    assert f'data-draft-url="{draft_url(invitation.token)}"' in body


def test_form_page_has_four_steps_in_order(visitor: Client, invitation: SelfFormInvitation) -> None:
    body = visitor.get(form_url(invitation.token)).content.decode()

    steps = re.findall(r'data-step="([^"]+)"', body)
    assert steps == ["person", "education", "family-contact", "check-send"]


def test_form_page_has_row_templates_for_education_and_family(visitor: Client, invitation: SelfFormInvitation) -> None:
    body = visitor.get(form_url(invitation.token)).content.decode()

    assert '<template data-row-template="edu">' in body
    assert '<template data-row-template="fam">' in body
    assert 'name="edu-__i__-org_name"' in body
    assert 'name="fam-__i__-given_name"' in body


def test_send_button_is_enabled_in_the_html_so_a_page_without_javascript_can_send(
    visitor: Client, invitation: SelfFormInvitation
) -> None:
    body = visitor.get(form_url(invitation.token)).content.decode()

    send = re.search(r"<button[^>]*data-send[^>]*>", body)
    assert send is not None
    assert re.search(r"\sdisabled[\s>]", send.group(0)) is None


def test_failed_field_is_marked_for_the_stepper(visitor: Client, invitation: SelfFormInvitation) -> None:
    response = visitor.post(form_url(invitation.token), full_post(**{"person-register_no": "123"}))

    assert response.status_code == 400
    assert "data-has-error" in response.content.decode()


def test_purged_row_shows_closed_page_and_takes_no_answers(visitor: Client, invitation: SelfFormInvitation) -> None:
    from employees.selfform.service import purge_old

    _expire(invitation)
    assert purge_old(timezone.localdate() + timedelta(days=60)) == 1

    response = visitor.get(form_url(invitation.token))
    assert response.status_code == 200
    assert CLOSED_TEXT in response.content.decode()

    posted = visitor.post(form_url(invitation.token), full_post(**{"person-given_name": "Хакер"}))
    assert CLOSED_TEXT in posted.content.decode()
    assert "Хакер" not in posted.content.decode()
    assert _stored(invitation).answers == "{}"
    assert _stored(invitation).status == SelfFormStatus.OPEN


def _audit_count(action: str) -> int:
    return SystemLogEntry.objects.filter(action=action).count()


def test_second_send_after_success_shows_done_and_is_audited_once(
    visitor: Client, invitation: SelfFormInvitation
) -> None:
    first = visitor.post(form_url(invitation.token), full_post())
    assert first.status_code == 200
    assert DONE_TEXT in first.content.decode()

    second = visitor.post(form_url(invitation.token), full_post(**{"person-given_name": "Дахин"}))

    assert second.status_code == 200
    assert DONE_TEXT in second.content.decode()
    assert _audit_count("selfform_submitted") == 1
    stored = _stored(invitation)
    assert stored.status == SelfFormStatus.SUBMITTED
    assert "Дахин" not in stored.answers


def test_send_after_revoke_shows_the_closed_page(visitor: Client, actor: User, invitation: SelfFormInvitation) -> None:
    revoke(invitation, by=actor)

    response = visitor.post(form_url(invitation.token), full_post())

    assert response.status_code == 200
    assert CLOSED_TEXT in response.content.decode()
    assert DONE_TEXT not in response.content.decode()
    assert _audit_count("selfform_submitted") == 0


def test_form_page_carries_the_digest_of_the_notice_the_person_reads(
    visitor: Client, invitation: SelfFormInvitation
) -> None:
    from employees.models import CompanySettings
    from employees.selfform.notice import notice_digest, notice_for

    body = visitor.get(form_url(invitation.token)).content.decode()

    expected = notice_digest(notice_for(CompanySettings.get()))
    assert f'name="notice_digest" value="{expected}"' in body


def test_notice_changed_after_the_page_was_read_is_refused(visitor: Client, invitation: SelfFormInvitation) -> None:
    from employees.models import CompanySettings
    from employees.selfform.notice import notice_digest, notice_for

    body = visitor.get(form_url(invitation.token)).content.decode()
    digest = re.search(r'name="notice_digest" value="([0-9a-f]+)"', body)
    assert digest is not None
    settings_row = CompanySettings.get()
    settings_row.selfform_retention_days = settings_row.selfform_retention_days + 1
    settings_row.save()
    assert notice_digest(notice_for(settings_row)) != digest.group(1)

    response = visitor.post(form_url(invitation.token), full_post(notice_digest=digest.group(1)))

    assert response.status_code == 400
    assert "Зөвшөөрлийн текст өөрчлөгдсөн" in response.content.decode()
    stored = _stored(invitation)
    assert stored.status == SelfFormStatus.OPEN
    assert stored.consent_text == ""
    assert stored.consented_at is None
    assert stored.submitted_at is None


def test_matching_notice_digest_is_accepted(visitor: Client, invitation: SelfFormInvitation) -> None:
    body = visitor.get(form_url(invitation.token)).content.decode()
    digest = re.search(r'name="notice_digest" value="([0-9a-f]+)"', body)
    assert digest is not None

    response = visitor.post(form_url(invitation.token), full_post(notice_digest=digest.group(1)))

    assert response.status_code == 200
    assert DONE_TEXT in response.content.decode()
