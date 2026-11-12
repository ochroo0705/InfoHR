"""Facts card in the employee page rail (2026-11-09): #rail-who shows the name and the facts, and it is always
visible at lg and up (the header hides its own fact strip there)."""

from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone
from leave.models import LeaveSettings, LeaveTypeExt
from leave.services import ledger
from macs.models import LeaveTypeRow

from employees.models import Employee, ensure_ext
from employees.services import history, macs_writes

from .conftest import hire_values


def login_as(client: Client, role: str, name: str = "viewer") -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def _rail_who(body: str) -> str:
    """The #rail-who block: from its id to the end of the rail."""
    rail = body[body.index('id="emp-rail"') : body.index("</aside>", body.index('id="emp-rail"'))]
    return rail[rail.index('id="rail-who"') :]


@pytest.fixture
def no_job_employee(actor: User) -> Employee:
    """A MACS-only employee: production row and HR ext, no job record."""
    emp = macs_writes.create_employee(hire_values("УБ55443322"), {}, code=macs_writes.next_code(), by=actor)
    ensure_ext(emp)
    return Employee.objects.get(pk=emp.pk)


def test_rail_facts_list_the_six_facts(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    text = _rail_who(body)
    for label in ("Албан тушаал", "Хэлтэс", "Шууд удирдлага", "Ажилд орсон", "Утас"):
        assert label in text
    assert 'id="rail-facts"' in text
    assert "Нягтлан" in text  # position title from the fixture
    assert "Санхүү" in text  # department name from the fixture
    assert "2026-01-05" in text  # hire date, YYYY-MM-DD


def test_rail_card_is_always_visible_at_lg_and_up(client: Client, hired: Employee) -> None:
    """The card has no hidden class; the name comes before the first closing div (nested facts keep that)."""
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    who = _rail_who(body)
    tag = who[: who.index(">") + 1]
    assert "hidden" not in tag.split()
    first_div_end = who.index("</div>")
    assert hired.full_name in who[:first_div_end]


def test_rail_manager_shows_the_name_not_the_code(client: Client, actor: User, job_values: dict) -> None:
    """row.job.manager is an Employee: its str() is "<code> <name>", so the card prints its full_name (fix 6)."""
    boss = macs_writes.create_employee(
        {**hire_values("УБ11223344"), "given_name": "Дорж"}, {}, code=macs_writes.next_code(), by=actor
    )
    boss = Employee.objects.get(pk=boss.pk)
    history.hire(
        hire_values("УБ55667788"),
        {},
        start=date(2026, 1, 5),
        job={**job_values, "manager": boss},
        salary=Decimal("2500000"),
        by=actor,
    )
    emp = Employee.objects.get(register_no="УБ55667788")
    login_as(client, "HR")
    who = _rail_who(client.get(f"/employees/{emp.pk}/").content.decode())
    assert "Дорж" in who
    assert f"{boss.code} {boss.full_name}" not in who


@pytest.fixture
def current_leave(hired: Employee, db: None) -> None:
    """An annual leave type and this year's automatic grant, so the hired employee has a current leave period."""
    row = LeaveTypeRow.objects.create(name="Ээлжийн амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=True, is_paid=True)
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})
    ledger.ensure_grants(hired, timezone.localdate())


def test_rail_facts_leave_days_only_with_leave_rights(client: Client, hired: Employee, current_leave: None) -> None:
    login_as(client, "HR", name="with_leave")
    with_leave = _rail_who(client.get(f"/employees/{hired.pk}/").content.decode())
    assert "Үлдсэн амралт" in with_leave


def test_rail_facts_no_leave_row_without_leave_view(client: Client, hired: Employee, current_leave: None) -> None:
    """HR without the leave view permission (the Auditor role gets 404 on the page, so the permission is taken off HR
    for this test only; the database rolls it back) sees no leave row, although a period is current."""
    from django.contrib.auth.models import Permission

    group = Group.objects.get(name="HR")
    group.permissions.remove(Permission.objects.get(codename="view_leave", content_type__app_label="leave"))
    login_as(client, "HR", name="no_leave")
    response = client.get(f"/employees/{hired.pk}/")
    assert response.status_code == 200
    assert "Үлдсэн амралт" not in _rail_who(response.content.decode())


def test_rail_facts_survive_an_employee_without_a_job(client: Client, no_job_employee: Employee) -> None:
    login_as(client, "HR")
    response = client.get(f"/employees/{no_job_employee.pk}/")
    assert response.status_code == 200
    who = _rail_who(response.content.decode())
    assert "—" in who
    assert "Албан тушаал" in who
