"""Inline edit of one employee field from a report cell: the staff list flags and the cell_edit view (D-080)."""

import html
import re
from collections.abc import Callable
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from employees import stale
from employees.forms import EmployeeForm
from employees.models import ActivityEntry, Employee

from reports import cell_edit

pytestmark = pytest.mark.django_db


def _address(person: int, field: str) -> str:
    return "/reports/cell/?" + urlencode({"person": person, "field": field})


def _loaded(user: User, employee: Employee) -> str:
    """The `loaded` snapshot the editor posts: what the form showed as stored."""
    return stale.snapshot(EmployeeForm(employee=Employee.objects.get(pk=employee.pk), user=user))


def test_manager_staff_list_marks_register_no_cell(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    page = client.get("/reports/staff-list/?cols=name&cols=register_no").content.decode()
    assert f'data-edit="/reports/cell/?person={hired.pk}&amp;field=register_no"' in page


def test_viewer_without_manage_right_gets_no_edit_cells(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "Accountant")  # sees the staff list and work_phone, but may not manage employees
    page = client.get("/reports/staff-list/?cols=name&cols=work_phone").content.decode()
    assert "data-edit=" not in page


def test_manager_gets_the_editor_for_the_field(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    response = client.get(_address(hired.pk, "private_phone"))
    assert response.status_code == 200
    page = response.content.decode()
    assert "data-cell-form" in page
    assert 'name="private_phone"' in page
    assert 'name="loaded"' in page


def test_viewer_gets_403_for_the_editor(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "Accountant")
    assert client.get(_address(hired.pk, "work_phone")).status_code == 403


def test_field_outside_editable_is_404(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    assert client.get(_address(hired.pk, "salary")).status_code == 404


def test_unknown_employee_is_404(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    assert client.get(_address(999_999, "private_phone")).status_code == 404


def test_post_valid_returns_the_new_value(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    user = login_as(client, "HR")
    loaded = _loaded(user, hired)
    response = client.post(_address(hired.pk, "private_phone"), {"private_phone": "99887766", "loaded": loaded})
    assert response.status_code == 200
    assert "<span data-cell-value>99887766</span>" in response.content.decode()
    hired.refresh_from_db()
    assert hired.private_phone == "99887766"


def test_post_invalid_returns_the_editor_with_error(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    user = login_as(client, "HR")
    loaded = _loaded(user, hired)
    response = client.post(_address(hired.pk, "email"), {"email": "not-an-email", "loaded": loaded})
    assert response.status_code == 200
    page = response.content.decode()
    assert "data-cell-error" in page
    assert "not-an-email" in page  # the user's text stays in the editor
    hired.refresh_from_db()
    assert hired.email != "not-an-email"


def test_post_by_viewer_is_403(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "Accountant")
    response = client.post(_address(hired.pk, "work_phone"), {"work_phone": "11223344", "loaded": ""})
    assert response.status_code == 403
    hired.refresh_from_db()
    assert hired.work_phone != "11223344"


def test_manager_without_view_personal_gets_403_for_nationality(client: Client, hired: Employee) -> None:
    manager = User.objects.create_user("cell_view_manager", password="x-long-pass-123")  # noqa: S106
    for codename in ("manage_employees", "view_employees"):  # manage, but not view_personal
        manager.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="macs"))
    client.force_login(User.objects.get(pk=manager.pk))  # fresh permission cache
    assert client.get(_address(hired.pk, "nationality")).status_code == 403
    assert client.post(_address(hired.pk, "nationality"), {"nationality": "Mongol", "loaded": ""}).status_code == 403
    hired.refresh_from_db()
    assert hired.nationality != "Mongol"


def test_clash_returns_the_current_value_and_a_retry_succeeds(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    user = login_as(client, "HR")
    loaded = _loaded(user, hired)
    Employee.objects.filter(pk=hired.pk).update(private_phone="99001122")  # changed meanwhile by someone else
    response = client.post(_address(hired.pk, "private_phone"), {"private_phone": "99887766", "loaded": loaded})
    assert response.status_code == 200
    page = response.content.decode()
    assert cell_edit.CLASH in page
    assert 'value="99001122"' in page  # the editor shows the value stored now
    match = re.search(r'name="loaded" value="([^"]*)"', page)
    assert match is not None
    fresh_loaded = html.unescape(match.group(1))
    assert "99001122" in fresh_loaded  # the snapshot is the current stored value, not the old one
    retry = client.post(_address(hired.pk, "private_phone"), {"private_phone": "99887766", "loaded": fresh_loaded})
    assert "<span data-cell-value>99887766</span>" in retry.content.decode()
    hired.refresh_from_db()
    assert hired.private_phone == "99887766"


def _grant(client: Client, role: str, name: str, *codenames: str) -> User:
    """A new user in one role group with extra macs permissions, logged in with a fresh permission cache."""
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="macs"))
    client.force_login(User.objects.get(pk=user.pk))
    return user


def _salary_loaded(user: User, employee: Employee) -> str:
    """The `loaded` snapshot the salary editor posts: the salary and insurance form as stored."""
    return stale.snapshot(cell_edit.editor_form(user, Employee.objects.get(pk=employee.pk), "account_no"))


def test_admin_saves_account_no_from_the_cell_and_logs_a_sensitive_entry(client: Client, hired: Employee) -> None:
    user = _grant(client, "Admin", "cell_admin_salary")
    response = client.post(
        _address(hired.pk, "account_no"), {"account_no": "1234567890", "loaded": _salary_loaded(user, hired)}
    )
    assert response.status_code == 200
    assert "<span data-cell-value>1234567890</span>" in response.content.decode()
    hired.refresh_from_db()
    assert hired.account_no == "1234567890"
    entry = ActivityEntry.objects.filter(employee_id=hired.pk, sensitive=True).latest("id")
    assert entry.changes[0]["new"] == "1234567890"


def test_accountant_may_open_the_account_no_editor(client: Client, hired: Employee) -> None:
    _grant(client, "Accountant", "cell_acc_editor")  # manage_salary without manage_employees
    assert client.get(_address(hired.pk, "account_no")).status_code == 200
    assert client.get(_address(hired.pk, "work_phone")).status_code == 403


def test_hr_with_view_salary_but_not_manage_salary_gets_403_for_account_no(client: Client, hired: Employee) -> None:
    _grant(client, "HR", "cell_hr_no_salary", "view_salary")  # HR may manage employees, not the salary columns
    assert client.get(_address(hired.pk, "account_no")).status_code == 403
    assert client.post(_address(hired.pk, "account_no"), {"account_no": "999", "loaded": ""}).status_code == 403
    hired.refresh_from_db()
    assert hired.account_no != "999"


def test_staff_list_marks_account_no_for_the_salary_right_only(client: Client, hired: Employee) -> None:
    _grant(client, "HR", "cell_hr_list", "view_salary")  # the column shows, but HR has no salary right
    page = client.get("/reports/staff-list/?cols=name&cols=account_no").content.decode()
    assert "Дансны дугаар" in page
    assert "data-edit=" not in page


def test_accountant_gets_account_no_edit_cell_but_not_work_phone(client: Client, hired: Employee) -> None:
    _grant(client, "Accountant", "cell_acc_list")
    page = client.get("/reports/staff-list/?cols=name&cols=account_no&cols=work_phone").content.decode()
    assert f'data-edit="/reports/cell/?person={hired.pk}&amp;field=account_no"' in page
    assert "field=work_phone" not in page
