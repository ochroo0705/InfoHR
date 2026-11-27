"""GET /api/v1/employees/{pk}/reporting-line: the chain of managers above an employee, as the React page calls it."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from employees import access, history_range
from employees.models import Employee, JobRecord
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values, link_login
from employees.tests.helpers import next_order_number

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
PERSON_KEYS = {
    "pk",
    "full_name",
    "given_initial",
    "photo_url",
    "photo_srcset",
    "position",
    "department",
    "work_phone",
    "email",
    "until",
}


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("reporting_line_hr", password=PASSWORD)
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


def _client(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _person(
    actor: User, job_values: dict[str, Any], register_no: str, manager: Employee | None = None, **overrides: Any
) -> Employee:
    job = {**job_values, "manager": manager, **overrides}
    return history.hire(
        hire_values(register_no),
        {},
        start=date(2026, 1, 5),
        job=job,
        salary=Decimal("2500000"),
        by=actor,
        order_number=next_order_number(),
        order_date=date(2026, 1, 5),
    )


@pytest.fixture
def chain(hr_user: User, job_values: dict[str, Any]) -> tuple[Employee, Employee, Employee]:
    """a is the top manager, b reports to a, c reports to b. All hired on 2026-01-05."""
    a = _person(
        hr_user,
        job_values,
        "УБ00000001",
        position=macs_writes.save_position("Захирал"),
        department=macs_writes.save_department("Удирдлага"),
    )
    b = _person(
        hr_user,
        job_values,
        "УБ00000002",
        manager=a,
        position=macs_writes.save_position("Хэлтсийн дарга"),
        department=macs_writes.save_department("Бизнес"),
    )
    c = _person(hr_user, job_values, "УБ00000003", manager=b)
    return a, b, c


def test_hr_sees_the_chain_in_order(hr_user: User, chain: tuple[Employee, Employee, Employee]) -> None:
    a, b, c = chain
    response = _client(hr_user).get(f"/api/v1/employees/{c.pk}/reporting-line")
    assert response.status_code == 200
    body = response.json()
    assert [level["full_name"] for level in body["levels"]] == [b.full_name, a.full_name]
    assert body["employee"]["pk"] == c.pk
    assert body["day"] == timezone.localdate().isoformat()
    assert (body["levels"][0]["position"], body["levels"][0]["department"]) == ("Хэлтсийн дарга", "Бизнес")
    assert (body["levels"][1]["position"], body["levels"][1]["department"]) == ("Захирал", "Удирдлага")
    assert (body["employee"]["position"], body["employee"]["department"]) == ("Нягтлан", "Санхүү")


def test_employee_sees_own_chain_above_them(chain: tuple[Employee, Employee, Employee]) -> None:
    a, b, c = chain
    login = User.objects.create_user("reporting_line_self", password=PASSWORD)
    link_login(c, login)
    assert not access.visible_employees(login).filter(pk__in=[a.pk, b.pk]).exists()
    response = _client(login).get(f"/api/v1/employees/{c.pk}/reporting-line")
    assert response.status_code == 200
    assert [level["full_name"] for level in response.json()["levels"]] == [b.full_name, a.full_name]


def test_employee_is_refused_another_record(hr_user: User, chain: tuple[Employee, Employee, Employee]) -> None:
    a, _b, c = chain
    login = User.objects.create_user("reporting_line_other", password=PASSWORD)
    link_login(c, login)
    response = _client(login).get(f"/api/v1/employees/{a.pk}/reporting-line")
    assert response.status_code == 404


def test_person_has_exactly_the_whitelisted_fields(hr_user: User, chain: tuple[Employee, Employee, Employee]) -> None:
    _a, _b, c = chain
    body = _client(hr_user).get(f"/api/v1/employees/{c.pk}/reporting-line").json()
    assert set(body["levels"][0]) == PERSON_KEYS
    assert set(body["employee"]) == PERSON_KEYS


def test_subject_has_own_job_and_no_until(hr_user: User, chain: tuple[Employee, Employee, Employee]) -> None:
    _a, _b, c = chain
    body = _client(hr_user).get(f"/api/v1/employees/{c.pk}/reporting-line?day=2026-03-01").json()
    assert body["employee"]["position"] == "Нягтлан"
    assert body["employee"]["department"] == "Санхүү"
    assert body["employee"]["until"] == ""
    assert body["levels"][0]["until"] == ""  # open-ended record of c: no last day


def test_manager_until_is_last_day_of_the_lower_record(
    hr_user: User, chain: tuple[Employee, Employee, Employee]
) -> None:
    _a, _b, c = chain
    JobRecord.objects.filter(employee=c).update(**history_range.span_kwargs(date(2026, 1, 5), date(2026, 3, 1)))
    body = _client(hr_user).get(f"/api/v1/employees/{c.pk}/reporting-line?day=2026-02-01").json()
    assert body["levels"][0]["until"] == "2026-02-28"
    assert body["employee"]["until"] == ""


def test_day_before_hire_gives_no_levels(hr_user: User, chain: tuple[Employee, Employee, Employee]) -> None:
    _a, _b, c = chain
    response = _client(hr_user).get(f"/api/v1/employees/{c.pk}/reporting-line?day=2025-01-01")
    assert response.status_code == 200
    body = response.json()
    assert body["day"] == "2025-01-01"
    assert body["levels"] == []


def test_nonsense_day_is_a_bad_request(hr_user: User, chain: tuple[Employee, Employee, Employee]) -> None:
    _a, _b, c = chain
    response = _client(hr_user).get(f"/api/v1/employees/{c.pk}/reporting-line?day=nonsense")
    assert response.status_code == 400
    assert response.json()["form_errors"] == ["Буруу огноо"]


def test_anonymous_is_refused(chain: tuple[Employee, Employee, Employee]) -> None:
    _a, _b, c = chain
    response = Client().get(f"/api/v1/employees/{c.pk}/reporting-line")
    assert response.status_code == 401
