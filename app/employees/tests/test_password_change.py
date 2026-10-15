from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client

from employees.models import Employee
from employees.tests.test_views import add_payload

pytestmark = pytest.mark.django_db

OLD = "x-long-pass-123"  # noqa: S105


def staff(client: Client, role: str = "HR", must_change: bool = False) -> User:
    user = User.objects.create_user("staffer", password=OLD)
    user.groups.add(Group.objects.get(name=role))
    user.must_change_password = must_change
    user.save(update_fields=["must_change_password"])
    client.force_login(user)
    return user


def test_hire_shows_password_once_then_not_again(client: Client, job_values: dict[str, Any]) -> None:
    staff(client, "Admin")
    response = client.post(
        "/employees/new/", add_payload(job_values, base_salary="1800000", create_login="on", username="bold")
    )
    emp = Employee.objects.get(register_no="УК88010122")
    assert response.status_code == 302
    page = client.get(response.headers["Location"]).content.decode()
    assert 'id="one-time-login"' in page and "bold" in page
    password = page.split('rounded bg-white px-2 py-1 font-mono text-base tracking-wider select-all">')[1].split("<")[0]
    bold = User.objects.get(username="bold")
    assert bold.check_password(password)
    again = client.get(f"/employees/{emp.pk}/").content.decode()
    assert password not in again and 'id="one-time-login"' not in again


def test_middleware_redirects_flagged_user(client: Client) -> None:
    staff(client, "HR", must_change=True)
    response = client.get("/employees/")
    assert response.status_code == 302 and response.headers["Location"] == "/password/change/"


def test_middleware_htmx_gets_hx_redirect(client: Client) -> None:
    staff(client, "HR", must_change=True)
    response = client.get("/employees/", HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and response.headers["HX-Redirect"] == "/password/change/"


def test_middleware_allows_change_page_and_logout(client: Client) -> None:
    staff(client, "HR", must_change=True)
    assert client.get("/password/change/").status_code == 200
    assert client.get("/static/css/app.css").status_code != 302
    assert client.post("/logout/").status_code == 302
    assert client.post("/logout/").status_code == 302


def test_change_clears_flag_and_unlocks_pages(client: Client) -> None:
    user = staff(client, "HR", must_change=True)
    response = client.post(
        "/password/change/",
        {"old_password": OLD, "new_password1": "Sain-nuuc-123", "new_password2": "Sain-nuuc-123"},
    )
    assert response.status_code == 302 and response.headers["Location"] == "/"
    user.refresh_from_db()
    assert not user.must_change_password and user.check_password("Sain-nuuc-123")
    assert client.get("/employees/").status_code == 200


def test_change_applies_password_validators(client: Client) -> None:
    staff(client, "HR", must_change=True)
    response = client.post("/password/change/", {"old_password": OLD, "new_password1": "123", "new_password2": "123"})
    assert response.status_code == 200
    assert "text-red-600" in response.content.decode()
    assert User.objects.get(username="staffer").must_change_password


def test_forced_change_does_not_ask_old_password(client: Client) -> None:
    staff(client, "HR", must_change=True)
    page = client.get("/password/change/").content.decode()
    assert 'name="old_password"' not in page and "Хуучин нууц үг" not in page
    response = client.post("/password/change/", {"new_password1": "Sain-nuuc-123", "new_password2": "Sain-nuuc-123"})
    assert response.status_code == 302
    assert not User.objects.get(username="staffer").must_change_password


def test_normal_change_still_asks_old_password(client: Client) -> None:
    staff(client, "HR")
    assert 'name="old_password"' in client.get("/password/change/").content.decode()
    r = client.post(
        "/password/change/",
        {"old_password": "wrong", "new_password1": "Sain-nuuc-123", "new_password2": "Sain-nuuc-123"},
    )
    assert "Хуучин нууц үг буруу байна." in r.content.decode()


def test_errors_are_mongolian_and_shown_once(client: Client) -> None:
    staff(client, "HR", must_change=True)
    page = client.post("/password/change/", {"new_password1": "Sta1", "new_password2": "Sta1"}).content.decode()
    assert "Хамгийн багадаа 8 тэмдэгт байна." in page
    assert "Your password" not in page and "This password" not in page
    assert page.count("Дор хаяж 8 тэмдэгт") == 0  # the hint gives way to the errors
    mismatch = client.post("/password/change/", {"new_password1": "Sain-nuuc-123", "new_password2": "Sain-nuuc-999"})
    assert mismatch.content.decode().count("Хоёр нууц үг таарахгүй байна.") == 1


@pytest.mark.parametrize(
    ("password", "ok"),
    [("Abcdefg1", True), ("abcdefg1", False), ("ABCDEFG1", False), ("Abcdefgh", False), ("Abcde1", False)],
)
def test_password_rule(password: str, ok: bool) -> None:
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    try:
        validate_password(password)
    except ValidationError:
        assert not ok
    else:
        assert ok


def test_rule_error_is_mongolian(client: Client) -> None:
    staff(client, "HR", must_change=True)
    page = client.post("/password/change/", {"new_password1": "abcdefgh1", "new_password2": "abcdefgh1"})
    assert "Том, жижиг үсэг, тоо тус бүр нэгээс доошгүй байна." in page.content.decode()


def test_temp_password_meets_rule() -> None:
    from accounts.passwords import temp_password
    from django.contrib.auth.password_validation import validate_password

    for _ in range(50):
        validate_password(temp_password())
