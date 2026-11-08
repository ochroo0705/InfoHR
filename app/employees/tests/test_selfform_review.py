"""HR review of a submitted self-form on the hire page: prefill, the read-only panel, the duplicate warning and the
hidden `submission` field. Confirming (the POST side) is a later task."""

import json
import re
from typing import Any

import pytest
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.test import Client
from macs.models import Branch, ContactType, EducationLevel, FamilyRelation, ProfessionType

from employees.models import Employee, SelfFormInvitation, SelfFormStatus
from employees.selfform import review
from employees.selfform.service import create_invitation, submit

from .conftest import named
from .test_views import add_payload, login_as

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
NEW_URL = "/employees/new/"
PANEL_TITLE = "Ажилтны өөрөө бөглөсөн анкет"
GENERIC_DUPLICATE = "Энэ регистрийн дугаартай ажилтан бүртгэлтэй байна"


def _user_in(role: str, name: str, *, limit: list[int] | None = None) -> User:
    user = User.objects.create_user(name, password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    if limit is not None:
        AccessScope.objects.create(user=user, limited=True, branch_ids=limit)
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _answers(**person: Any) -> dict[str, Any]:
    base = {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": "уб 99112233",
        "birth_date": "1999-11-22",
        "gender": "F",
        "work_phone": "99112233",
        "email": "saraa@example.com",
        "clan_name": "Ногоон",
    }
    return {"person": base | person, "education": [], "family": [], "contact": {}}


def _submitted(user: User, *, branch: Branch | None = None, photo_b64: str = "", **person: Any) -> SelfFormInvitation:
    invitation = create_invitation(label="Сараа", branch=branch, hours=None, by=user)
    submit(invitation, _answers(**person), photo_b64=photo_b64, agreed_correct=True, consent=True)
    return invitation


@pytest.fixture
def hr(db: None) -> User:
    return _user_in("HR", "hr_review")


@pytest.fixture
def lists() -> dict[str, Any]:
    return {
        "relation": named(FamilyRelation, "Хүү"),
        "contact": named(ContactType, "Утас"),
        "edu_level": named(EducationLevel, "Бакалавр"),
        "profession": named(ProfessionType, "Нягтлан"),
    }


def _rich(hr: User, lists: dict[str, Any]) -> SelfFormInvitation:
    """A submitted form with one education row, one family row and an emergency contact."""
    invitation = create_invitation(label="Сараа", branch=None, hours=None, by=hr)
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
    submit(invitation, answers, photo_b64="", agreed_correct=True, consent=True)
    return invitation


def test_get_prefills_person_and_contact_from_submission(client: Client, hr: User, lists: dict[str, Any]) -> None:
    login_as(client, "HR", "hr_viewer")
    invitation = _rich(hr, lists)
    body = client.get(f"{NEW_URL}?submission={invitation.pk}").content.decode()

    assert 'name="family_name" value="Батын"' in body
    assert 'name="given_name" value="Сараа"' in body
    assert 'name="register_no" value="УБ99112233"' in body  # normalized, as stored
    assert 'name="birth_date" value="1999-11-22"' in body
    assert 'value="F" selected' in body
    assert 'name="work_phone" value="99112233"' in body
    assert 'name="email" value="saraa@example.com"' in body
    assert 'name="clan_name" value="Ногоон"' in body
    assert f'<option value="{lists["contact"].pk}" selected' in body
    assert 'name="contact-name" value="Ээж"' in body
    assert 'name="contact-value" value="99887766"' in body


def test_panel_lists_education_and_family_by_name_not_id(client: Client, hr: User, lists: dict[str, Any]) -> None:
    login_as(client, "HR", "hr_viewer")
    invitation = _rich(hr, lists)
    body = client.get(f"{NEW_URL}?submission={invitation.pk}").content.decode()

    assert PANEL_TITLE in body
    assert "Сүхбаатарын нэрэмжит сургууль" in body
    assert "Бакалавр" in body and "Нягтлан" in body
    # exact rendered rows: label, then the name (the family member's given name appears nowhere else on the page)
    assert "Хамаарал:</span> Хүү" in body
    assert "Нэр:</span> Нармандах" in body
    assert "Овог:</span> Дорж" in body
    assert f">{lists['edu_level'].pk}<" not in body


@pytest.mark.parametrize("stored", [999999, "abc"])
def test_panel_shows_unknown_code_as_question_mark(client: Client, hr: User, stored: Any) -> None:
    login_as(client, "HR", "hr_viewer")
    invitation = create_invitation(label="Сараа", branch=None, hours=None, by=hr)
    answers = _answers()
    answers["education"] = [{"org_name": "Сургууль", "edu_level": stored}]
    # written straight to the row: the real validation would refuse a code that is not in the list
    SelfFormInvitation.objects.filter(pk=invitation.pk).update(
        status=SelfFormStatus.SUBMITTED, answers=json.dumps(answers, ensure_ascii=False)
    )
    body = client.get(f"{NEW_URL}?submission={invitation.pk}").content.decode()
    assert PANEL_TITLE in body and "«?»" in body


@pytest.mark.parametrize("raw_register", ["", "abc!!"])
def test_blank_or_garbled_register_gives_no_warning_and_no_error(
    client: Client, hr: User, hired: Employee, raw_register: str
) -> None:
    login_as(client, "HR", "hr_viewer")
    invitation = create_invitation(label="Сараа", branch=None, hours=None, by=hr)
    answers = _answers(register_no=raw_register)
    SelfFormInvitation.objects.filter(pk=invitation.pk).update(
        status=SelfFormStatus.SUBMITTED, answers=json.dumps(answers, ensure_ascii=False)
    )
    stored = SelfFormInvitation.objects.get(pk=invitation.pk)
    assert review.duplicate_for(stored, hr) is None
    response = client.get(f"{NEW_URL}?submission={invitation.pk}")
    body = response.content.decode()
    assert response.status_code == 200 and PANEL_TITLE in body
    assert GENERIC_DUPLICATE not in body and "аль хэдийн харьяалагдсан" not in body
    assert 'name="register_no"' in body and 'name="register_no" value="УБ99112233"' not in body


def test_duplicate_register_blocks_the_hire_post(client: Client, hr: User, hired: Employee, job_values: Any) -> None:
    login_as(client, "HR", "hr_viewer")
    invitation = _submitted(hr, family_name="Доржийн")  # same register number as the hired employee
    before = Employee.objects.count()
    payload = add_payload(job_values, register_no="УБ99112233", submission=str(invitation.pk))
    response = client.post(NEW_URL, payload)

    body = response.content.decode()
    assert response.status_code == 200  # the usual re-render of a refused hire
    assert "аль хэдийн бүртгэлтэй" in body  # the existing validation of the hire form refuses the number
    assert Employee.objects.count() == before  # no second employee
    assert SelfFormInvitation.objects.get(pk=invitation.pk).status == SelfFormStatus.SUBMITTED


def test_open_submission_is_ignored_silently(client: Client, hr: User) -> None:
    login_as(client, "HR", "hr_viewer")
    invitation = create_invitation(label="Сараа", branch=None, hours=None, by=hr)  # still open
    body = client.get(f"{NEW_URL}?submission={invitation.pk}").content.decode()
    assert PANEL_TITLE not in body
    assert 'name="submission"' not in body
    assert 'name="family_name" value="Батын"' not in body


@pytest.mark.parametrize("raw", ["abc", "0", "-3", "1.5", "99999999"])
def test_garbled_submission_id_is_ignored_silently(client: Client, raw: str) -> None:
    login_as(client, "HR", "hr_viewer")
    response = client.get(f"{NEW_URL}?submission={raw}")
    body = response.content.decode()
    assert response.status_code == 200
    assert PANEL_TITLE not in body and 'name="submission"' not in body


def test_foreign_branch_submission_is_ignored_silently(client: Client, hr: User) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    invitation = _submitted(hr, branch=south)
    limited = _user_in("HR", "hr_north", limit=[north.pk])
    client.force_login(limited)

    body = client.get(f"{NEW_URL}?submission={invitation.pk}").content.decode()
    assert PANEL_TITLE not in body and 'name="submission"' not in body
    assert 'name="family_name" value="Батын"' not in body


def test_duplicate_register_names_the_visible_employee(client: Client, hr: User, hired: Employee) -> None:
    login_as(client, "HR", "hr_viewer")
    invitation = _submitted(hr, family_name="Доржийн")  # same register number as the hired employee
    body = client.get(f"{NEW_URL}?submission={invitation.pk}").content.decode()

    assert GENERIC_DUPLICATE not in body
    assert f'href="/employees/{hired.pk}/"' in body
    assert "Батын Сараа" in body


def test_duplicate_register_outside_scope_shows_generic_text_only(client: Client, hr: User, hired: Employee) -> None:
    north = Branch.objects.create(name="Хойд")
    invitation = _submitted(hr, branch=north, family_name="Доржийн")
    limited = _user_in("HR", "hr_north2", limit=[north.pk])
    client.force_login(limited)

    body = client.get(f"{NEW_URL}?submission={invitation.pk}").content.decode()
    assert GENERIC_DUPLICATE in body
    assert f'href="/employees/{hired.pk}/"' not in body
    assert "Батын Сараа" not in body


def test_invalid_post_keeps_hidden_submission_and_never_overrides_posted_values(
    client: Client, hr: User, job_values: dict[str, Any]
) -> None:
    login_as(client, "HR", "hr_viewer")
    invitation = _submitted(hr)
    payload = add_payload(job_values, family_name="", submission=str(invitation.pk))
    response = client.post(NEW_URL, payload)

    body = response.content.decode()
    assert response.status_code == 200
    assert f'name="submission" value="{invitation.pk}"' in body
    # the posted blank is rendered: Django writes no value attribute for an empty bound field (not the stored name)
    family_tag = re.search(r'<input[^>]*name="family_name"[^>]*>', body)
    assert family_tag is not None and "value=" not in family_tag.group(0)


def test_normal_get_has_no_review_panel(client: Client) -> None:
    login_as(client, "HR", "hr_viewer")
    body = client.get(NEW_URL).content.decode()
    assert PANEL_TITLE not in body
    assert 'name="submission"' not in body


def test_panel_notes_a_photo_sent_by_the_employee(client: Client, hr: User) -> None:
    login_as(client, "HR", "hr_viewer")
    invitation = _submitted(hr, photo_b64="aGVsbG8=")
    body = client.get(f"{NEW_URL}?submission={invitation.pk}").content.decode()
    assert "Ажилтан зураг илгээсэн: хадгалахад хавсарна" in body


def test_panel_escapes_employee_text(client: Client, hr: User) -> None:
    login_as(client, "HR", "hr_viewer")
    invitation = create_invitation(label="Сараа", branch=None, hours=None, by=hr)
    answers = _answers()
    answers["education"] = [{"org_name": "<script>alert(1)</script>", "start_year": 2000, "end_year": 2004}]
    submit(invitation, answers, photo_b64="", agreed_correct=True, consent=True)
    body = client.get(f"{NEW_URL}?submission={invitation.pk}").content.decode()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    stored = json.loads(SelfFormInvitation.objects.get(pk=invitation.pk).answers)
    assert stored["education"][0]["org_name"] == "<script>alert(1)</script>"
