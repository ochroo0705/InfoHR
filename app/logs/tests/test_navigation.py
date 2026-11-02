"""Links into the log page: the top-bar «Бүртгэл» link and the drawer's «Бүрэн харах» link on an employee's page."""

import re
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse
from employees.models import Employee, ensure_ext
from employees.services import history, macs_writes

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
EMPLOYEE_LOG = "/logs/"
SYSTEM_LOG = "/logs/system/"
# The menu link's markup: the same classes as the other module links, so its text is the anchor.
MENU_TEXT = ">Бүртгэл</a>"
DRAWER_TEXT = ">Бүрэн харах</a>"


def _user(name: str, role: str | None, *, first: str = "", last: str = "") -> User:
    user = User.objects.create_user(name, password=PASSWORD, first_name=first, last_name=last)  # noqa: S106
    if role is not None:
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _hire(actor: User, family: str, given: str, register_no: str) -> Employee:
    job: dict[str, Any] = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {
        "family_name": family,
        "given_name": given,
        "register_no": register_no,
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
    }
    return history.hire(values, {}, start=date(2026, 1, 5), job=job, salary=Decimal("2500000"), by=actor)


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("log_nav_actor", password=PASSWORD)  # noqa: S106


@pytest.fixture
def own(actor: User) -> Employee:
    return _hire(actor, "Батын", "Сараа", "УБ99130001")


@pytest.fixture
def hr(own: Employee) -> User:
    return _user("log_nav_hr", "HR", first="Оюун", last="Хүний")


@pytest.fixture
def admin(own: Employee) -> User:
    return _user("log_nav_admin", "Admin")


@pytest.fixture
def staff(own: Employee) -> User:
    """An Employee-role login linked to its own record (EmployeeExt.user)."""
    user = _user("log_nav_staff", "Employee")
    ext = ensure_ext(own)
    ext.user = user
    ext.save(update_fields=["user"])
    return user


@pytest.fixture
def audit_only(db: None) -> User:
    """Holds accounts.view_audit and nothing else: no employee rights."""
    user = User.objects.create_user("log_nav_audit", password=PASSWORD)  # noqa: S106
    user.user_permissions.add(Permission.objects.get(codename="view_audit", content_type__app_label="accounts"))
    return User.objects.get(pk=user.pk)


def test_hr_employee_page_links_to_the_log_for_that_person(hr: User, own: Employee) -> None:
    body = _client(hr).get(reverse("employees:detail", args=[own.pk])).content.decode()
    assert f"/logs/?employee={own.pk}" in body
    assert DRAWER_TEXT in body


def test_employee_role_own_page_has_no_log_link(staff: User, own: Employee) -> None:
    response = _client(staff).get(reverse("employees:detail", args=[own.pk]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "/logs/?employee=" not in body
    assert DRAWER_TEXT not in body


@pytest.mark.parametrize("user_fixture", ["hr", "admin"])
def test_menu_link_goes_to_employee_log_for_hr_and_admin(
    request: pytest.FixtureRequest, user_fixture: str, own: Employee
) -> None:
    user = request.getfixturevalue(user_fixture)
    body = _client(user).get(reverse("employees:detail", args=[own.pk])).content.decode()
    # HR and Admin also see reports, so the log link sits in the «Тайлан» menu of the top bar
    assert re.search(rf'<a href="{EMPLOYEE_LOG}"[^>]*>(?:(?!</a>).)*>Бүртгэл<', body, re.S)


def test_menu_link_absent_for_employee_role(staff: User, own: Employee) -> None:
    body = _client(staff).get(reverse("employees:detail", args=[own.pk])).content.decode()
    assert MENU_TEXT not in body


def test_audit_only_user_gets_menu_link_to_system_log(audit_only: User) -> None:
    response = _client(audit_only).get(SYSTEM_LOG)
    assert response.status_code == 200
    body = response.content.decode()
    assert f'href="{SYSTEM_LOG}" class="flex shrink-0' in body
    assert MENU_TEXT in body


def test_following_the_drawer_link_as_hr_shows_the_chip(hr: User, own: Employee) -> None:
    response = _client(hr).get(f"/logs/?employee={own.pk}")
    assert response.status_code == 200
    assert "Ажилтан: Батын Сараа" in response.content.decode()


def test_drawer_link_is_still_on_the_page_after_a_note(hr: User, own: Employee) -> None:
    # The drawer header sits outside #activity, which htmx redraws; a note must leave the page's link in place.
    client = _client(hr)
    response = client.post(reverse("employees:note", args=[own.pk]), {"text": "Тэмдэглэл"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    body = client.get(reverse("employees:detail", args=[own.pk])).content.decode()
    assert f"/logs/?employee={own.pk}" in body


@pytest.fixture
def auditor(own: Employee) -> User:
    """The Auditor role: view_audit only, no employee rights."""
    return _user("log_nav_auditor", "Auditor")


def test_auditor_system_log_page_opens(auditor: User) -> None:
    assert _client(auditor).get(SYSTEM_LOG).status_code == 200


def test_auditor_today_page_shows_no_employee_names(auditor: User, own: Employee) -> None:
    # Existing behaviour: the home pages need only a login; the Auditor sees no employee rows.
    response = _client(auditor).get(reverse("employees:today"))
    assert response.status_code == 200
    assert "Батын" not in response.content.decode()


def test_auditor_cannot_open_employee_log(auditor: User) -> None:
    response = _client(auditor).get(EMPLOYEE_LOG)
    assert response.status_code == 403
    assert "Ажилтны бүртгэл" not in response.content.decode()


def test_auditor_cannot_export_the_system_log(auditor: User) -> None:
    assert _client(auditor).get(reverse("logs:system_xlsx")).status_code == 403


def test_auditor_system_page_has_no_employee_tab(auditor: User) -> None:
    body = _client(auditor).get(SYSTEM_LOG).content.decode()
    assert "Ажилтны бүртгэл" not in body
    assert f'href="{EMPLOYEE_LOG}"' not in body
    assert "Системийн бүртгэл" in body


def test_auditor_employee_list_shows_no_names(auditor: User, own: Employee) -> None:
    response = _client(auditor).get(reverse("employees:list"))
    assert response.status_code == 200  # existing behaviour: an empty list, not a 403
    body = response.content.decode()
    assert "Батын" not in body
    assert "Сараа" not in body
    assert f"/employees/{own.pk}/" not in body


def test_auditor_menu_links_to_system_log(auditor: User, own: Employee) -> None:
    body = _client(auditor).get(SYSTEM_LOG).content.decode()
    assert f'href="{SYSTEM_LOG}" class="flex shrink-0' in body
    assert MENU_TEXT in body
