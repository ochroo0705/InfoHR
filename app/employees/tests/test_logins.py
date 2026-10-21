import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client

from employees.models import ActivityEntry, ActivityKind, Employee
from employees.services import logins

pytestmark = pytest.mark.django_db


def login_as(client: Client, role: str, name: str = "viewer") -> User:
    user = User.objects.create_user(name, password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def test_create_login_links_user_and_logs(hired: Employee, actor: User) -> None:
    login, password = logins.create_login(hired, "  saraa.b  ", by=actor)
    hired.refresh_from_db()
    assert hired.ext.user == login
    assert login.username == "saraa.b"
    assert login.check_password(password)
    assert login.must_change_password
    assert login.first_name == hired.given_name and login.last_name == hired.family_name
    entry = ActivityEntry.objects.get(employee=hired, kind=ActivityKind.CHANGED, message__startswith="Нэвтрэх эрх")
    assert entry.message == "Нэвтрэх эрх үүсгэсэн: saraa.b"
    assert entry.by == actor
    assert password not in entry.message and password not in str(entry.changes)


@pytest.mark.parametrize("username", ["", "   "])
def test_create_login_refuses_empty(hired: Employee, actor: User, username: str) -> None:
    with pytest.raises(ValueError, match="Нэвтрэх нэрийг бичнэ үү"):
        logins.create_login(hired, username, by=actor)
    hired.refresh_from_db()
    assert hired.ext.user is None


def test_create_login_refuses_taken_username(hired: Employee, actor: User) -> None:
    User.objects.create_user("taken", password="x-long-pass-123")  # noqa: S106
    with pytest.raises(ValueError, match="бүртгэлтэй байна"):
        logins.create_login(hired, "taken", by=actor)
    hired.refresh_from_db()
    assert hired.ext.user is None


def test_create_login_refuses_when_employee_has_login(hired: Employee, actor: User) -> None:
    logins.create_login(hired, "first", by=actor)
    with pytest.raises(ValueError, match="аль хэдийн байна"):
        logins.create_login(hired, "second", by=actor)
    assert not User.objects.filter(username="second").exists()
    assert ActivityEntry.objects.filter(employee=hired, message__startswith="Нэвтрэх эрх").count() == 1


def test_manager_creates_login_from_detail_page(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/login/", {"username": "newuser"})
    assert response.status_code == 200
    body = response.content.decode()
    hired.refresh_from_db()
    assert hired.ext.user is not None and hired.ext.user.username == "newuser"
    assert hired.ext.user.must_change_password
    assert "Түр нууц үг" in body and "newuser" in body
    password = body.split('select-all">')[1].split("<")[0]
    assert len(password) == 10 and hired.ext.user.check_password(password)
    assert response["Cache-Control"] == "no-store"


def test_login_form_shows_error_for_taken_name(client: Client, hired: Employee, actor: User) -> None:
    login_as(client, "HR")
    response = client.post(f"/employees/{hired.pk}/login/", {"username": actor.username})
    assert response.status_code == 200
    assert "бүртгэлтэй байна" in response.content.decode()
    hired.refresh_from_db()
    assert hired.ext.user is None


def test_login_modal_get_shows_form_and_hint(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/login/").content.decode()
    assert 'name="username"' in body and "автоматаар үүснэ" in body


def test_accountant_cannot_create_login(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    assert client.post(f"/employees/{hired.pk}/login/", {"username": "nope"}).status_code == 403
    assert not User.objects.filter(username="nope").exists()


def test_employee_role_cannot_see_other_employee_login_form(client: Client, hired: Employee) -> None:
    login_as(client, "Employee")
    assert client.post(f"/employees/{hired.pk}/login/", {"username": "nope"}).status_code == 404


def test_button_shown_only_to_manager_without_login(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    url = f"/employees/{hired.pk}/"
    assert "Нэвтрэх эрх үүсгэх" in client.get(url).content.decode()
    logins.create_login(hired, "has-login", by=User.objects.get(username="viewer"))
    assert "Нэвтрэх эрх үүсгэх" not in client.get(url).content.decode()


def test_button_hidden_from_accountant(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    assert "Нэвтрэх эрх үүсгэх" not in client.get(f"/employees/{hired.pk}/").content.decode()


def test_temp_password_format_and_uniqueness() -> None:
    from accounts import passwords

    generated = {passwords.temp_password() for _ in range(200)}
    assert len(generated) == 200
    for password in generated:
        assert len(password) == 10
        assert not set(password) & set("0O1lI")
        assert set(password) <= set(passwords.TEMP_ALPHABET)


def test_no_reset_on_employee_page(client: Client, hired: Employee, actor: User) -> None:
    login_as(client, "HR")
    logins.create_login(hired, "forgot", by=actor)
    assert "Нууц үг шинэчлэх" not in client.get(f"/employees/{hired.pk}/").content.decode()
    assert client.post(f"/employees/{hired.pk}/password-reset/").status_code == 404
