import pytest
from accounts.models import User
from django.test import Client
from django.urls import reverse

from employees.models import ActivityEntry, Employee, EmployeeExt, SetupItem
from employees.services import setup
from employees.tests.test_views import login_as

from .conftest import set_account


def url(e: Employee, key: str) -> str:
    return reverse("employees:setup_toggle", args=[e.pk, key])


def test_hire_sets_setup_required(hired: Employee) -> None:
    assert hired.ext.setup_required is True


def test_toggle_creates_deletes_and_logs(hired: Employee, actor: User) -> None:
    setup.toggle(hired, "contract", actor)
    assert SetupItem.objects.filter(employee=hired, key="contract").exists()
    setup.toggle(hired, "contract", actor)
    assert not SetupItem.objects.filter(employee=hired).exists()
    messages = list(ActivityEntry.objects.filter(employee=hired).values_list("message", flat=True))
    assert "Бүрдүүлэлт: Гэрээ байгуулсан — хийсэн" in messages
    assert "Бүрдүүлэлт: Гэрээ байгуулсан — болиулсан" in messages


def test_auto_items_reflect_data_and_cannot_toggle(hired: Employee, actor: User) -> None:
    admin = User.objects.create_superuser("root", password="x-long-pass-123")  # noqa: S106
    done = {i.key: i.done for i in setup.status(hired, admin)}
    assert "login" not in done and not done["bank"]  # login is no longer a checklist item
    set_account(hired, "123")  # the account number alone ticks the bank item
    done = {i.key: i.done for i in setup.status(hired, admin)}
    assert done["bank"]
    for key in ("login", "bank", "nope"):
        with pytest.raises(ValueError):
            setup.toggle(hired, key, actor)


def test_view_rejects_auto_item(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    assert client.post(url(hired, "login")).status_code == 400


def test_bank_hidden_without_view_salary(hired: Employee) -> None:
    hr = User.objects.create_user("hr1", password="x-long-pass-123")  # noqa: S106
    from django.contrib.auth.models import Group

    hr.groups.add(Group.objects.get(name="HR"))
    assert "bank" not in [i.key for i in setup.status(hired, hr)]


def test_accountant_forbidden(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    assert client.post(url(hired, "contract")).status_code == 403
    assert "Бүрдүүлэлт" not in client.get(reverse("employees:detail", args=[hired.pk])).content.decode()


def test_hr_toggle_and_complete(client: Client, hired: Employee, actor: User) -> None:
    login_as(client, "HR")
    page = client.get(reverse("employees:detail", args=[hired.pk])).content.decode()
    assert "Бүрдүүлэлт" in page and "/3" in page
    response = client.post(url(hired, "contract"))
    assert response.status_code == 200 and "1/3" in response.content.decode()
    for key in ("id_copy", "equipment"):
        setup.toggle(hired, key, actor)
    assert setup.is_complete(hired) is False
    set_account(hired, "1")
    assert setup.is_complete(hired)
    assert "Бүрдүүлэлт дууссан" in client.get(reverse("employees:detail", args=[hired.pk])).content.decode()


def _done_except_bank(hired: Employee, actor: User) -> None:
    for key in ("contract", "id_copy", "equipment"):
        setup.toggle(hired, key, actor)


def test_complete_is_per_viewer(client: Client, hired: Employee, actor: User) -> None:
    _done_except_bank(hired, actor)
    page_url = reverse("employees:detail", args=[hired.pk])
    login_as(client, "HR")
    assert "Бүрдүүлэлт дууссан" in client.get(page_url).content.decode()
    admin = User.objects.create_superuser("root2", password="x-long-pass-123")  # noqa: S106
    client.force_login(admin)
    body = client.get(page_url).content.decode()
    assert "Бүрдүүлэлт дууссан" not in body and "Банкны мэдээлэл бүртгэсэн" in body


def test_toggle_on_non_required_employee_forbidden(client: Client, hired: Employee) -> None:
    EmployeeExt.objects.filter(employee=hired).update(setup_required=False)
    login_as(client, "HR")
    assert client.post(url(hired, "contract")).status_code == 403
