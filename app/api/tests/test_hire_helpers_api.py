"""The hire page's helpers (GET /employees/check-register, /districts, /order-suggest) and HR's self-form decision
(POST /selfforms/{pk}/send-back and /reject). Every route needs the manage right; a self-form outside the user's scope
is 404."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.test import Client
from employees.models import SelfFormInvitation, SelfFormStatus
from employees.selfform.service import create_invitation
from employees.selfform.service import submit as submit_selfform
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values
from employees.views_selfform import _NOTE_NEEDED, _REASON_NEEDED
from macs.models import Branch, City, District

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
CHECK_URL = "/api/v1/employees/check-register"
DISTRICTS_URL = "/api/v1/employees/districts"
SUGGEST_URL = "/api/v1/employees/order-suggest"
SELFFORMS_URL = "/api/v1/selfforms"
SENT_BACK_FLASH = "Анкетыг ажилтанд буцаалаа. Ажилтан засаад дахин илгээнэ."
REJECTED_FLASH = "Анкетыг татгалзлаа. Ажилтан дахин бөглөх боломжгүй болсон."
NOT_FOUND = "Хуудас олдсонгүй"


def _user(name: str, group: str = roles.HR) -> User:
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return User.objects.get(pk=user.pk)  # fresh permission and scope cache


@pytest.fixture
def hr_user(db: None) -> User:
    return _user("helpers_hr")


@pytest.fixture
def accountant(db: None) -> User:
    return _user("helpers_accountant", roles.ACCOUNTANT)


@pytest.fixture
def hired(hr_user: User) -> Any:
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _submitted(by: User, branch: Branch | None = None) -> SelfFormInvitation:
    """A self-form the employee has sent in, waiting for HR (status submitted)."""
    invitation = create_invitation(label="Сараа", branch=branch, hours=None, by=by)
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
    invitation.refresh_from_db()
    return invitation


def _post_json(client: Client, url: str, body: dict[str, str]) -> Any:
    return client.post(url, data=json.dumps(body), content_type="application/json")


def _messages(response: Any) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


# --- live register check ---


def test_check_register_finds_normalised_match(hr_user: User, hired: Any) -> None:
    response = _client(hr_user).get(CHECK_URL, {"register_no": "уб 99112233"})

    assert response.status_code == 200, response.content
    match = response.json()["match"]
    assert match == {"pk": hired.pk, "code": hired.code or "", "full_name": hired.full_name}


def test_check_register_empty_gives_null(hr_user: User, hired: Any) -> None:
    client = _client(hr_user)

    assert client.get(CHECK_URL, {"register_no": ""}).json() == {"match": None}
    assert client.get(CHECK_URL, {"register_no": "   "}).json() == {"match": None}
    assert client.get(CHECK_URL).json() == {"match": None}


def test_check_register_hides_employee_outside_scope(hr_user: User, hired: Any) -> None:
    other = macs_writes.save_department("Бусад хэлтэс")
    AccessScope.objects.create(user=hr_user, limited=True, department_ids=[other.pk])
    limited = User.objects.get(pk=hr_user.pk)  # fresh scope

    response = _client(limited).get(CHECK_URL, {"register_no": "УБ99112233"})

    assert response.status_code == 200
    assert response.json() == {"match": None}


# --- districts ---


def test_districts_follow_the_city(hr_user: User) -> None:
    ulaanbaatar = City.objects.create(name="Улаанбаатар")
    District.objects.create(name="Баянгол", city=ulaanbaatar)
    darkhan = City.objects.create(name="Дархан")
    District.objects.create(name="Дархан-Уул", city=darkhan)

    response = _client(hr_user).get(DISTRICTS_URL, {"city": str(ulaanbaatar.pk)})

    assert response.status_code == 200, response.content
    labels = [choice["label"] for choice in response.json() if choice["value"]]
    assert labels == ["Баянгол"]


def test_unknown_city_gives_empty_list(hr_user: User) -> None:
    client = _client(hr_user)

    assert client.get(DISTRICTS_URL, {"city": "999999"}).json() == []
    assert client.get(DISTRICTS_URL, {"city": ""}).json() == []
    assert client.get(DISTRICTS_URL).json() == []


# --- order suggest ---


def test_order_suggest_uses_date_or_today(hr_user: User, hired: Any) -> None:
    client = _client(hr_user)

    in_2026 = client.get(SUGGEST_URL, {"date": "2026-03-01"}).json()
    in_2027 = client.get(SUGGEST_URL, {"date": "2027-03-01"}).json()
    no_date = client.get(SUGGEST_URL, {"date": "nope"}).json()

    assert in_2026 == {"number": "2", "date": "2026-03-01"}  # the hired fixture's order is "1"
    assert in_2027 == {"number": "1", "date": "2027-03-01"}  # numbers are counted per calendar year
    assert no_date["date"] == date.today().isoformat()


# --- self-form decision ---


def test_send_back_blank_note_refused(hr_user: User) -> None:
    invitation = _submitted(hr_user)

    response = _post_json(_client(hr_user), f"{SELFFORMS_URL}/{invitation.pk}/send-back", {"note": "   "})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": False, "form_errors": [_NOTE_NEEDED], "redirect": ""}
    invitation.refresh_from_db()
    assert invitation.status == SelfFormStatus.SUBMITTED


def test_send_back_success_sets_flash_and_redirect(hr_user: User) -> None:
    invitation = _submitted(hr_user)

    response = _post_json(
        _client(hr_user), f"{SELFFORMS_URL}/{invitation.pk}/send-back", {"note": "Регистрийн дугаараа засна уу"}
    )

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": True, "form_errors": [], "redirect": "/employees/self-forms/"}
    invitation.refresh_from_db()
    assert invitation.status == SelfFormStatus.OPEN
    assert SENT_BACK_FLASH in _messages(response)


def test_reject_success(hr_user: User) -> None:
    invitation = _submitted(hr_user)

    response = _post_json(_client(hr_user), f"{SELFFORMS_URL}/{invitation.pk}/reject", {"reason": "Хуурамч мэдээлэл"})

    assert response.status_code == 200, response.content
    assert response.json() == {"ok": True, "form_errors": [], "redirect": "/employees/self-forms/"}
    invitation.refresh_from_db()
    assert invitation.status == SelfFormStatus.REJECTED
    assert invitation.reject_reason == "Хуурамч мэдээлэл"
    assert REJECTED_FLASH in _messages(response)


def test_reject_blank_reason_refused(hr_user: User) -> None:
    invitation = _submitted(hr_user)

    response = _post_json(_client(hr_user), f"{SELFFORMS_URL}/{invitation.pk}/reject", {"reason": " "})

    assert response.json() == {"ok": False, "form_errors": [_REASON_NEEDED], "redirect": ""}
    invitation.refresh_from_db()
    assert invitation.status == SelfFormStatus.SUBMITTED


def test_reject_already_decided_is_refused(hr_user: User) -> None:
    invitation = _submitted(hr_user)
    client = _client(hr_user)
    first = _post_json(client, f"{SELFFORMS_URL}/{invitation.pk}/reject", {"reason": "Эхний шалтгаан"})
    assert first.json()["ok"] is True

    again = _post_json(client, f"{SELFFORMS_URL}/{invitation.pk}/reject", {"reason": "Дахин шалтгаан"})

    assert again.status_code == 200
    body = again.json()
    assert body["ok"] is False
    assert len(body["form_errors"]) == 1  # the service's «not submitted» refusal
    assert body["redirect"] == ""
    invitation.refresh_from_db()
    assert invitation.status == SelfFormStatus.REJECTED
    assert invitation.reject_reason == "Эхний шалтгаан"


def test_decision_outside_scope_is_404(hr_user: User) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнөд")
    invitation = _submitted(hr_user, branch=south)
    AccessScope.objects.create(user=hr_user, limited=True, branch_ids=[north.pk])
    limited = User.objects.get(pk=hr_user.pk)  # fresh scope
    client = _client(limited)

    sent_back = _post_json(client, f"{SELFFORMS_URL}/{invitation.pk}/send-back", {"note": "Засна уу"})
    rejected = _post_json(client, f"{SELFFORMS_URL}/{invitation.pk}/reject", {"reason": "Татгалзая"})

    for response in (sent_back, rejected):
        assert response.status_code == 404
        assert response.json()["form_errors"] == [NOT_FOUND]
    invitation.refresh_from_db()
    assert invitation.status == SelfFormStatus.SUBMITTED


def test_decision_needs_manage_right(hr_user: User, accountant: User) -> None:
    invitation = _submitted(hr_user)
    client = _client(accountant)

    sent_back = _post_json(client, f"{SELFFORMS_URL}/{invitation.pk}/send-back", {"note": "Засна уу"})
    rejected = _post_json(client, f"{SELFFORMS_URL}/{invitation.pk}/reject", {"reason": "Татгалзая"})

    for response in (sent_back, rejected):
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"
    invitation.refresh_from_db()
    assert invitation.status == SelfFormStatus.SUBMITTED


def test_only_the_documented_helpers_are_new() -> None:
    from api.main import api

    paths = api.get_openapi_schema()["paths"]
    selfform_ops = {
        (path, method) for path, item in paths.items() if path.startswith("/api/v1/selfforms") for method in item
    }
    assert selfform_ops == {
        ("/api/v1/selfforms/{pk}/send-back", "post"),
        ("/api/v1/selfforms/{pk}/reject", "post"),
        # step 3e: the self-form list screen (app/api/selfforms.py)
        ("/api/v1/selfforms", "get"),
        ("/api/v1/selfforms", "post"),
        ("/api/v1/selfforms/{pk}", "get"),
        ("/api/v1/selfforms/{pk}/extend", "post"),
        ("/api/v1/selfforms/{pk}/revoke", "post"),
    }
    assert {"get"} == set(paths["/api/v1/employees/check-register"])
    assert {"get"} == set(paths["/api/v1/employees/districts"])
    assert {"get"} == set(paths["/api/v1/employees/order-suggest"])


GET_HELPERS = [
    f"{CHECK_URL}?register_no=X",
    f"{DISTRICTS_URL}?city=1",
    f"{SUGGEST_URL}?date=2026-01-01",
]


@pytest.mark.parametrize("url", GET_HELPERS)
def test_helper_gets_need_the_manage_right(accountant: User, url: str) -> None:
    response = _client(accountant).get(url)

    assert response.status_code == 403, response.content
    assert response.json()["code"] == "forbidden"


@pytest.mark.parametrize("url", GET_HELPERS)
def test_helper_gets_need_a_login(url: str) -> None:
    response = Client().get(url)

    assert response.status_code == 401, response.content


@pytest.mark.parametrize("action", ["send-back", "reject"])
def test_selfform_decisions_need_a_login(hr_user: User, action: str) -> None:
    invitation = _submitted(hr_user)
    body = json.dumps({"note": "Засна уу", "reason": "Татгалзая"})

    response = Client().post(f"{SELFFORMS_URL}/{invitation.pk}/{action}", data=body, content_type="application/json")

    assert response.status_code == 401, response.content
    invitation.refresh_from_db()
    assert invitation.status == SelfFormStatus.SUBMITTED
