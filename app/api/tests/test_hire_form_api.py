"""GET /api/v1/employees/new: the hire form's layout, fields, gating and self-form review."""

import re
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from employees.models import Employee
from employees.selfform.service import create_invitation, submit
from employees.services import history, macs_writes, orders
from employees.tests.conftest import hire_values
from macs.models import Branch
from recruitment.services import pipeline
from recruitment.tests.conftest import make_vacancy

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
NEW_URL = "/api/v1/employees/new"


def _hr(name: str, *, perms: tuple[str, ...] = (), group: str = roles.HR) -> User:
    """A user in a role group, with extra permissions granted directly (the perms are read fresh on each request)."""
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    for codename in perms:
        app_label, _, code = codename.partition(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=code))
    return User.objects.get(pk=user.pk)  # fresh permission cache


SALARY_PERMS = ("macs.manage_salary", "macs.view_salary")


@pytest.fixture
def hr_user(db: None) -> User:
    return _hr("hire_form_hr")


@pytest.fixture
def salary_hr(db: None) -> User:
    """An HR user who also holds the salary rights, so the salary tab and the si- fields exist."""
    return _hr("hire_form_salary_hr", perms=SALARY_PERMS)


@pytest.fixture
def hired(hr_user: User) -> Employee:
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


def _get(user: User | None, query: str = "") -> Any:
    client = Client()
    if user is not None:
        client.force_login(user)
    return client.get(f"{NEW_URL}{query}")


def _body(user: User | None, query: str = "") -> dict[str, Any]:
    response = _get(user, query)
    assert response.status_code == 200, response.content
    return response.json()


def _names(body: dict[str, Any]) -> list[str]:
    return [field["name"] for field in body["fields"]]


def test_hr_gets_four_tabs_in_django_order(salary_hr: User) -> None:
    body = _body(salary_hr)

    assert [tab["key"] for tab in body["tabs"]] == ["basic", "personal", "salary", "login"]
    assert [tab["label"] for tab in body["tabs"]] == ["Үндсэн", "Хувийн", "Цалин, даатгал", "Нэвтрэх эрх"]
    basic = body["tabs"][0]["sections"]
    assert basic[0]["heading"] == "Үндсэн мэдээлэл"
    assert basic[0]["names"][:5] == ["family_name", "given_name", "clan_name", "register_no", "birth_date"]
    assert [section["heading"] for section in basic][:2] == ["Үндсэн мэдээлэл", "Ажил, гэрээ"]
    assert body["title"] == "Ажилтан нэмэх"


def test_job_section_starts_with_start_then_first_hire_date(salary_hr: User) -> None:
    job = _body(salary_hr)["tabs"][0]["sections"][1]["names"]

    assert job[:2] == ["start", "first_hire_date"]
    assert job[-5:] == ["second_position", "office", "section", "job_type", "job_figure"]


def test_no_salary_right_has_no_salary_tab_and_no_si_fields(hr_user: User) -> None:
    body = _body(hr_user)

    assert [tab["key"] for tab in body["tabs"]] == ["basic", "personal", "login"]
    names = _names(body)
    assert not any(name.startswith("si-") for name in names)
    assert "base_salary" not in names


def test_order_section_present_only_when_hire_orders_required(monkeypatch: pytest.MonkeyPatch, salary_hr: User) -> None:
    monkeypatch.setattr(orders, "requires_order", lambda order_type: False)
    basic = _body(salary_hr)["tabs"][0]["sections"]
    assert all(section["kind"] != "order" for section in basic)
    assert not any(name.startswith("order-") for name in _names(_body(salary_hr)))

    monkeypatch.setattr(orders, "requires_order", lambda order_type: True)
    basic = _body(salary_hr)["tabs"][0]["sections"]
    order = basic[-1]
    assert order["kind"] == "order"
    assert order["heading"] == "Тушаал"
    assert order["names"] == ["order-number", "order-date", "order-summary", "order-issued_by"]
    assert order["note"] == "дугаар заавал, огноо хоосон бол өөрчлөлтийн огноо"
    assert not order["note"].startswith("Тушаал")


def test_slot_override_field_only_for_permission_holder(hr_user: User) -> None:
    assert "slot_override" not in _names(_body(hr_user))

    holder = _hr("hire_form_slot_holder", perms=("employees.override_position_slots",))
    assert "slot_override" in _names(_body(holder))


def test_photo_field_is_kind_file(salary_hr: User) -> None:
    by_name = {field["name"]: field for field in _body(salary_hr)["fields"]}

    assert by_name["photo"]["kind"] == "file"


def test_branch_field_required_for_limited_hirer(hr_user: User) -> None:
    branch = Branch.objects.create(name="Төв салбар")
    AccessScope.objects.create(user=hr_user, limited=True, branch_ids=[branch.pk])
    limited = User.objects.get(pk=hr_user.pk)  # fresh scope

    by_name = {field["name"]: field for field in _body(limited)["fields"]}

    assert by_name["branch"]["required"] is True


def test_fields_carry_hire_names(monkeypatch: pytest.MonkeyPatch, salary_hr: User) -> None:
    monkeypatch.setattr(orders, "requires_order", lambda order_type: True)
    names = _names(_body(salary_hr))

    for name in ("addr-city", "contact-name", "si-bank", "order-number", "username", "create_login"):
        assert name in names, name


def test_candidate_query_prefills_and_returns_id(hr_user: User) -> None:
    candidate = pipeline.add_candidate(make_vacancy(), by=hr_user, surname="Дорж", given_name="Бат")

    body = _body(hr_user, f"?candidate={candidate.pk}&family_name=Дорж")

    assert body["candidate"] == candidate.pk
    by_name = {field["name"]: field for field in body["fields"]}
    assert by_name["family_name"]["value"] == "Дорж"


def test_submission_query_returns_review_and_duplicate(hr_user: User, hired: Employee) -> None:
    invitation = create_invitation(label="Сараа", branch=None, hours=None, by=hr_user)
    answers = {
        "person": {
            "family_name": "Батын",
            "given_name": "Сараа",
            "register_no": "УБ99112233",
            "birth_date": "1999-11-22",
            "gender": "F",
            "work_phone": "99112233",
        },
        "education": [],
        "family": [],
        "contact": {},
    }
    submit(invitation, answers, photo_b64="", agreed_correct=True, consent=True)

    body = _body(hr_user, f"?submission={invitation.pk}")

    assert body["submission"] == invitation.pk
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["review"]["submitted_at"])
    assert body["review"]["has_photo"] is False
    assert body["review"]["education"] == []
    assert body["duplicate"] == {"visible": True, "employee_pk": hired.pk, "employee_name": "Батын Сараа"}


def test_no_manage_right_is_403(db: None) -> None:
    accountant = _hr("hire_form_accountant", group=roles.ACCOUNTANT)

    response = _get(accountant)

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_unauthenticated_is_401(db: None) -> None:
    assert _get(None).status_code == 401


def test_new_is_not_read_as_a_pk(hr_user: User) -> None:
    response = _get(hr_user)

    assert response.status_code == 200
    assert response.json()["title"] == "Ажилтан нэмэх"
