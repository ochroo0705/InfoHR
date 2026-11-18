"""The hire itself (`hire_page.submit`), without the HTTP part: a valid hire, every refusal rolls back, and the login
comes back in the outcome instead of the session."""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import QueryDict
from django.utils import timezone
from macs.models import AddressRow, City, District
from recruitment.models import Candidate, Stage
from recruitment.services import convert, pipeline
from recruitment.tests.conftest import make_vacancy

from employees import history_range, named_lock
from employees.models import Employee, SelfFormInvitation, SelfFormStatus
from employees.selfform.service import create_invitation
from employees.selfform.service import submit as submit_selfform
from employees.services import personal_writes as pw
from employees.services import slots
from employees.services.hire_page import (
    CANDIDATE_GONE,
    SUBMISSION_GONE,
    HirePage,
    build,
    submit,
)
from employees.services.page_writes import DB_REFUSED

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
    user = User.objects.create_user("hr_submit", password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name="HR"))
    return User.objects.get(pk=user.pk)  # fresh permission cache


@pytest.fixture
def admin(db: None) -> User:
    user = User.objects.create_user("admin_submit", password=PASSWORD)  # noqa: S106
    user.groups.add(Group.objects.get(name="Admin"))
    return User.objects.get(pk=user.pk)  # fresh permission cache


@pytest.fixture
def place(db: None) -> dict[str, Any]:
    city = City.objects.create(name="Улаанбаатар")
    return {"city": city, "district": District.objects.create(name="Баянгол", city=city)}


def _page(user: User, payload: dict[str, str]) -> HirePage:
    return build(user, {}, QueryDict(urlencode(payload)), None)


def _address(place: dict[str, Any], **extra: str) -> dict[str, str]:
    return {"addr-city": str(place["city"].pk), "addr-district": str(place["district"].pk), **extra}


def _submitted(hr: User) -> SelfFormInvitation:
    invitation = create_invitation(label="Сараа", branch=None, hours=None, by=hr)
    answers: dict[str, Any] = {"person": PERSON_ANSWERS, "education": [], "family": [], "contact": {}}
    submit_selfform(invitation, answers, photo_b64="", agreed_correct=True, consent=True)
    return invitation


def _candidate(hr: User) -> Candidate:
    return pipeline.add_candidate(make_vacancy(), by=hr, surname="Дорж", given_name="Бат")


def test_valid_hire_creates_employee_with_job_and_salary(admin: User, job_values: dict[str, Any]) -> None:
    page = _page(admin, add_payload(job_values, base_salary="1800000"))
    outcome = submit(admin, page)
    assert outcome.status == 200 and outcome.login is None
    assert outcome.reason is None
    employee = Employee.objects.get(register_no="УК88010122")
    assert outcome.employee is not None and outcome.employee.pk == employee.pk
    assert employee.job_records.get().position == job_values["position"]
    assert employee.salary_records.get().base_salary == Decimal("1800000.00")


def test_invalid_form_returns_status_400_with_field_errors(hr: User, job_values: dict[str, Any]) -> None:
    before = Employee.objects.count()
    page = _page(hr, add_payload(job_values, family_name=""))  # required family name missing
    outcome = submit(hr, page)
    assert outcome.employee is None and outcome.login is None
    assert outcome.status == 400 and outcome.reason == "invalid"
    assert page.person.errors.get("family_name")
    assert Employee.objects.count() == before


def test_slot_blocked_adds_message_and_writes_nothing(
    hr: User, job_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    message = "Орон тооны төлөвлөгөөгүй байна"

    def blocked(**kwargs: Any) -> None:
        raise slots.SlotBlocked(message)

    monkeypatch.setattr(slots, "gate", blocked)
    before = Employee.objects.count()
    page = _page(hr, add_payload(job_values))
    outcome = submit(hr, page)
    assert outcome.status == 400 and outcome.employee is None and outcome.login is None
    assert outcome.reason == "refused"
    assert message in page.person.non_field_errors()
    assert Employee.objects.count() == before


def test_candidate_gone_inside_transaction_rolls_back(
    hr: User, job_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _candidate(hr)
    page = _page(hr, add_payload(job_values, candidate=str(candidate.pk)))
    assert page.candidate_id == candidate.pk  # convertible when the page was built
    monkeypatch.setattr(convert, "lock_convertible", lambda pk: None)  # gone once the transaction locks it
    before = Employee.objects.count()
    outcome = submit(hr, page)
    assert outcome.status == 400 and outcome.employee is None and outcome.login is None
    assert outcome.reason == "refused"
    assert CANDIDATE_GONE in page.person.non_field_errors()
    assert page.candidate_id is None
    assert Employee.objects.count() == before
    assert Candidate.objects.get(pk=candidate.pk).stage == Stage.NEW


def test_submission_changed_since_read_rolls_back(hr: User, job_values: dict[str, Any]) -> None:
    invitation = _submitted(hr)
    page = _page(hr, add_payload(job_values, submission=str(invitation.pk)))
    assert page.submission is not None
    # the employee sends the form again after the page was read
    SelfFormInvitation.objects.filter(pk=invitation.pk).update(submitted_at=timezone.now() + timedelta(minutes=5))
    before = Employee.objects.count()
    outcome = submit(hr, page)
    assert outcome.status == 400 and outcome.employee is None
    assert SUBMISSION_GONE in page.person.non_field_errors()
    assert page.review is None
    assert Employee.objects.count() == before
    invitation.refresh_from_db()
    assert invitation.status == SelfFormStatus.SUBMITTED and invitation.employee_id is None


@pytest.mark.parametrize("case", ["personal_conflict", "history_error", "db_refusal"])
def test_personal_conflict_history_error_and_db_refusal_roll_back(
    hr: User,
    job_values: dict[str, Any],
    place: dict[str, Any],
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if case == "personal_conflict":
        message = "Энэ хаяг аль хэдийн бүртгэгдсэн байна"

        def personal_refused(kind: str, *args: Any, **kwargs: Any) -> None:
            raise pw.PersonalConflict(message)

        monkeypatch.setattr(pw, "add", personal_refused)
    elif case == "history_error":
        message = history_range.LOCK_BUSY_MESSAGE

        def lock_busy(lock: named_lock.Lock) -> None:
            raise named_lock.LockBusy()

        monkeypatch.setattr(named_lock, "take", lock_busy)
    else:
        message = DB_REFUSED

        def db_refused(kind: str, *args: Any, **kwargs: Any) -> None:
            raise IntegrityError("refused")

        monkeypatch.setattr(pw, "add", db_refused)
    before = Employee.objects.count()
    page = _page(hr, add_payload(job_values, **_address(place, **{"addr-street": "Peace ave 1"})))
    outcome = submit(hr, page)
    assert outcome.status == 400 and outcome.employee is None and outcome.login is None
    assert message in page.person.non_field_errors()
    assert Employee.objects.count() == before
    assert not AddressRow.objects.exists()


def test_login_created_returns_password_once(admin: User, job_values: dict[str, Any]) -> None:
    page = _page(admin, add_payload(job_values, create_login="on", username="bold"))
    outcome = submit(admin, page)
    assert outcome.status == 200 and outcome.employee is not None
    assert outcome.login is not None
    assert outcome.login["employee"] == outcome.employee.pk
    assert outcome.login["username"] == "bold"
    assert isinstance(outcome.login["password"], str) and outcome.login["password"]
    assert User.objects.filter(username="bold").exists()


def test_duplicate_register_no_refused(hr: User, job_values: dict[str, Any]) -> None:
    assert submit(hr, _page(hr, add_payload(job_values))).status == 200
    page = _page(hr, add_payload(job_values, family_name="Другой"))  # the same register number as the first hire
    outcome = submit(hr, page)
    assert outcome.status == 400 and outcome.employee is None
    assert page.person.errors.get("register_no")
    assert Employee.objects.filter(register_no="УК88010122").count() == 1


def test_page_refused_by_build_returns_refused_reason(hr: User, job_values: dict[str, Any]) -> None:
    candidate = _candidate(hr)
    pipeline.reject(candidate, by=hr, reason="Тохирохгүй")
    page = _page(hr, add_payload(job_values, candidate=str(candidate.pk)))
    assert page.refusal_status == 400  # build refused the POST before any form was saved
    before = Employee.objects.count()
    outcome = submit(hr, page)
    assert outcome.status == 400 and outcome.reason == "refused" and outcome.employee is None
    assert Employee.objects.count() == before


def test_submit_without_manage_right_raises(hr: User, job_values: dict[str, Any]) -> None:
    page = _page(hr, add_payload(job_values))
    outsider = User.objects.create_user("nobody_submit", password=PASSWORD)  # noqa: S106
    before = Employee.objects.count()
    with pytest.raises(PermissionDenied):
        submit(outsider, page)
    assert Employee.objects.count() == before


def test_submit_on_unbound_page_raises(hr: User) -> None:
    page = build(hr, {}, None, None)  # a GET page is not bound
    with pytest.raises(ValueError, match="submit needs a bound page"):
        submit(hr, page)


def test_empty_post_is_a_bound_invalid_hire(hr: User) -> None:
    before = Employee.objects.count()
    page = build(hr, {}, QueryDict(), None)  # an empty POST is still a POST: the forms are bound
    assert page.person.is_bound
    outcome = submit(hr, page)
    assert outcome.status == 400 and outcome.reason == "invalid" and outcome.employee is None
    assert page.person.errors.get("family_name")
    assert Employee.objects.count() == before


def test_build_without_data_is_unbound(hr: User) -> None:
    page = build(hr, {}, None, None)  # a GET: the forms are unbound and prefilled only
    assert not page.person.is_bound
    assert not page.job.is_bound
