"""The hire page's forms and gating (`hire_page.build`), without the HTTP part: the GET prefill, the candidate and
self-form refusals on POST, the review panel, the salary right and the manage right."""

from datetime import date
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.http import QueryDict
from recruitment.models import Candidate
from recruitment.services import pipeline
from recruitment.tests.conftest import make_vacancy

from employees.models import Employee, SelfFormInvitation, SelfFormStatus
from employees.selfform.service import create_invitation, submit
from employees.services.hire_page import (
    CANDIDATE_GONE,
    SUBMISSION_GONE,
    SUBMISSION_NOT_SENT,
    build,
)

from .test_views import add_payload

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
PERSON_ANSWERS = {
    "family_name": "Батын",
    "given_name": "Сараа",
    "register_no": "УБ99112233",
    "birth_date": "1999-11-22",
    "gender": "F",
    "work_phone": "99112233",
    "email": "saraa@example.com",
    "clan_name": "Ногоон",
}


@pytest.fixture
def hr(db: None) -> User:
    user = User.objects.create_user("hr_build", password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name="HR"))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _post(payload: dict[str, str]) -> QueryDict:
    return QueryDict(urlencode(payload))


def _candidate(hr: User) -> Candidate:
    return pipeline.add_candidate(make_vacancy(), by=hr, surname="Дорж", given_name="Бат")


def _submitted(hr: User) -> SelfFormInvitation:
    invitation = create_invitation(label="Сараа", branch=None, hours=None, by=hr)
    answers: dict[str, Any] = {"person": PERSON_ANSWERS, "education": [], "family": [], "contact": {}}
    submit(invitation, answers, photo_b64="", agreed_correct=True, consent=True)
    return invitation


def test_get_prefills_from_query(hr: User, job_values: dict[str, Any]) -> None:
    query = {
        "family_name": " Батын ",
        "position": str(job_values["position"].pk),
        "department": "abc",  # not a number: ignored
        "start": "2026-01-02",
    }
    page = build(hr, query, None, None)
    assert page.person.initial["family_name"] == "Батын"
    assert page.job.initial["position"] == job_values["position"].pk
    assert "department" not in page.job.initial
    assert page.job.initial["start"] == date(2026, 1, 2)
    assert page.refusal_status is None


def test_candidate_unknown_or_foreign_is_ignored(hr: User, job_values: dict[str, Any]) -> None:
    for raw in ("999999", "abc"):
        page = build(hr, {}, _post(add_payload(job_values, candidate=raw)), None)
        assert page.candidate_id is None
        assert page.refusal_status is None


def test_foreign_candidate_is_ignored_without_recruitment_right(hr: User, job_values: dict[str, Any]) -> None:
    # A hirer with the employee right but not the recruitment right: the candidate is not visible to them, so the
    # value is ignored silently (no refusal, no link), as in test_user_without_recruitment_right_cannot_link.
    candidate = _candidate(hr)
    hire_only = Group.objects.create(name="HireOnly_build")
    hire_only.permissions.set(Group.objects.get(name="HR").permissions.exclude(codename="manage_recruitment"))
    hr.groups.clear()
    hr.groups.add(hire_only)
    user = User.objects.get(pk=hr.pk)  # fresh permission cache
    page = build(user, {}, _post(add_payload(job_values, candidate=str(candidate.pk))), None)
    assert page.candidate_id is None
    assert page.refusal_status is None
    assert not page.person.non_field_errors()


def test_post_with_gone_candidate_refuses(hr: User, job_values: dict[str, Any]) -> None:
    candidate = _candidate(hr)
    pipeline.reject(candidate, by=hr, reason="Тохирохгүй")
    page = build(hr, {}, _post(add_payload(job_values, candidate=str(candidate.pk))), None)
    assert page.refusal_status == 400
    assert CANDIDATE_GONE in page.person.non_field_errors()
    assert page.candidate_id is None


def test_gone_candidate_with_reviewable_submission_keeps_review(hr: User, job_values: dict[str, Any]) -> None:
    # The original employee_add passed **review_ctx on the gone branch, so the review panel stays on the refused form.
    candidate = _candidate(hr)
    pipeline.reject(candidate, by=hr, reason="Тохирохгүй")
    invitation = _submitted(hr)
    payload = add_payload(job_values, candidate=str(candidate.pk), submission=str(invitation.pk))
    page = build(hr, {}, _post(payload), None)
    assert page.refusal_status == 400
    assert CANDIDATE_GONE in page.person.non_field_errors()
    assert page.candidate_id is None
    assert page.submission_id == invitation.pk
    assert page.review is not None
    assert page.duplicate is None


def test_post_with_unsent_submission_refuses(hr: User, job_values: dict[str, Any]) -> None:
    invitation = create_invitation(label="Сараа", branch=None, hours=None, by=hr)
    payload = add_payload(job_values, submission=str(invitation.pk))
    page = build(hr, {}, _post(payload), None)
    assert page.refusal_status == 400
    assert SUBMISSION_NOT_SENT in page.person.non_field_errors()
    assert page.submission is None
    assert page.submission_id == invitation.pk

    SelfFormInvitation.objects.filter(pk=invitation.pk).update(status=SelfFormStatus.CONFIRMED)
    page = build(hr, {}, _post(payload), None)
    assert page.refusal_status == 400
    assert SUBMISSION_GONE in page.person.non_field_errors()
    assert page.submission_id == invitation.pk


def test_reviewable_submission_fills_review_and_initial(hr: User) -> None:
    invitation = _submitted(hr)
    page = build(hr, {"submission": str(invitation.pk)}, None, None)
    assert page.submission is not None and page.submission.pk == invitation.pk
    assert page.submission_id == invitation.pk
    assert page.review is not None
    assert page.duplicate is None  # no employee has this register number yet
    assert page.refusal_status is None
    assert page.person.initial["family_name"] == "Батын"


def test_reviewable_submission_shows_duplicate_employee(hr: User, hired: Employee) -> None:
    # `hired` holds the register number UB99112233, the one the submitted form carries
    invitation = _submitted(hr)
    page = build(hr, {"submission": str(invitation.pk)}, None, None)
    assert page.duplicate is not None
    assert page.duplicate["visible"] is True
    assert page.duplicate["employee"].pk == hired.pk


def test_no_salary_right_has_no_si_form(hr: User) -> None:
    page = build(hr, {}, None, None)
    assert page.si is None
    assert page.allow_salary is False


def test_no_manage_right_raises(db: None) -> None:
    outsider = User.objects.create_user("nobody_build", password=PASSWORD)  # noqa: S106
    with pytest.raises(PermissionDenied):
        build(outsider, {}, None, None)
