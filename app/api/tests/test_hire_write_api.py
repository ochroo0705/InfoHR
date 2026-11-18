"""POST /api/v1/employees: the hire from the add form, as the React page posts it (multipart: `values` JSON,
`candidate`, `submission`, `photo`). Business outcomes answer 200 with ok; the password is never in the response."""

import io
import json
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import Client
from employees.models import CompanySettings, Employee, SelfFormInvitation, SelfFormStatus
from employees.selfform.service import create_invitation
from employees.selfform.service import submit as submit_selfform
from employees.services import history, macs_writes
from employees.services.hire_page import CANDIDATE_GONE, SUBMISSION_GONE, SUBMISSION_NOT_SENT
from employees.services.orders import OrderError
from employees.services.page_writes import DB_REFUSED
from employees.tests.conftest import named
from employees.tests.helpers import next_order_number
from employees.views import ONE_TIME_LOGIN_KEY
from macs.models import Branch, Country, EmployeePhoto, NazgRow
from PIL import Image
from recruitment.models import Stage
from recruitment.services import convert, pipeline
from recruitment.tests.conftest import make_vacancy

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
URL = "/api/v1/employees"


def _user(name: str, group: str) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission and scope cache


@pytest.fixture
def hr_user(db: None) -> User:
    return _user("hire_write_hr", roles.HR)


@pytest.fixture
def admin_user(db: None) -> User:
    return _user("hire_write_admin", roles.ADMIN)


@pytest.fixture
def position_branch(db: None) -> Branch:
    return Branch.objects.create(name="Төв салбар")


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


def _client(user: User | None = None) -> Client:
    client = Client()
    if user is not None:
        client.force_login(user)
    return client


def _values(job_values: dict[str, Any], **extra: str) -> dict[str, str]:
    """The `values` the add form posts for a valid hire (every value a string, as a browser sends it)."""
    values = {
        "family_name": "Доржийн",
        "given_name": "Болд",
        "register_no": "УК88010122",
        "birth_date": "1988-01-01",
        "gender": "M",
        "work_phone": "99001122",
        "first_hire_date": "2026-02-01",
        "citizenship": str(named(Country, "Монгол").pk),
        "prior_service_years": "3",
        "prior_service_months": "0",
        "work_conditions": "1",
        "start": "2026-02-01",
        "position": str(job_values["position"].pk),
        "department": str(job_values["department"].pk),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
        "order-number": next_order_number(),
    }
    values.update(extra)
    return values


def _post(client: Client, values: dict[str, str], **extra: Any) -> Any:
    return client.post(URL, {"values": json.dumps(values), **extra})


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "blue").save(buffer, "PNG")
    return buffer.getvalue()


def test_valid_hire_returns_pk_and_redirect_to_detail(hr_user: User, job_values: dict[str, Any]) -> None:
    response = _post(_client(hr_user), _values(job_values))

    assert response.status_code == 200, response.content
    body = response.json()
    employee = Employee.objects.get(register_no="УК88010122")
    assert body["ok"] is True
    assert body["pk"] == employee.pk
    assert body["redirect"] == f"/employees/{employee.pk}/"
    assert body["field_errors"] == {} and body["form_errors"] == []


def test_hire_sets_one_time_login_in_session_when_requested(admin_user: User, job_values: dict[str, Any]) -> None:
    client = _client(admin_user)

    response = _post(client, _values(job_values, base_salary="1800000", create_login="on", username="bold"))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ok"] is True
    pending = client.session[ONE_TIME_LOGIN_KEY]
    assert pending["employee"] == body["pk"]
    assert pending["username"] == "bold"
    assert pending["password"]
    assert pending["password"] not in response.content.decode()  # shown once, never in the response
    assert "password" not in body


def test_blank_family_name_returns_field_error_by_html_name(hr_user: User, job_values: dict[str, Any]) -> None:
    before = Employee.objects.count()

    response = _post(_client(hr_user), _values(job_values, family_name=""))

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["pk"] is None and body["redirect"] == ""
    assert "family_name" in body["field_errors"]
    assert Employee.objects.count() == before


def test_prefixed_errors_use_prefixed_names(hr_user: User, job_values: dict[str, Any]) -> None:
    values = _values(job_values, **{"addr-city": "999999", "contact-name": "Ээж"})

    body = _post(_client(hr_user), values).json()

    assert body["ok"] is False
    assert "addr-city" in body["field_errors"]
    assert "contact-relative" in body["field_errors"]  # a filled contact name requires its relation
    assert "city" not in body["field_errors"] and "relative" not in body["field_errors"]


def test_photo_is_saved(hr_user: User, job_values: dict[str, Any]) -> None:
    picture = SimpleUploadedFile("face.png", _png(), content_type="image/png")

    body = _post(_client(hr_user), _values(job_values), photo=picture).json()

    assert body["ok"] is True
    assert EmployeePhoto.objects.filter(employee_id=body["pk"]).exists()


def test_bad_photo_is_a_form_error_not_a_500(hr_user: User, job_values: dict[str, Any]) -> None:
    not_image = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
    before = Employee.objects.count()

    response = _post(_client(hr_user), _values(job_values), photo=not_image)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "photo" in body["field_errors"]
    assert Employee.objects.count() == before


def test_no_salary_right_ignores_si_and_base_salary(hr_user: User, job_values: dict[str, Any]) -> None:
    values = _values(job_values, base_salary="9999999", **{"si-bank": "1"})

    body = _post(_client(hr_user), values).json()

    assert body["ok"] is True
    employee = Employee.objects.get(pk=body["pk"])
    assert not employee.salary_records.exists()
    assert employee.bank in ("", None) and employee.account_no in ("", None)  # the si fields were ignored too


def test_hire_outside_scope_redirects_to_list(hr_user: User, job_values: dict[str, Any]) -> None:
    other = macs_writes.save_department("Бусад хэлтэс")
    AccessScope.objects.create(user=hr_user, limited=True, department_ids=[other.pk])
    limited = User.objects.get(pk=hr_user.pk)  # fresh scope

    body = _post(_client(limited), _values(job_values)).json()

    assert body["ok"] is True
    assert body["redirect"] == "/employees/"


def test_malformed_values_is_400(hr_user: User) -> None:
    client = _client(hr_user)

    not_json = client.post(URL, {"values": "{not json"})
    not_object = client.post(URL, {"values": json.dumps(["family_name"])})
    not_string = client.post(URL, {"values": json.dumps({"family_name": 1})})

    assert not_json.status_code == 400
    assert not_object.status_code == 400
    assert not_string.status_code == 400


def test_deeply_nested_values_is_400(hr_user: User) -> None:
    response = _client(hr_user).post(URL, {"values": "[" * 5000 + "]" * 5000})

    assert response.status_code == 400
    assert response.json()["form_errors"]


def test_lone_surrogate_values_is_400(hr_user: User, job_values: dict[str, Any]) -> None:
    client = _client(hr_user)
    in_value = client.post(URL, {"values": json.dumps({"family_name": "\ud800"})})
    in_name = client.post(URL, {"values": json.dumps({"\ud800": "x"})})

    assert in_value.status_code == 400
    assert in_name.status_code == 400
    assert not Employee.objects.filter(register_no="УК88010122").exists()


def test_no_manage_right_is_403(db: None, job_values: dict[str, Any]) -> None:
    accountant = _user("hire_write_accountant", roles.ACCOUNTANT)

    response = _post(_client(accountant), _values(job_values))

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert not Employee.objects.filter(register_no="УК88010122").exists()


def _submitted(hr_user: User) -> SelfFormInvitation:
    invitation = create_invitation(label="Сараа", branch=None, hours=None, by=hr_user)
    answers: dict[str, Any] = {
        "person": {
            "family_name": "Батын",
            "given_name": "Сараа",
            "register_no": "УБ99112233",
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
    submit_selfform(invitation, answers, photo_b64="", agreed_correct=True, consent=True)
    return invitation


REGISTER_TAKEN = "Энэ регистрийн дугаартай ажилтан аль хэдийн бүртгэлтэй."
SLOT_FULL = "Орон тоо дүүрсэн байна"


def _assert_refused(client: Client, response: Any, before: int, username: str | None = None) -> dict[str, Any]:
    """The refusal every API refusal test checks: 200 with ok false, no employee, no one-time login in the session. With
    `username`, that login name must not have been created either (the posted create_login would have made it)."""
    assert response.status_code == 200, response.content
    body: dict[str, Any] = response.json()
    assert body["ok"] is False
    assert body["pk"] is None
    assert Employee.objects.count() == before
    assert ONE_TIME_LOGIN_KEY not in client.session
    if username is not None:
        assert not User.objects.filter(username=username).exists()
    return body


def test_candidate_gone_answers_message_and_keeps_no_candidate(admin_user: User, job_values: dict[str, Any]) -> None:
    candidate = pipeline.add_candidate(make_vacancy(), by=admin_user, surname="Дорж", given_name="Бат")
    pipeline.reject(candidate, by=admin_user, reason="Тохирохгүй")
    client = _client(admin_user)
    before = Employee.objects.count()

    response = _post(
        client,
        _values(job_values, create_login="on", username="bold"),
        candidate=str(candidate.pk),
    )

    body = _assert_refused(client, response, before, username="bold")
    assert CANDIDATE_GONE in body["form_errors"]
    assert body["candidate"] is None


def test_submission_not_sent_and_submission_gone_messages(admin_user: User, job_values: dict[str, Any]) -> None:
    client = _client(admin_user)
    not_sent = create_invitation(label="Сараа", branch=None, hours=None, by=admin_user)  # still OPEN
    gone = _submitted(admin_user)
    SelfFormInvitation.objects.filter(pk=gone.pk).update(status=SelfFormStatus.CONFIRMED)  # already decided
    cases = [(not_sent.pk, SUBMISSION_NOT_SENT), (gone.pk, SUBMISSION_GONE)]

    for pk, message in cases:
        before = Employee.objects.count()
        response = _post(
            client,
            _values(job_values, create_login="on", username="bold"),
            submission=str(pk),
        )

        body = _assert_refused(client, response, before, username="bold")
        assert message in body["form_errors"]
        assert body["submission"] == pk


def test_slot_full_refuses_with_slot_message(
    hr_user: User, job_values: dict[str, Any], position_branch: Branch
) -> None:
    """The real budget: one post, already filled by the first hire, so the second hire has no free slot. HR has no
    override right and posts no reason, so the refusal is the gate's own message."""
    CompanySettings.objects.update_or_create(defaults={"enforce_position_slots": True})
    NazgRow.objects.create(kind="Main", qty=1, year=2026, position=job_values["position"], branch=position_branch)
    client = _client(hr_user)
    assert _post(client, _values(job_values, branch=str(position_branch.pk))).json()["ok"] is True
    before = Employee.objects.count()

    response = _post(
        client,
        _values(
            job_values, branch=str(position_branch.pk), register_no="УК88010123", create_login="on", username="bold"
        ),
    )

    body = _assert_refused(client, response, before, username="bold")
    assert any(SLOT_FULL in message and "Орон тоо 1, ажиллаж буй 1." in message for message in body["form_errors"])


def test_duplicate_register_no_refused(admin_user: User, job_values: dict[str, Any]) -> None:
    client = _client(admin_user)
    assert _post(client, _values(job_values)).json()["ok"] is True
    before = Employee.objects.count()

    response = _post(client, _values(job_values, family_name="Другой", create_login="on", username="bold"))

    body = _assert_refused(client, response, before, username="bold")
    assert body["field_errors"]["register_no"] == [REGISTER_TAKEN]
    assert Employee.objects.filter(register_no="УК88010122").count() == 1


def test_second_post_of_the_same_register_no_makes_one_employee(admin_user: User, job_values: dict[str, Any]) -> None:
    client = _client(admin_user)
    assert _post(client, _values(job_values)).json()["ok"] is True
    before = Employee.objects.count()

    # a new order number, so the register number is the only thing that can refuse the second post
    response = _post(
        client,
        _values(job_values, create_login="on", username="bold", **{"order-number": next_order_number()}),
    )

    body = _assert_refused(client, response, before, username="bold")
    assert body["field_errors"]["register_no"] == [REGISTER_TAKEN]
    assert Employee.objects.filter(register_no="УК88010122").count() == 1


def test_login_username_taken_is_field_error_on_username(admin_user: User, job_values: dict[str, Any]) -> None:
    User.objects.create_user("bold", password=PASSWORD)  # the name is already in use
    client = _client(admin_user)
    before = Employee.objects.count()
    users_before = User.objects.count()

    response = _post(client, _values(job_values, create_login="on", username="bold"))

    body = _assert_refused(client, response, before)
    assert body["field_errors"]["username"] == ["Ийм нэвтрэх нэр аль хэдийн байна."]
    assert User.objects.count() == users_before  # no second user with that name


def test_db_refusal_answers_db_refused(
    admin_user: User, job_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*args: Any, **kwargs: Any) -> None:
        raise IntegrityError("refused")

    monkeypatch.setattr(history, "hire", refused)
    client = _client(admin_user)
    before = Employee.objects.count()

    response = _post(client, _values(job_values, create_login="on", username="bold"))

    body = _assert_refused(client, response, before, username="bold")
    assert DB_REFUSED in body["form_errors"]


def test_branch_limited_hirer_without_branch_is_refused(
    hr_user: User, job_values: dict[str, Any], position_branch: Branch
) -> None:
    AccessScope.objects.create(user=hr_user, limited=True, branch_ids=[position_branch.pk])
    limited = User.objects.get(pk=hr_user.pk)  # fresh scope
    client = _client(limited)
    before = Employee.objects.count()

    response = _post(client, _values(job_values, create_login="on", username="bold"))

    body = _assert_refused(client, response, before, username="bold")
    assert body["field_errors"].get("branch")

    # the same hirer with their branch hires
    hired = _post(client, _values(job_values, branch=str(position_branch.pk))).json()
    assert hired["ok"] is True
    assert Employee.objects.filter(pk=hired["pk"]).exists()


def test_refusal_leaves_a_valid_candidate_convertible(admin_user: User, job_values: dict[str, Any]) -> None:
    candidate = pipeline.add_candidate(make_vacancy(), by=admin_user, surname="Дорж", given_name="Бат")
    User.objects.create_user("bold", password=PASSWORD)  # the username is taken: the hire is refused
    client = _client(admin_user)
    before = Employee.objects.count()
    values = _values(job_values, create_login="on", username="bold")

    refused = _post(client, values, candidate=str(candidate.pk))

    body = _assert_refused(client, refused, before)
    assert body["candidate"] == candidate.pk
    assert convert.convertible(admin_user, str(candidate.pk)) is not None  # still open to conversion
    candidate.refresh_from_db()
    assert candidate.stage == Stage.NEW and candidate.employee_id is None

    # the cause is fixed (a new username); the same form hires and converts the candidate
    values["username"] = "bold2"
    hired = _post(client, values, candidate=str(candidate.pk)).json()

    assert hired["ok"] is True
    candidate.refresh_from_db()
    assert candidate.stage == Stage.HIRED and candidate.employee_id == hired["pk"]


def test_order_non_field_error_goes_to_order_errors_not_form_errors(
    hr_user: User, job_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*args: Any, **kwargs: Any) -> None:
        raise OrderError({"__all__": "Тушаалын дугаар давхардсан байна."})

    monkeypatch.setattr(history, "hire", refused)
    before = Employee.objects.count()

    body = _post(_client(hr_user), _values(job_values)).json()

    assert body["ok"] is False
    assert body["order_errors"] == ["Тушаалын дугаар давхардсан байна."]
    assert "Тушаалын дугаар давхардсан байна." not in body["form_errors"]
    assert Employee.objects.count() == before


def test_order_errors_empty_on_success(hr_user: User, job_values: dict[str, Any]) -> None:
    body = _post(_client(hr_user), _values(job_values)).json()

    assert body["ok"] is True
    assert body["order_errors"] == []
