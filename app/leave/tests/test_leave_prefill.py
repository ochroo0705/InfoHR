from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from macs.models import LeaveAssign, LeaveTypeRow

from leave.models import LeaveTypeExt

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("leave.views.today", lambda: date(2026, 10, 14))
    monkeypatch.setattr("django.utils.timezone.localdate", lambda: date(2026, 10, 14))


def _client(user: User) -> Client:
    c = Client()
    c.force_login(user)
    return c


def _in_group(name: str) -> User:
    u = User.objects.create_user(f"u_{name}", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name=name))
    return u


def _leave_only_user() -> User:
    """May record leave but sees no employee (no employee view right, no own record): all are out of scope."""
    group = Group.objects.create(name="Чөлөө бүртгэгч тест")
    codenames = ("record_leave", "view_leave")
    group.permissions.set(Permission.objects.filter(content_type__app_label="leave", codename__in=codenames))
    u = User.objects.create_user("leave_only", password="x-long-pass-123")  # noqa: S106
    u.groups.add(group)
    return u


def _add_url(**params: str) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{reverse('leave:add')}?{query}" if query else reverse("leave:add")


def _post(employee: Employee, annual: LeaveTypeRow, **extra: str) -> dict[str, str]:
    data = {
        "employee": str(employee.pk),
        "leave_type": str(annual.pk),
        "start_date": "2026-11-02",
        "end_date": "2026-11-06",
        "note": "",
    }
    data.update(extra)
    return data


def test_address_fills_the_form(employee: Employee, annual: LeaveTypeRow) -> None:
    params = {"employee": str(employee.pk), "type": str(annual.pk), "start": "2026-11-02", "end": "2026-11-06"}
    url = _add_url(**params, **{"from": "assistant"})
    r = _client(_in_group("HR")).get(url)
    assert r.status_code == 200
    initial = r.context["form"].initial
    assert initial["employee"] == employee.pk
    assert initial["leave_type"] == annual.pk
    assert initial["start_date"] == date(2026, 11, 2)
    assert initial["end_date"] == date(2026, 11, 6)


def test_bad_or_missing_parts_stay_empty(employee: Employee, annual: LeaveTypeRow) -> None:
    url = _add_url(employee=str(employee.pk), start="2026-13-45", **{"from": "assistant"})
    initial = _client(_in_group("HR")).get(url).context["form"].initial
    assert initial["start_date"] is None
    assert initial["end_date"] is None
    assert "leave_type" not in initial


def test_far_year_and_end_before_start_are_left_out(employee: Employee, annual: LeaveTypeRow) -> None:
    hr = _client(_in_group("HR"))
    far = _add_url(start="2046-01-01", end="2046-01-03")
    assert hr.get(far).context["form"].initial["start_date"] is None
    backwards = _add_url(start="2026-11-06", end="2026-11-02")
    initial = hr.get(backwards).context["form"].initial
    assert initial["start_date"] == date(2026, 11, 6)
    assert initial["end_date"] is None


def test_employee_outside_scope_is_not_prefilled(employee: Employee, annual: LeaveTypeRow) -> None:
    user = _leave_only_user()
    r = _client(user).get(_add_url(employee=str(employee.pk), type=str(annual.pk), **{"from": "assistant"}))
    assert r.status_code == 200
    assert "employee" not in r.context["form"].initial
    assert r.context["form"].initial["leave_type"] == annual.pk
    assert f'value="{employee.pk}"' not in r.content.decode()


def test_inactive_type_is_not_prefilled(employee: Employee) -> None:
    old = LeaveTypeRow.objects.create(name="Хуучин төрөл")
    LeaveTypeExt.objects.create(leave_type=old, uses_annual_balance=False, is_paid=True, is_active=False)
    r = _client(_in_group("HR")).get(_add_url(type=str(old.pk), **{"from": "assistant"}))
    assert "leave_type" not in r.context["form"].initial


def test_assisted_page_shows_the_line_and_the_person(employee: Employee, annual: LeaveTypeRow) -> None:
    url = _add_url(employee=str(employee.pk), type=str(annual.pk), start="2026-11-02", **{"from": "assistant"})
    html = _client(_in_group("HR")).get(url).content.decode()
    assert "Асуултаас бөглөсөн" in html
    assert f"{employee.full_name} · Нягтлан · Санхүү" in html


def test_plain_page_has_no_assist_line(employee: Employee, annual: LeaveTypeRow) -> None:
    url = _add_url(employee=str(employee.pk), type=str(annual.pk), start="2026-11-02")
    r = _client(_in_group("HR")).get(url)
    html = r.content.decode()
    assert "Асуултаас бөглөсөн" not in html
    assert f"{employee.full_name} · Нягтлан · Санхүү" not in html
    assert r.context["form"].initial["leave_type"] == annual.pk


def test_invalid_post_keeps_the_assist_line_and_person(employee: Employee, annual: LeaveTypeRow) -> None:
    params = {"employee": str(employee.pk), "type": str(annual.pk), "start": "2026-11-02"}
    url = _add_url(**params, **{"from": "assistant"})
    r = _client(_in_group("HR")).post(url, _post(employee, annual, leave_type=""))
    html = r.content.decode()
    assert r.status_code == 200
    assert "text-red-600" in html
    assert f"{employee.full_name} · Нягтлан · Санхүү" in html
    assert "Асуултаас бөглөсөн: Ажилтан, Төрөл, Эхлэх" in html
    assert "from=assistant" in html  # the form posts back to the address it was opened with
    assert not LeaveAssign.objects.exists()


def test_post_with_assist_flag_validates_as_before(employee: Employee, annual: LeaveTypeRow) -> None:
    url = _add_url(**{"from": "assistant"})
    hr = _client(_in_group("HR"))
    invalid = hr.post(url, _post(employee, annual, leave_type=""))
    assert invalid.status_code == 200
    assert "text-red-600" in invalid.content.decode()
    assert not LeaveAssign.objects.exists()
    valid = hr.post(url, _post(employee, annual))
    assert valid.status_code == 204
    assert LeaveAssign.objects.count() == 1
