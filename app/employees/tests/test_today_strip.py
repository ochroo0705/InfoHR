# ruff: noqa: F811  (the reused fixtures are imported, then named as test arguments)
from dataclasses import replace
from datetime import date, timedelta

import pytest
from accounts import modules
from accounts.models import AccessScope, User
from checklists.models import Checklist, ChecklistKind, ChecklistState, ChecklistTask
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from macs.models import Branch, LeaveTypeRow, LegalHoliday
from recruitment.models import Vacancy, VacancyStatus

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


def test_new_hires_window(hired: Employee, actor: User, job_values: dict[str, object]) -> None:
    old = _second_employee(actor, job_values)
    Employee.objects.filter(pk=hired.pk).update(first_hire_date=TODAY - timedelta(days=10))
    Employee.objects.filter(pk=old.pk).update(first_hire_date=TODAY - timedelta(days=40))
    found = today.new_hires(_rows(), TODAY)
    assert [r.employee.pk for r in found] == [hired.pk]
    assert today.new_hires([replace(r, state="left") for r in _rows()], TODAY) == []


def test_hires_fragment_names_only_visible(
    client: Client,
    hired: Employee,
    actor: User,
    job_values: dict[str, object],
    frozen_today: date,
) -> None:
    second = _second_employee(actor, job_values)
    north, south = Branch.objects.create(name="Хойд"), Branch.objects.create(name="Өмнөд")
    Employee.objects.filter(pk=hired.pk).update(branch_id=north.pk, first_hire_date=date(2026, 10, 4))
    Employee.objects.filter(pk=second.pk).update(branch_id=south.pk, first_hire_date=date(2026, 10, 4))
    hr = login_as(client, "HR", "hr_hires")
    AccessScope.objects.update_or_create(user=hr, defaults={"limited": True, "branch_ids": [north.pk]})
    url = reverse("employees:today_hires")
    response = client.get(url)
    body = response.content.decode()
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert hired.full_name in body
    assert second.full_name not in body
    assert "Сүүлийн 30 хоногт шинээр орсон 1 " in client.get(reverse("employees:today")).content.decode()


def test_holidays_ahead_window(frozen_today: date) -> None:
    LegalHoliday.objects.create(
        name="Тестийн баяр", start_date=date(2026, 10, 20), end_date=date(2026, 10, 20), hdays=1
    )
    LegalHoliday.objects.create(
        name="Хоцрогдсон баяр", start_date=date(2026, 12, 25), end_date=date(2026, 12, 25), hdays=1
    )
    assert today.holidays_ahead(TODAY) == [(date(2026, 10, 20), "Тестийн баяр")]


def test_holidays_ahead_year_boundary(frozen_today: date) -> None:
    LegalHoliday.objects.create(name="Шинэ жил", start_date=date(2027, 1, 1), end_date=date(2027, 1, 1), hdays=1)
    assert today.holidays_ahead(date(2026, 12, 20)) == [(date(2027, 1, 1), "Шинэ жил")]


def test_holidays_none_configured(frozen_today: date) -> None:
    assert today.holidays_ahead(TODAY) == []


def test_holiday_line_shows_on_the_page(client: Client, hired: Employee, frozen_today: date) -> None:
    LegalHoliday.objects.create(
        name="Тестийн баяр", start_date=date(2026, 10, 20), end_date=date(2026, 10, 20), hdays=1
    )
    login_as(client, "HR")
    body = client.get(reverse("employees:today")).content.decode()
    assert "Баяр ёслол: 2026-10-20 Тестийн баяр" in body


def test_no_holiday_line_when_none_configured(client: Client, hired: Employee, frozen_today: date) -> None:
    login_as(client, "HR")
    assert "Баяр ёслол" not in client.get(reverse("employees:today")).content.decode()


def _vacancy(job_values: dict[str, object], status: str) -> None:
    Vacancy.objects.create(
        title="Нягтлан",
        position=job_values["position"],
        department=job_values["department"],
        headcount=1,
        status=status,
    )


def test_open_vacancies_none_without_right() -> None:
    assert today.open_vacancies(_user("Accountant", "vac_none")) is None


def test_open_vacancies_counts_open_only(job_values: dict[str, object]) -> None:
    _vacancy(job_values, VacancyStatus.OPEN)
    _vacancy(job_values, VacancyStatus.OPEN)
    _vacancy(job_values, VacancyStatus.CLOSED)
    assert today.open_vacancies(_user("HR", "vac1")) == 2


def test_open_vacancy_line_links_to_vacancies(
    client: Client, job_values: dict[str, object], frozen_today: date
) -> None:
    _vacancy(job_values, VacancyStatus.OPEN)
    login_as(client, "HR")
    body = client.get(reverse("employees:today")).content.decode()
    assert "Нээлттэй ажлын байр 1 →" in body
    assert f'href="{reverse("recruitment:vacancies")}"' in body


def test_checklist_summary_none_without_right() -> None:
    assert today.checklist_summary(_user("HR", "ck_none"), _rows(), TODAY) is None


def test_checklist_summary_counts_open_lists_and_overdue_tasks(
    hired: Employee, actor: User, job_values: dict[str, object]
) -> None:
    second = _second_employee(actor, job_values)
    open_one = Checklist.objects.create(
        employee=hired, kind=ChecklistKind.OFFBOARDING, template_name="Загвар", anchor_day=TODAY
    )
    Checklist.objects.create(employee=second, kind=ChecklistKind.OFFBOARDING, template_name="Загвар", anchor_day=TODAY)
    cancelled = Checklist.objects.create(
        employee=hired,
        kind=ChecklistKind.ONBOARDING,
        template_name="Загвар",
        anchor_day=TODAY,
        state=ChecklistState.CANCELLED,
    )
    ChecklistTask.objects.create(checklist=open_one, title="Хоцорсон", due_on=TODAY - timedelta(days=2))
    ChecklistTask.objects.create(checklist=open_one, title="Цаашдаа", due_on=TODAY + timedelta(days=2))
    ChecklistTask.objects.create(
        checklist=open_one, title="Хийгдсэн", due_on=TODAY - timedelta(days=3), done_at=timezone.now()
    )
    ChecklistTask.objects.create(checklist=cancelled, title="Цуцлагдсан", due_on=TODAY - timedelta(days=2))
    assert today.checklist_summary(_user("Admin", "ck1"), _rows(), TODAY) == (2, 1)


def test_checklist_summary_counts_only_people_the_viewer_sees(
    hired: Employee, actor: User, job_values: dict[str, object]
) -> None:
    second = _second_employee(actor, job_values)
    north, south = Branch.objects.create(name="Хойд"), Branch.objects.create(name="Өмнөд")
    Employee.objects.filter(pk=hired.pk).update(branch_id=north.pk)
    Employee.objects.filter(pk=second.pk).update(branch_id=south.pk)
    for person in (hired, second):
        checklist = Checklist.objects.create(
            employee=person, kind=ChecklistKind.OFFBOARDING, template_name="Загвар", anchor_day=TODAY
        )
        ChecklistTask.objects.create(checklist=checklist, title="Хоцорсон", due_on=TODAY - timedelta(days=1))
    scoped = _user("HR", "ck_scoped")  # the Admin group is never limited by scope, so use HR plus the right
    right = Permission.objects.get(content_type__app_label="checklists", codename="manage_checklists")
    scoped.user_permissions.add(right)
    AccessScope.objects.update_or_create(user=scoped, defaults={"limited": True, "branch_ids": [north.pk]})
    visible = employee_rows(access.visible_employees(scoped).filter(ext__isnull=False), TODAY)
    assert today.checklist_summary(scoped, visible, TODAY) == (1, 1)
    assert today.checklist_summary(_user("Admin", "ck_all"), _rows(), TODAY) == (2, 2)


def test_checklist_summary_none_when_the_module_is_off(
    monkeypatch: pytest.MonkeyPatch, hired: Employee, job_values: dict[str, object]
) -> None:
    Checklist.objects.create(employee=hired, kind=ChecklistKind.OFFBOARDING, template_name="Загвар", anchor_day=TODAY)
    monkeypatch.setattr(modules, "enabled", lambda key: key != "checklists")
    assert today.checklist_summary(_user("Admin", "ck_off"), _rows(), TODAY) is None


def test_checklist_line_shows_on_the_page(client: Client, hired: Employee, frozen_today: date) -> None:
    checklist = Checklist.objects.create(
        employee=hired, kind=ChecklistKind.OFFBOARDING, template_name="Загвар", anchor_day=TODAY
    )
    ChecklistTask.objects.create(checklist=checklist, title="Хоцорсон", due_on=TODAY - timedelta(days=1))
    login_as(client, "Admin")
    body = client.get(reverse("employees:today")).content.decode()
    assert "Бүрдүүлэлт: 1 нээлттэй · " in body
    assert '<span class="text-red-700">1 хоцорсон</span>' in body
    line = body.split("data-checklist-summary", 1)[1].split("</div>", 1)[
        0
    ]  # the line itself, not the page's other links
    assert "<a " not in line  # no overview page exists: plain text, no link


def test_hires_line_says_it_looks_back(client: Client, hired: Employee, frozen_today: date) -> None:
    Employee.objects.filter(pk=hired.pk).update(first_hire_date=date(2026, 10, 4))
    login_as(client, "HR", "hr_looks_back")
    body = client.get(reverse("employees:today")).content.decode()
    assert "Сүүлийн 30 хоногт шинээр орсон 1 " in body
    assert "Шинээр орсон" not in body
