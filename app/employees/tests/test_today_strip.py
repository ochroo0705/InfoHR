# ruff: noqa: F811  (the reused fixtures are imported, then named as test arguments)
from datetime import date, timedelta

import pytest
from accounts.models import AccessScope, User
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from macs.models import Branch, LeaveTypeRow

from employees import access, today
from employees.listing import Row, employee_rows
from employees.models import Employee

from .test_today import (  # noqa: F401
    TODAY,
    _record,
    _second_employee,
    _user,
    annual,
    frozen_today,
    leave_actor,
)
from .test_views import login_as

pytestmark = pytest.mark.django_db


def _rows() -> list[Row]:
    return employee_rows(Employee.objects.all(), TODAY)


def _nobody() -> User:
    return User.objects.create_user("nobody", password="x-long-pass-123")  # noqa: S106


def test_away_strip_counts_distinct_people_per_working_day(
    hired: Employee, annual: LeaveTypeRow, leave_actor: User, actor: User, job_values: dict[str, object]
) -> None:
    second = _second_employee(actor, job_values)
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 16), leave_actor)
    _record(second, annual, date(2026, 10, 15), date(2026, 10, 15), leave_actor)
    user = _user("HR", "strip1")
    strip = today.away_strip(user, _rows(), TODAY)
    assert strip.counts[:4] == [1, 2, 1, None]
    assert len(strip.days) == today.WINDOW_DAYS
    assert strip.days[0].is_today
    assert strip.show_leave


def test_away_strip_without_the_leave_right_is_all_none_and_hidden(hired: Employee) -> None:
    strip = today.away_strip(_nobody(), _rows(), TODAY)
    assert strip.counts == [None] * today.WINDOW_DAYS
    assert strip.today_split == []
    assert not strip.show_leave


def test_today_split_groups_by_leave_type_name(
    hired: Employee,
    annual: LeaveTypeRow,
    leave_actor: User,
    actor: User,
    job_values: dict[str, object],
) -> None:
    second = _second_employee(actor, job_values)
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 16), leave_actor)
    _record(second, annual, date(2026, 10, 14), date(2026, 10, 14), leave_actor)
    strip = today.away_strip(_user("HR", "strip2"), _rows(), TODAY)
    assert strip.today_split == [(annual.name, 2)]


def test_away_on_day_returns_only_people_covered_that_day(
    hired: Employee, annual: LeaveTypeRow, leave_actor: User
) -> None:
    _record(hired, annual, date(2026, 10, 15), date(2026, 10, 16), leave_actor)
    user = _user("HR", "strip3")
    assert today.away_on_day(user, _rows(), TODAY) == []
    found = today.away_on_day(user, _rows(), date(2026, 10, 16))
    assert [(a.row.employee.pk, a.until) for a in found] == [(hired.pk, date(2026, 10, 16))]
    assert today.away_on_day(user, _rows(), date(2026, 10, 17)) == []


def test_upcoming_counts_has_both_keys_when_empty() -> None:
    assert today.upcoming_counts([]) == {"birthday": 0, "anniversary": 0}


def test_upcoming_counts_counts_each_kind(hired: Employee) -> None:
    hired.birth_date = date(1990, 10, 20)
    hired.first_hire_date = date(2023, 10, 31)
    hired.save()
    found = today.upcoming(_user("HR", "strip4"), _rows(), TODAY)
    assert today.upcoming_counts(found) == {"birthday": 1, "anniversary": 1}


def _away_url(day: date | str) -> str:
    return f"{reverse('employees:today_away')}?day={day}"


def test_today_away_fragment_lists_names_with_links(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, frozen_today: date
) -> None:
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 16), leave_actor)
    login_as(client, "HR")
    response = client.get(_away_url(TODAY))
    body = response.content.decode()
    assert response.status_code == 200
    assert reverse("employees:detail", args=[hired.pk]) in body
    assert hired.full_name in body
    assert annual.name in body
    assert "2026-10-16" in body


def test_today_away_fragment_bad_or_out_of_window_day_is_404(
    client: Client, hired: Employee, frozen_today: date
) -> None:
    login_as(client, "HR")
    assert client.get(_away_url("nonsense")).status_code == 404
    assert client.get(reverse("employees:today_away")).status_code == 404
    assert client.get(_away_url(TODAY - timedelta(days=1))).status_code == 404
    assert client.get(_away_url(TODAY + timedelta(days=today.WINDOW_DAYS))).status_code == 404
    assert client.get(_away_url(TODAY + timedelta(days=today.WINDOW_DAYS - 1))).status_code == 200


def _employee_viewer_without_leave_right() -> User:
    """Sees every employee (macs.view_employees) but has no leave.view_leave."""
    user = User.objects.create_user("no_leave", password="x-long-pass-123")  # noqa: S106
    user.user_permissions.add(Permission.objects.get(codename="view_employees"))
    return User.objects.get(pk=user.pk)


def test_today_away_fragment_is_empty_without_the_leave_right(
    client: Client, hired: Employee, annual: LeaveTypeRow, leave_actor: User, frozen_today: date
) -> None:
    _record(hired, annual, date(2026, 10, 14), date(2026, 10, 16), leave_actor)
    viewer = _employee_viewer_without_leave_right()
    assert hired.pk in set(access.visible_employees(viewer).values_list("pk", flat=True))
    client.force_login(viewer)
    response = client.get(_away_url(TODAY))
    assert response.status_code == 200
    assert hired.full_name not in response.content.decode()


def test_fragments_list_only_people_inside_the_users_scope(
    client: Client,
    hired: Employee,
    annual: LeaveTypeRow,
    leave_actor: User,
    actor: User,
    job_values: dict[str, object],
    frozen_today: date,
) -> None:
    second = _second_employee(actor, job_values)
    north, south = Branch.objects.create(name="Хойд"), Branch.objects.create(name="Өмнөд")
    Employee.objects.filter(pk=hired.pk).update(
        branch_id=north.pk, birth_date=date(1990, 10, 20), first_hire_date=date(2023, 10, 31)
    )
    Employee.objects.filter(pk=second.pk).update(
        branch_id=south.pk, birth_date=date(1991, 10, 21), first_hire_date=date(2022, 10, 30)
    )
    for person in (hired, second):
        _record(person, annual, date(2026, 10, 14), date(2026, 10, 16), leave_actor)
    hr = login_as(client, "HR", "hr_scoped")
    AccessScope.objects.update_or_create(user=hr, defaults={"limited": True, "branch_ids": [north.pk]})
    hired.refresh_from_db()
    second.refresh_from_db()
    pages = [
        client.get(_away_url(TODAY)),
        client.get(f"{reverse('employees:today_upcoming')}?kind=birthday"),
        client.get(f"{reverse('employees:today_upcoming')}?kind=anniversary"),
    ]
    for page in pages:
        body = page.content.decode()
        assert hired.full_name in body
        assert second.full_name not in body


def test_today_split_is_empty_when_today_is_an_off_day(
    hired: Employee, annual: LeaveTypeRow, leave_actor: User
) -> None:
    saturday = date(2026, 10, 17)
    _record(hired, annual, date(2026, 10, 16), date(2026, 10, 19), leave_actor)
    strip = today.away_strip(_user("HR", "strip_off"), employee_rows(Employee.objects.all(), saturday), saturday)
    assert strip.counts[0] is None
    assert strip.today_split == []


def test_today_upcoming_fragment_lists_birthdays_only_with_personal_right(
    client: Client, hired: Employee, frozen_today: date
) -> None:
    hired.birth_date = date(1990, 10, 20)
    hired.first_hire_date = date(2023, 10, 31)
    hired.save()
    url = reverse("employees:today_upcoming")
    login_as(client, "HR")
    body = client.get(f"{url}?kind=birthday").content.decode()
    assert hired.full_name in body
    assert "2026-10-20" in body
    anniversary = client.get(f"{url}?kind=anniversary").content.decode()
    assert hired.full_name in anniversary
    assert "3 жилийн ой" in anniversary
    client.logout()
    login_as(client, "Accountant", "acc_up")
    assert hired.full_name not in client.get(f"{url}?kind=birthday").content.decode()


def test_today_upcoming_fragment_unknown_kind_is_404(client: Client, hired: Employee, frozen_today: date) -> None:
    login_as(client, "HR")
    url = reverse("employees:today_upcoming")
    assert client.get(f"{url}?kind=other").status_code == 404
    assert client.get(url).status_code == 404


def test_fragments_are_not_cached(client: Client, hired: Employee, frozen_today: date) -> None:
    login_as(client, "HR")
    away = client.get(_away_url(TODAY))
    upcoming = client.get(f"{reverse('employees:today_upcoming')}?kind=birthday")
    assert away["Cache-Control"] == "no-store"
    assert upcoming["Cache-Control"] == "no-store"
