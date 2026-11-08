"""HR confirms a submitted self-form on the hire page: the hire POST links the submission, writes its education
and family rows, the emergency contact and (when HR uploads none) the employee's photo. Also send-back and reject.

Setup mirrors test_candidate_hook.py and test_selfform_review.py.
"""

import base64
import json
from datetime import timedelta
from io import BytesIO
from typing import Any

import pytest
from accounts.models import AccessScope, SystemLogEntry, User
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from macs.models import Branch, ContactType, EducationLevel, EmployeePhoto, FamilyRelation, ProfessionType
from PIL import Image
from recruitment.models import Candidate, Stage
from recruitment.services import pipeline
from recruitment.tests.conftest import make_vacancy

from employees.models import Employee, SelfFormInvitation, SelfFormStatus
from employees.selfform import service as selfform_service
from employees.selfform.service import create_invitation, submit
from employees.services import macs_writes, personal_rows
from employees.services import personal_writes as pw

from .conftest import named
from .test_views import add_payload, login_as

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
NEW_URL = "/employees/new/"
SUBMISSION_GONE_TEXT = "аль хэдийн шийдвэрлэгдсэн эсвэл буцаагдсан байна"
SUBMISSION_NOT_SENT_TEXT = "одоохондоо илгээгээгүй байна"
PHOTO_HINT = "зураг эвдэрсэн байна"
ROW_HINT = "«Буцаах» товчоор"
SAVED_REGISTER = "УБ99112233"
PERSON_POST = {
    "family_name": "Батын",
    "given_name": "Сараа",
    "register_no": SAVED_REGISTER,
    "birth_date": "1999-11-22",
    "gender": "F",
    "work_phone": "99112233",
    "email": "saraa@example.com",
    "clan_name": "Ногоон",
}


def _user_in(role: str, name: str, *, limit: list[int] | None = None) -> User:
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    if limit is not None:
        AccessScope.objects.create(user=user, limited=True, branch_ids=limit)
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _answers() -> dict[str, Any]:
    return {
        "person": {
            "family_name": "Батын",
            "given_name": "Сараа",
            "register_no": SAVED_REGISTER,
            "birth_date": "1999-11-22",
            "gender": "F",
            "work_phone": "99112233",
            "email": "saraa@example.com",
            "clan_name": "Ногоон",
        },
        "education": [],
        "family": [],
        "contact": {},
    }


def _jpeg(color: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (40, 50), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def _stored_photo(employee: Employee) -> bytes:
    return bytes(EmployeePhoto.objects.get(employee=employee).data or b"")


@pytest.fixture
def hr(db: None) -> User:
    return _user_in("HR", "hr_confirm")


@pytest.fixture
def lists() -> dict[str, Any]:
    return {
        "relation": named(FamilyRelation, "Хүү"),
        "contact": named(ContactType, "Утас"),
        "edu_level": named(EducationLevel, "Бакалавр"),
        "profession": named(ProfessionType, "Нягтлан"),
    }


def _rich(hr: User, lists: dict[str, Any], branch: Branch | None = None, photo_b64: str = "") -> SelfFormInvitation:
    """A submitted form with one education row, one family row and an emergency contact."""
    invitation = create_invitation(label="Сараа", branch=branch, hours=None, by=hr)
    answers = _answers()
    answers["education"] = [
        {
            "org_name": "Сүхбаатарын нэрэмжит сургууль",
            "start_year": 2005,
            "end_year": 2010,
            "edu_level": lists["edu_level"].pk,
            "profession_type": lists["profession"].pk,
        }
    ]
    answers["family"] = [{"relation": lists["relation"].pk, "given_name": "Нармандах", "surname": "Дорж"}]
    answers["contact"] = {
        "contact_type": lists["contact"].pk,
        "name": "Ээж",
        "relative": "Ээж",
        "value": "99887766",
    }
    submit(invitation, answers, photo_b64=photo_b64, agreed_correct=True, consent=True)
    return invitation


def _confirm_payload(job_values: dict[str, Any], lists: dict[str, Any], sub: SelfFormInvitation) -> dict[str, Any]:
    """What the hire page posts when HR confirms the prefilled form as it stands."""
    payload = add_payload(job_values, **PERSON_POST, submission=str(sub.pk))
    payload |= {
        "contact-contact_type": str(lists["contact"].pk),
        "contact-name": "Ээж",
        "contact-relative": "Ээж",
        "contact-value": "99887766",
    }
    return payload


def _post_confirm(client: Client, payload: dict[str, Any]) -> Any:
    return client.post(NEW_URL, payload)


def _employees_with_register() -> int:
    return Employee.objects.filter(register_no=SAVED_REGISTER).count()


def test_confirm_creates_employee_rows_and_links_submission(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any]
) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    response = _post_confirm(client, _confirm_payload(job_values, lists, sub))

    assert response.status_code == 302
    employee = Employee.objects.get(register_no=SAVED_REGISTER)
    assert (employee.family_name, employee.given_name) == ("Батын", "Сараа")
    assert len(personal_rows.rows("education", employee)) == 1
    assert len(personal_rows.rows("family", employee)) == 1
    assert len(personal_rows.rows("contact", employee)) == 1
    sub.refresh_from_db()
    assert sub.status == SelfFormStatus.CONFIRMED and sub.employee_id == employee.pk
    assert SystemLogEntry.objects.filter(action="selfform_confirmed").count() == 1


def test_confirm_uses_submission_photo_when_none_uploaded(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any]
) -> None:
    login_as(client, "HR", "hr_viewer")
    green = _jpeg("green")
    sub = _rich(hr, lists, photo_b64=base64.b64encode(green).decode("ascii"))
    assert _post_confirm(client, _confirm_payload(job_values, lists, sub)).status_code == 302

    employee = Employee.objects.get(register_no=SAVED_REGISTER)
    assert _stored_photo(employee) == green


def test_uploaded_photo_wins_over_submission_photo(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    login_as(client, "HR", "hr_viewer")
    green = _jpeg("green")
    sub = _rich(hr, lists, photo_b64=base64.b64encode(green).decode("ascii"))
    saved: list[bytes] = []
    real_save = macs_writes.save_photo

    def spy(employee: Employee, jpeg: bytes | None) -> None:
        saved.append(jpeg or b"")
        real_save(employee, jpeg)

    monkeypatch.setattr(macs_writes, "save_photo", spy)
    payload = _confirm_payload(job_values, lists, sub)
    payload["photo"] = SimpleUploadedFile("face.jpg", _jpeg("blue"), content_type="image/jpeg")
    assert _post_confirm(client, payload).status_code == 302

    assert len(saved) == 1 and saved[0] != green  # HR's upload was saved, the submission photo was not


def test_two_confirms_create_one_employee(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any]
) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    payload = _confirm_payload(job_values, lists, sub)
    assert _post_confirm(client, payload).status_code == 302
    count = Employee.objects.count()

    response = _post_confirm(client, payload)  # the same form, posted again from another tab
    assert response.status_code == 400
    assert SUBMISSION_GONE_TEXT in response.content.decode()
    assert Employee.objects.count() == count and _employees_with_register() == 1


def test_failed_hire_leaves_submission_submitted(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any]
) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    response = _post_confirm(client, _confirm_payload(job_values, lists, sub) | {"family_name": ""})

    assert response.status_code == 200
    assert f'name="submission" value="{sub.pk}"' in response.content.decode()  # still attached for a retry
    assert not Employee.objects.filter(register_no=SAVED_REGISTER).exists()
    sub.refresh_from_db()
    assert sub.status == SelfFormStatus.SUBMITTED and sub.employee_id is None


def test_personal_conflict_rolls_back_hire_and_leaves_submitted(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    real_add = pw.add

    def refuse_submission_rows(kind: str, *args: Any, **kwargs: Any) -> Any:
        if kind in ("education", "family"):  # only the self-form rows; the hire's own contact write goes through
            raise pw.PersonalConflict("Мөр бүртгэгдсэнгүй.")
        return real_add(kind, *args, **kwargs)

    monkeypatch.setattr(pw, "add", refuse_submission_rows)
    response = _post_confirm(client, _confirm_payload(job_values, lists, sub))

    assert response.status_code == 400 and "Мөр бүртгэгдсэнгүй." in response.content.decode()
    assert not Employee.objects.filter(register_no=SAVED_REGISTER).exists()
    sub.refresh_from_db()
    assert sub.status == SelfFormStatus.SUBMITTED and sub.employee_id is None


def test_duplicate_register_no_blocks_confirm_with_clear_message(
    client: Client, hr: User, hired: Employee, lists: dict[str, Any], job_values: dict[str, Any]
) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)  # same register number as the hired employee
    count = Employee.objects.count()
    response = _post_confirm(client, _confirm_payload(job_values, lists, sub))

    assert response.status_code == 200 and "аль хэдийн бүртгэлтэй" in response.content.decode()
    assert Employee.objects.count() == count
    sub.refresh_from_db()
    assert sub.status == SelfFormStatus.SUBMITTED


def test_row_that_no_longer_validates_blocks_confirm_with_send_back_hint(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any]
) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    broken = _answers() | {"education": [{"org_name": "Сургууль", "edu_level": 999999}]}
    SelfFormInvitation.objects.filter(pk=sub.pk).update(answers=json.dumps(broken, ensure_ascii=False))

    response = _post_confirm(client, _confirm_payload(job_values, lists, sub))
    assert response.status_code == 400 and ROW_HINT in response.content.decode()
    assert not Employee.objects.filter(register_no=SAVED_REGISTER).exists()
    sub.refresh_from_db()
    assert sub.status == SelfFormStatus.SUBMITTED


def test_send_back_and_reject_need_note_and_reason(client: Client, hr: User, lists: dict[str, Any]) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    rejected = _rich(hr, lists)

    back = client.post(f"/employees/self-forms/{sub.pk}/send-back/", {"note": "   "}, follow=True)
    assert back.redirect_chain[-1][0] == f"{NEW_URL}?submission={sub.pk}"
    assert "Засах шалтгаанаа бичнэ үү." in back.content.decode()

    reject = client.post(f"/employees/self-forms/{rejected.pk}/reject/", {"reason": ""}, follow=True)
    assert reject.redirect_chain[-1][0] == f"{NEW_URL}?submission={rejected.pk}"
    assert "Татгалзсан шалтгаанаа бичнэ үү." in reject.content.decode()

    sub.refresh_from_db()
    rejected.refresh_from_db()
    assert sub.status == SelfFormStatus.SUBMITTED and rejected.status == SelfFormStatus.SUBMITTED


def test_send_back_reopens_and_reject_closes(client: Client, hr: User, lists: dict[str, Any]) -> None:
    login_as(client, "HR", "hr_viewer")
    sent = _rich(hr, lists)
    refused = _rich(hr, lists)

    back = client.post(f"/employees/self-forms/{sent.pk}/send-back/", {"note": "Регистрээ шалгана уу"})
    assert back.status_code == 302 and back["Location"] == "/employees/self-forms/"
    sent.refresh_from_db()
    assert sent.status == SelfFormStatus.OPEN and sent.hr_note == "Регистрээ шалгана уу"

    reject = client.post(f"/employees/self-forms/{refused.pk}/reject/", {"reason": "Хуурамч мэдээлэл"})
    assert reject.status_code == 302 and reject["Location"] == "/employees/self-forms/"
    refused.refresh_from_db()
    assert refused.status == SelfFormStatus.REJECTED and refused.reject_reason == "Хуурамч мэдээлэл"


def test_send_back_and_reject_are_post_only(client: Client, hr: User, lists: dict[str, Any]) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    assert client.get(f"/employees/self-forms/{sub.pk}/send-back/").status_code == 405
    assert client.get(f"/employees/self-forms/{sub.pk}/reject/").status_code == 405


def test_branch_limited_user_cannot_open_other_branch_submission(hr: User, lists: dict[str, Any]) -> None:
    south = Branch.objects.create(name="Өмнөд")
    north = Branch.objects.create(name="Хойд")
    sub = _rich(hr, lists, branch=south)
    limited = _user_in("HR", "hr_north_only", limit=[north.pk])
    client = Client()
    client.force_login(limited)

    body = client.get(f"{NEW_URL}?submission={sub.pk}").content.decode()
    assert "Ажилтны өөрөө бөглөсөн анкет" not in body and 'name="submission"' not in body
    assert client.post(f"/employees/self-forms/{sub.pk}/send-back/", {"note": "x"}).status_code == 404
    assert client.post(f"/employees/self-forms/{sub.pk}/reject/", {"reason": "x"}).status_code == 404
    sub.refresh_from_db()
    assert sub.status == SelfFormStatus.SUBMITTED


def test_open_submission_not_reviewable_yet(client: Client, hr: User, job_values: dict[str, Any]) -> None:
    login_as(client, "HR", "hr_viewer")
    open_form = create_invitation(label="Сараа", branch=None, hours=None, by=hr)  # still open, not submitted

    body = client.get(f"{NEW_URL}?submission={open_form.pk}").content.decode()
    assert 'name="submission"' not in body

    response = client.post(NEW_URL, add_payload(job_values, submission=str(open_form.pk)))
    assert response.status_code == 400 and SUBMISSION_NOT_SENT_TEXT in response.content.decode()
    assert SUBMISSION_GONE_TEXT not in response.content.decode()
    assert not Employee.objects.filter(register_no="УК88010122").exists()
    open_form.refresh_from_db()
    assert open_form.status == SelfFormStatus.OPEN


def test_candidate_and_submission_hooks_do_not_interfere(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any], actor: User
) -> None:
    candidate: Candidate = pipeline.add_candidate(make_vacancy(), by=actor, surname="Дорж", given_name="Бат")
    other = _rich(hr, lists)  # a submitted form that this hire does not use
    login_as(client, "HR", "hr_viewer")

    response = client.post(NEW_URL, add_payload(job_values, candidate=str(candidate.pk)))

    assert response.status_code == 302
    candidate.refresh_from_db()
    assert candidate.stage == Stage.HIRED and candidate.employee_id is not None
    other.refresh_from_db()
    assert other.status == SelfFormStatus.SUBMITTED


@pytest.mark.parametrize(
    "answers",
    [
        "{not json",  # malformed JSON
        "[]",  # top level is a list, not an object
        '{"education": ["не объект"]}',  # a row that is not an object
        '{"education": 5}',  # the row list is not a list
    ],
)
def test_corrupt_stored_answers_refuse_confirm_with_hint(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any], answers: str
) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    SelfFormInvitation.objects.filter(pk=sub.pk).update(answers=answers)

    response = _post_confirm(client, _confirm_payload(job_values, lists, sub))
    assert response.status_code == 400 and ROW_HINT in response.content.decode()
    assert not Employee.objects.filter(register_no=SAVED_REGISTER).exists()
    sub.refresh_from_db()
    assert sub.status == SelfFormStatus.SUBMITTED and sub.employee_id is None


def test_corrupt_stored_photo_refuses_confirm_with_hint(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any]
) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    SelfFormInvitation.objects.filter(pk=sub.pk).update(photo_b64="!!! not a picture !!!")

    response = _post_confirm(client, _confirm_payload(job_values, lists, sub))
    assert response.status_code == 400 and PHOTO_HINT in response.content.decode()
    assert not Employee.objects.filter(register_no=SAVED_REGISTER).exists()
    sub.refresh_from_db()
    assert sub.status == SelfFormStatus.SUBMITTED and sub.employee_id is None


def test_resubmission_between_read_and_confirm_is_refused(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page read the submission; the employee sent it again before HR's confirm reached the lock."""
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    real_reviewable = selfform_service.reviewable_submission

    def resubmitted_after_read(user: User, raw: str | None) -> SelfFormInvitation | None:
        found = real_reviewable(user, raw)
        SelfFormInvitation.objects.filter(pk=sub.pk).update(submitted_at=timezone.now() + timedelta(minutes=5))
        return found

    monkeypatch.setattr("employees.views.reviewable_submission", resubmitted_after_read)
    response = _post_confirm(client, _confirm_payload(job_values, lists, sub))

    assert response.status_code == 400 and SUBMISSION_GONE_TEXT in response.content.decode()
    assert not Employee.objects.filter(register_no=SAVED_REGISTER).exists()
    sub.refresh_from_db()
    assert sub.status == SelfFormStatus.SUBMITTED and sub.employee_id is None


def test_second_confirm_refused_inside_transaction_rolls_hire_back(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second POST passes the pre-check (it still sees the submission as waiting) and is refused only by the
    lock inside the hire transaction: the second hire is rolled back and nothing else is written."""
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    waiting_copy = SelfFormInvitation.objects.get(pk=sub.pk)  # still submitted, as the second tab saw it
    assert _post_confirm(client, _confirm_payload(job_values, lists, sub)).status_code == 302
    count = Employee.objects.count()

    writes: list[str] = []
    real_add = pw.add
    real_save = macs_writes.save_photo

    def counting_add(kind: str, *args: Any, **kwargs: Any) -> Any:
        writes.append(kind)
        return real_add(kind, *args, **kwargs)

    def counting_save(employee: Employee, jpeg: bytes | None) -> None:
        writes.append("photo")
        real_save(employee, jpeg)

    monkeypatch.setattr("employees.views.reviewable_submission", lambda user, raw: waiting_copy)
    monkeypatch.setattr(pw, "add", counting_add)
    monkeypatch.setattr(macs_writes, "save_photo", counting_save)
    # a different register number, so the duplicate check of the hire form does not stop the request first
    payload = _confirm_payload(job_values, lists, sub) | {"register_no": "УК77000011"}
    response = _post_confirm(client, payload)

    assert response.status_code == 400 and SUBMISSION_GONE_TEXT in response.content.decode()
    assert Employee.objects.count() == count
    assert not Employee.objects.filter(register_no="УК77000011").exists()
    # the hire's own contact write is rolled back with the hire; no self-form row and no photo was written
    assert not {"education", "family", "photo"} & set(writes)


@pytest.mark.parametrize("refusal", ["sent_back", "rejected"])
def test_refused_submission_keeps_its_id_so_a_second_save_is_refused_too(
    client: Client, hr: User, lists: dict[str, Any], job_values: dict[str, Any], refusal: str
) -> None:
    login_as(client, "HR", "hr_viewer")
    sub = _rich(hr, lists)
    if refusal == "sent_back":
        selfform_service.send_back(sub, note="Регистрээ шалгана уу", by=hr)
    else:
        selfform_service.reject(sub, reason="Тохирохгүй", by=hr)
    payload = _confirm_payload(job_values, lists, sub)
    employees_before = Employee.objects.count()

    first = _post_confirm(client, payload)

    assert first.status_code == 400
    body = first.content.decode()
    assert f'name="submission" value="{sub.pk}"' in body  # the id stays in the form
    assert "Ажилтны өөрөө бөглөсөн анкет" not in body  # and no review panel for a refused form
    second = _post_confirm(client, payload)  # Save again, with the hidden id
    assert second.status_code == 400
    assert Employee.objects.count() == employees_before
    assert not Employee.objects.filter(register_no=SAVED_REGISTER).exists()
