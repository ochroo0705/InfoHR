"""GET /api/v1/employees/{pk}: the employee page's header, rail and rights, from employees.services.detail_page."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import AccessScope, User
from checklists.services import onboarding
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees.listing import row_for
from employees.models import Employee
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values, link_login
from employees.views import ONE_TIME_LOGIN_KEY

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("employee_api_hr", password=PASSWORD)
    user.groups.add(Group.objects.get_or_create(name=roles.HR)[0])
    return user


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


@pytest.fixture
def hired(hr_user: User, job_values: dict[str, Any]) -> Employee:
    """A working employee hired on 2026-01-05."""
    return history.hire(
        hire_values(),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number="1",
        order_date=date(2026, 1, 5),
    )


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def test_hr_gets_the_header_with_the_job_position(hr_user: User, hired: Employee) -> None:
    response = _client(hr_user).get(f"/api/v1/employees/{hired.pk}")
    assert response.status_code == 200
    body = response.json()
    row = row_for(hired, timezone.localdate())  # the row in force today, as the page reads it
    assert body["facts"]["position"] == str(row.job.position)
    assert body["facts"]["manager_label"] == ""
    assert body["family_name"] == hired.family_name
    assert body["given_name"] == hired.given_name
    assert body["full_name"] == hired.full_name
    assert body["state"]["key"] == "active"
    assert body["state"]["label"] == "Ажиллаж байгаа"
    assert body["can"]["manage"] is True


def test_setup_progress_text_is_done_over_total(hr_user: User, hired: Employee) -> None:
    onboarding.start_for_hire(hired, start_date=date(2026, 1, 5), employee_type="full_time", by=hr_user)
    body = _client(hr_user).get(f"/api/v1/employees/{hired.pk}").json()
    setup = body["setup"]
    assert setup is not None
    assert setup["progress_text"] == f"{setup['done']}/{setup['total']} хийгдсэн"


def test_unknown_pk_is_404(hr_user: User) -> None:
    assert _client(hr_user).get("/api/v1/employees/999999").status_code == 404


def test_create_login_flag_follows_the_login_link(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    assert client.get(f"/api/v1/employees/{hired.pk}").json()["can"]["create_login"] is True
    login = User.objects.create_user("employee_api_linked", password=PASSWORD)
    link_login(hired, login)
    assert client.get(f"/api/v1/employees/{hired.pk}").json()["can"]["create_login"] is False


def test_pending_login_of_another_employee_stays_in_the_session(
    hr_user: User, hired: Employee, job_values: dict[str, Any]
) -> None:
    other = history.hire(
        hire_values("УБ99112244") | {"given_name": "Бат"},
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("2500000"),
        by=hr_user,
        order_number="2",
        order_date=date(2026, 1, 5),
    )
    client = _client(hr_user)
    session = client.session
    session[ONE_TIME_LOGIN_KEY] = {"employee": other.pk, "username": "other.hire", "password": "tmp-pass-77"}
    session.save()
    body = client.get(f"/api/v1/employees/{hired.pk}").json()
    assert body["one_time_login"] is None
    assert client.session[ONE_TIME_LOGIN_KEY]["employee"] == other.pk


def test_employee_outside_the_scope_is_404(hr_user: User, hired: Employee) -> None:
    AccessScope.objects.create(user=hr_user, limited=True)  # a limited scope with no branch, department or team
    assert _client(hr_user).get(f"/api/v1/employees/{hired.pk}").status_code == 404


def test_user_without_the_salary_right_gets_no_salary_flag(hired: Employee) -> None:
    viewer = User.objects.create_user("employee_api_plain", password=PASSWORD)
    link_login(hired, viewer)  # the own record is always visible; the salary right is not held
    body = _client(viewer).get(f"/api/v1/employees/{hired.pk}").json()
    assert body["can"]["view_salary"] is False
    assert body["can"]["manage"] is False
    assert body["can"]["record_leave"] is False


def test_one_time_login_comes_once_and_is_not_cached(hr_user: User, hired: Employee) -> None:
    client = _client(hr_user)
    session = client.session
    session[ONE_TIME_LOGIN_KEY] = {"employee": hired.pk, "username": "gadur.hire", "password": "tmp-pass-42"}
    session.save()
    first = client.get(f"/api/v1/employees/{hired.pk}")
    assert first.json()["one_time_login"] == {"username": "gadur.hire", "password": "tmp-pass-42"}
    assert "no-store" in first["Cache-Control"]
    second = client.get(f"/api/v1/employees/{hired.pk}")
    assert second.json()["one_time_login"] is None
    assert ONE_TIME_LOGIN_KEY not in client.session


def test_anonymous_gets_401(hired: Employee) -> None:
    assert Client().get(f"/api/v1/employees/{hired.pk}").status_code == 401


def test_position_line_is_position_dot_department_with_a_job(hr_user: User, hired: Employee) -> None:
    row = row_for(hired, timezone.localdate())
    facts = _client(hr_user).get(f"/api/v1/employees/{hired.pk}").json()["facts"]
    assert facts["position_line"] == f"{row.job.position} · {row.job.department}"


def _stub_job(position: Any, department: Any) -> Any:
    """The fields _facts_out reads from a job record; a null foreign key is None, as on a record without one."""
    from types import SimpleNamespace

    return SimpleNamespace(
        position=position,
        department=department,
        manager=None,
        employee_type="",
        contract_type="fixed_term",
        contract_end=None,
        get_employee_type_display=lambda: "",
    )


def test_null_foreign_keys_send_no_none_text() -> None:
    from types import SimpleNamespace

    from api.employee import _facts_out

    employee = SimpleNamespace(first_hire_date=None, work_phone=None)
    facts = _facts_out(employee, _stub_job(position=None, department=None))
    assert facts["position"] == ""
    assert facts["department"] == ""
    assert facts["position_line"] == " · "


def test_no_job_gives_an_empty_position_line() -> None:
    from types import SimpleNamespace

    from api.employee import _facts_out

    employee = SimpleNamespace(first_hire_date=None, work_phone=None)
    facts = _facts_out(employee, None)
    assert facts["position"] == ""
    assert facts["position_line"] == ""
