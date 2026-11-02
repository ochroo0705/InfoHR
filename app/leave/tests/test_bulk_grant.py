from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from macs.models import LeaveTypeRow

from leave.models import GrantKind, LeaveGrantExt
from leave.tests.conftest import make_employee

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]

PERIOD = {"start": "2026-03-01", "end": "2027-02-28", "days": "2", "reason": "Нэмэлт амралт"}


def _manual(*people: Employee) -> int:
    """How many manual grants of the test period the given people hold (hires may carry an automatic grant too)."""
    return LeaveGrantExt.objects.filter(grant__employee__in=people, kind=GrantKind.MANUAL, grant__ent_days=2).count()


def _client(user: User) -> Client:
    c = Client()
    c.force_login(user)
    return c


def _second(actor: User) -> Employee:
    return make_employee(actor, hired=date(2023, 5, 1), register_no="УБ88112233")


def test_post_grants_every_chosen_person(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    other = _second(actor)
    body = {**PERIOD, "ids": [employee.pk, other.pk]}
    response = _client(actor).post(reverse("leave:grant_bulk"), body)
    assert response.status_code == 200 and "2</strong> хүнд нэмлээ" in response.content.decode()
    assert _manual(employee) == 1 and _manual(other) == 1


def test_only_chosen_people_get_days(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    other = _second(actor)
    _client(actor).post(reverse("leave:grant_bulk"), {**PERIOD, "ids": [employee.pk]})
    assert _manual(employee) == 1 and _manual(other) == 0


def test_everyone_grants_all_working_people(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    other = _second(actor)
    _client(actor).post(reverse("leave:grant_bulk"), {**PERIOD, "everyone": "1"})
    assert _manual(employee, other) == 2


def test_one_refusal_skips_that_person_only(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    other = _second(actor)
    body = {**PERIOD, "days": "0", "ids": [employee.pk, other.pk]}  # 0 days is refused for each person
    page = _client(actor).post(reverse("leave:grant_bulk"), body).content.decode()
    assert "0</strong> хүнд нэмлээ" in page and employee.full_name in page and "Хоног 0 байж болохгүй" in page


def test_invalid_form_grants_nothing_and_keeps_the_form(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    response = _client(actor).post(reverse("leave:grant_bulk"), {**PERIOD, "reason": "", "ids": [employee.pk]})
    assert "хүнд нэмэх" in response.content.decode() and _manual(employee) == 0


def test_get_shows_count_and_empty_selection_is_told(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    c = _client(actor)
    assert "<strong>1</strong>" in c.get(reverse("leave:grant_bulk"), {"ids": [employee.pk]}).content.decode()
    assert "Ажилтан сонгоогүй" in c.get(reverse("leave:grant_bulk")).content.decode()


def test_user_without_record_right_is_refused(employee: Employee, annual: LeaveTypeRow) -> None:
    viewer = User.objects.create_user("viewer_only", password="x-long-pass-123")  # noqa: S106
    viewer.groups.add(Group.objects.get(name="Accountant"))  # can read leave, cannot record it
    c = _client(viewer)
    assert c.get(reverse("leave:grant_bulk"), {"ids": [employee.pk]}).status_code == 403
    assert c.post(reverse("leave:grant_bulk"), {**PERIOD, "ids": [employee.pk]}).status_code == 403
    assert _manual(employee) == 0


def test_balances_page_has_pickers_for_a_recorder(employee: Employee, annual: LeaveTypeRow, actor: User) -> None:
    body = _client(actor).get(reverse("leave:balances")).content.decode()
    assert 'class="bulk-pick' in body and "Бүгдэд эрх нэмэх" in body
