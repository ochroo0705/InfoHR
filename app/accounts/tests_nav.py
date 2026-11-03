"""The top bar menu groups (accounts/nav.py): which links each role sees, and which one is marked as open."""

from datetime import date
from typing import Any

import pytest
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory
from django.urls import resolve, reverse

from accounts.models import User
from accounts.nav import NavGroup, top_nav

PASSWORD = "nav-test-pass"  # noqa: S105
NO_REQUESTS: dict[str, Any] = {"show": False, "count": 0}


def _user(name: str, *roles: str, is_staff: bool = False) -> User:
    user = User.objects.create_user(name, password=PASSWORD, is_staff=is_staff)  # noqa: S106
    user.groups.set([Group.objects.get(name=role) for role in roles])  # replaces the default Employee role
    return User.objects.get(pk=user.pk)  # fresh object: no cached permissions


def _nav(user: User, path: str = "/employees/", own_record: bool = False, requests: Any = None) -> list[NavGroup]:
    request = RequestFactory().get(path)
    request.user = user
    request.resolver_match = resolve(path)
    return top_nav(request, own_record, requests or NO_REQUESTS)


def _shape(groups: list[NavGroup]) -> dict[str, list[str]]:
    return {g.key: [item.label for item in g.items] for g in groups}


@pytest.mark.django_db
def test_hr_gets_six_groups_with_menus() -> None:
    assert _shape(_nav(_user("nav_hr", "HR"), own_record=True)) == {
        "today": ["Өнөөдөр"],
        "employees": ["Ажилтнууд", "Тушаалын бүртгэл"],
        "leave": ["Чөлөө, амралт"],
        "recruitment": ["Ажилд авах"],
        "reports": ["Тайлан", "Бүртгэл"],
        "settings": ["Жагсаалтууд", "Орон тооны төлөвлөгөө"],
    }


@pytest.mark.django_db
def test_staff_start_with_my_page_and_see_no_hr_screens() -> None:
    groups = _nav(_user("nav_staff", "Employee"), own_record=True)
    assert _shape(groups) == {"me": ["Миний хуудас"], "employees": ["Ажилтнууд"]}
    assert all(g.single for g in groups)  # one link each: plain links, no drop-down menus


@pytest.mark.django_db
def test_my_page_is_not_a_top_link_for_hr() -> None:
    assert "me" not in _shape(_nav(_user("nav_hr2", "HR"), own_record=True))


@pytest.mark.django_db
def test_auditor_sees_only_the_system_log_as_a_plain_link() -> None:
    reports = {g.key: g for g in _nav(_user("nav_audit", "Auditor"))}["reports"]
    assert reports.single is not None
    assert reports.single.label == "Бүртгэл"
    assert reports.single.url == reverse("logs:system")


@pytest.mark.django_db
def test_waiting_requests_count_shows_on_the_leave_group() -> None:
    leave = {g.key: g for g in _nav(_user("nav_hr3", "HR"), requests={"show": True, "count": 3})}["leave"]
    assert [item.label for item in leave.items] == ["Чөлөө, амралт", "Хүсэлт"]
    assert leave.badge == 3


@pytest.mark.django_db
def test_manager_without_leave_right_gets_requests_as_a_plain_link() -> None:
    leave = {g.key: g for g in _nav(_user("nav_boss", "Employee"), requests={"show": True, "count": 2})}["leave"]
    assert leave.single is not None
    assert leave.single.url == reverse("leave:requests")


@pytest.mark.django_db
def test_open_screen_marks_its_link_and_group() -> None:
    groups = {g.key: g for g in _nav(_user("nav_hr4", "HR"), path=reverse("employees:orders"))}
    assert groups["employees"].active
    assert [item.active for item in groups["employees"].items] == [False, True]
    assert not groups["today"].active


@pytest.mark.django_db
def test_requests_page_marks_only_the_requests_link() -> None:
    path = reverse("leave:requests")
    leave = {g.key: g for g in _nav(_user("nav_hr5", "HR"), path=path, requests={"show": True, "count": 0})}["leave"]
    assert [item.active for item in leave.items] == [False, True]


@pytest.mark.django_db
def test_admin_site_link_only_for_staff_accounts() -> None:
    assert "Админ хэсэг" in _shape(_nav(_user("nav_admin", "Admin", is_staff=True)))["settings"]
    assert "Админ хэсэг" not in _shape(_nav(_user("nav_admin2", "Admin")))["settings"]


@pytest.mark.django_db
def test_page_draws_menus_and_the_user_menu() -> None:
    user = _user("nav_hr6", "HR")
    client = Client()
    client.force_login(user)
    body = client.get(reverse("employees:today")).content.decode()
    assert body.count("data-nav-menu") == 5  # 3 menus + the theme menu + the user menu
    assert f'href="{reverse("password_change")}"' in body
    assert f'action="{reverse("logout")}"' in body


@pytest.mark.django_db
def test_recruitment_link_shows_for_hr_and_hiring_managers_only() -> None:
    from employees.tests.conftest import hire_values
    from recruitment.models import Vacancy

    hr = _user("nav_rec_hr", "HR")
    assert "recruitment" in _shape(_nav(hr))
    stranger = _user("nav_rec_stranger", "Employee")
    assert "recruitment" not in _shape(_nav(stranger, own_record=True))
    # A hiring manager (an employee linked to the login, named on a vacancy) gets the link; before that, none.
    from employees.services import history, macs_writes

    position, department = macs_writes.save_position("Нягтлан"), macs_writes.save_department("Санхүү")
    job = {
        "position": position,
        "department": department,
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    employee = history.hire(hire_values("УБ99887766"), {}, start=date(2026, 1, 5), job=job, salary=None, by=hr)
    employee.ext.user = stranger
    employee.ext.save()
    assert "recruitment" not in _shape(_nav(stranger, own_record=True))
    Vacancy.objects.create(
        title="V",
        position=position,
        department=department,
        hiring_manager=employee,
    )
    groups = {g.key: g for g in _nav(User.objects.get(pk=stranger.pk), own_record=True)}
    assert groups["recruitment"].single is not None
    assert groups["recruitment"].single.url == reverse("recruitment:vacancies")


@pytest.mark.django_db
def test_recruitment_check_runs_once_per_request(django_assert_num_queries: Any) -> None:
    stranger = _user("nav_rec_once", "Employee")
    request = RequestFactory().get("/employees/")
    request.user = stranger
    request.resolver_match = resolve("/employees/")
    top_nav(request, False, NO_REQUESTS)
    with django_assert_num_queries(0):
        top_nav(request, False, NO_REQUESTS)


@pytest.mark.django_db
def test_base_page_loads_modal_and_mongolian_validation_scripts() -> None:
    client = Client()
    client.force_login(_user("nav_scripts", "HR"))
    body = client.get(reverse("employees:today")).content.decode()
    assert 'src="/static/js/modal.js' in body  # pop-up closing and one-modal-per-trigger rule (UI_RULES §6)
    assert 'src="/static/js/validation_mn.js' in body  # Mongolian browser validation text (UI_RULES §2)
