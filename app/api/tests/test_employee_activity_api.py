"""GET /api/v1/employees/{pk}/activity: one 50-entry batch of the «Түүх» drawer, as activity_more renders it."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employees import access
from employees.models import ActivityEntry, ActivityKind, Employee
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values, link_login

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
BATCH = 50
ENTRIES = 60


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("employee_activity_hr", password=PASSWORD)
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


def _notes(employee: Employee, by: User, count: int) -> None:
    """`count` notes made now; message Тэмдэглэл-N, N counting up from the oldest."""
    for n in range(count):
        ActivityEntry.objects.create(employee=employee, by=by, kind=ActivityKind.NOTE, message=f"Тэмдэглэл-{n}")


def _backdate(entry: ActivityEntry, when: date) -> None:
    """ActivityEntry.at is set on create and the log is append-only, so the test writes the column directly."""
    stamp = timezone.make_aware(datetime.combine(when, datetime.min.time().replace(hour=12)))
    with connection.cursor() as cursor:
        cursor.execute("UPDATE employees_activityentry SET at_time = %s WHERE id = %s", [stamp, entry.pk])


def _newest_first(employee: Employee) -> list[ActivityEntry]:
    return list(ActivityEntry.objects.filter(employee=employee).order_by("-at", "-id"))


def _get(user: User, employee: Employee, offset: str | None = None) -> Any:
    url = f"/api/v1/employees/{employee.pk}/activity"
    if offset is not None:
        url += f"?offset={offset}"
    return _client(user).get(url)


def test_first_batch_has_fifty_entries_and_the_next_offset(hr_user: User, hired: Employee) -> None:
    _notes(hired, hr_user, ENTRIES)
    response = _get(hr_user, hired, "0")
    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == BATCH
    assert body["next_offset"] == BATCH
    assert body["prev_day"] == ""
    assert body["empty_label"] == ""
    assert response["Cache-Control"] == "no-store"
    assert body["entries"][0]["message"] == f"Тэмдэглэл-{ENTRIES - 1}"  # newest first


def test_second_batch_has_the_rest_and_no_next_offset(hr_user: User, hired: Employee) -> None:
    _notes(hired, hr_user, ENTRIES)  # the hire wrote its own log lines too; HR does not see the salary ones
    total = access.visible_activity(hr_user, hired).count()
    body = _get(hr_user, hired, str(BATCH)).json()
    assert len(body["entries"]) == total - BATCH
    assert body["next_offset"] is None
    assert body["entries"][-1]["message"] == access.visible_activity(hr_user, hired).last().message


def test_a_day_heading_is_not_repeated_across_the_batch_boundary(hr_user: User, hired: Employee) -> None:
    _notes(hired, hr_user, ENTRIES)  # all made today: the second batch continues today
    body = _get(hr_user, hired, str(BATCH)).json()
    assert body["prev_day"] == timezone.localdate().isoformat()
    first = body["entries"][0]
    assert first["starts_day"] is True  # a new group opens at the batch boundary, as the template does
    assert first["day_heading"] == ""  # the day already has its heading above
    assert all(e["day_heading"] == "" for e in body["entries"])


def test_an_older_day_at_the_batch_boundary_gets_its_heading(hr_user: User, hired: Employee) -> None:
    _notes(hired, hr_user, ENTRIES)
    yesterday = timezone.localdate() - timedelta(days=1)
    for entry in _newest_first(hired)[BATCH:]:  # the older half is yesterday's
        _backdate(entry, yesterday)
    body = _get(hr_user, hired, str(BATCH)).json()
    assert body["prev_day"] == timezone.localdate().isoformat()
    first = body["entries"][0]
    assert first["day"] == yesterday.isoformat()
    assert first["day_heading"] == "Өчигдөр"
    assert first["starts_day"] is True


def test_junk_offset_is_the_first_batch(hr_user: User, hired: Employee) -> None:
    _notes(hired, hr_user, ENTRIES)
    assert _get(hr_user, hired, "abc").json() == _get(hr_user, hired, "0").json()


def test_negative_offset_is_the_first_batch(hr_user: User, hired: Employee) -> None:
    _notes(hired, hr_user, ENTRIES)
    assert _get(hr_user, hired, "-5").json() == _get(hr_user, hired, "0").json()


def test_entry_fields_follow_the_template(hr_user: User, hired: Employee) -> None:
    ActivityEntry.objects.create(
        employee=hired,
        by=None,
        kind=ActivityKind.CORRECTION,
        message="Засвар",
        changes=[{"field": "Албан тушаал", "old": "", "new": "Нягтлан"}],
    )
    ActivityEntry.objects.create(employee=hired, by=hr_user, kind=ActivityKind.NOTE, message="Текст")
    entries = {e["message"]: e for e in _get(hr_user, hired).json()["entries"]}

    note = entries["Текст"]
    assert note["is_note"] is True
    assert note["kind_label"] == "Тэмдэглэл"
    assert note["by"] == (hr_user.get_full_name() or hr_user.username)
    assert note["message_class"] == "mt-1 rounded-lg bg-sky-50 px-3 py-2 whitespace-pre-line"
    assert note["dot_class"].endswith("bg-sky-500")
    assert note["badge_class"].endswith("bg-sky-50 text-sky-700")

    correction = entries["Засвар"]
    assert correction["by"] == "Систем"
    assert correction["is_note"] is False
    assert correction["message_class"] == "mt-0.5 text-amber-700"
    assert correction["dot_class"].endswith("bg-amber-500")
    assert correction["changes"] == [{"field": "Албан тушаал", "old": "", "new": "Нягтлан"}]
    assert correction["day_heading"] == ""  # the note above is today's: no second heading
    assert entries["Текст"]["day_heading"] == "Өнөөдөр"  # the drawer's first entry carries today's heading
    assert len(correction["time"]) == 5 and correction["time"][2] == ":"


def test_empty_drawer_shows_the_empty_label(hr_user: User) -> None:
    bare = Employee.objects.create(family_name="Хоосон", given_name="Бат", code="E9998")  # no log lines at all
    body = _get(hr_user, bare).json()
    assert body["entries"] == []
    assert body["empty_label"] == "Бүртгэл алга"
    assert body["next_offset"] is None


def test_employee_outside_the_scope_is_404(hired: Employee) -> None:
    stranger = User.objects.create_user("employee_activity_stranger", password=PASSWORD)  # no groups, no link
    assert _get(stranger, hired).status_code == 404


def test_unknown_pk_is_404(hr_user: User) -> None:
    assert _client(hr_user).get("/api/v1/employees/999999/activity").status_code == 404


def _plain_user(name: str) -> User:
    return User.objects.create_user(name, password=PASSWORD)  # no groups: no view rights, not linked to anyone


def test_sensitive_entries_are_hidden_without_the_salary_right(hired: Employee) -> None:
    ActivityEntry.objects.create(employee=hired, kind=ActivityKind.CHANGED, message="Цалин", sensitive=True)
    assert not access.visible_activity(_plain_user("activity_filter_plain"), hired).filter(message="Цалин").exists()
    admin = User.objects.create_user("activity_filter_admin", password=PASSWORD)
    admin.groups.add(Group.objects.get_or_create(name=roles.ADMIN)[0])  # the admin group holds the salary right
    assert access.visible_activity(admin, hired).filter(message="Цалин").exists()


def test_personal_entries_are_hidden_without_the_personal_right(hired: Employee, hr_user: User) -> None:
    ActivityEntry.objects.create(employee=hired, kind=ActivityKind.CHANGED, message="Хувь", personal=True)
    assert not access.visible_activity(_plain_user("activity_personal_plain"), hired).filter(message="Хувь").exists()
    assert access.visible_activity(hr_user, hired).filter(message="Хувь").exists()  # HR holds view_personal


def test_notes_are_hidden_without_the_employee_list_right(hired: Employee, hr_user: User) -> None:
    ActivityEntry.objects.create(employee=hired, by=hr_user, kind=ActivityKind.NOTE, message="Дотоод")
    assert not access.visible_activity(_plain_user("activity_note_plain"), hired).filter(message="Дотоод").exists()
    assert access.visible_activity(hr_user, hired).filter(message="Дотоод").exists()  # HR holds view_employees


def test_a_very_long_offset_is_the_first_batch_and_does_not_500(hr_user: User, hired: Employee) -> None:
    _notes(hired, hr_user, 3)
    response = _get(hr_user, hired, "9" * 30)
    assert response.status_code == 200
    assert response.json() == _get(hr_user, hired, "0").json()


def test_the_log_link_names_the_employee_log_with_this_person(hr_user: User, hired: Employee) -> None:
    body = _get(hr_user, hired).json()
    assert body["log_url"] == f"{reverse('logs:employee')}?employee={hired.pk}"


def test_the_log_link_is_empty_without_the_employee_list_right(hired: Employee) -> None:
    # A login linked to this employee sees their own record, but holds no employee-list right: no «Бүрэн харах».
    self_user = _plain_user("activity_log_self")
    link_login(hired, self_user)
    body = _get(self_user, hired).json()
    assert body["log_url"] == ""


def test_anonymous_is_401(hired: Employee) -> None:
    assert Client().get(f"/api/v1/employees/{hired.pk}/activity").status_code == 401
