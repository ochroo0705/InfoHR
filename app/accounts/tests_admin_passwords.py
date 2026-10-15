"""Admin never types passwords: new users and resets get a temporary one, shown once (D-014)."""

import pytest
from django.contrib.messages import get_messages
from django.test import Client

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client: Client) -> Client:
    client.force_login(User.objects.create_superuser("root", password="Root-pass-1"))  # noqa: S106
    return client


def _shown_password(response: object) -> str:
    text = " ".join(str(m) for m in get_messages(response.wsgi_request))  # type: ignore[attr-defined]
    return text.split("<code>")[1].split("</code>")[0]


def test_add_user_asks_only_username_and_gives_temp_password(admin_client: Client) -> None:
    page = admin_client.get("/admin/accounts/user/add/").content.decode()
    assert 'name="username"' in page and 'name="password1"' not in page
    response = admin_client.post("/admin/accounts/user/add/", {"username": "naraa"})
    assert response.status_code == 302
    user = User.objects.get(username="naraa")
    assert user.must_change_password and user.check_password(_shown_password(response))


def test_password_page_has_no_password_inputs_and_resets(admin_client: Client) -> None:
    user = User.objects.create_user("bold", password="Old-pass-1")  # noqa: S106
    url = f"/admin/accounts/user/{user.pk}/password/"
    page = admin_client.get(url).content.decode()
    assert "Түр нууц үг үүсгэх" in page and 'name="password1"' not in page
    response = admin_client.post(url)
    assert response.status_code == 302
    user.refresh_from_db()
    new = _shown_password(response)
    assert user.must_change_password and user.check_password(new) and not user.check_password("Old-pass-1")


def test_reset_logged_on_linked_employee_without_password(admin_client: Client) -> None:
    from employees.models import ActivityEntry
    from leave.tests.conftest import make_employee

    root = User.objects.get(username="root")
    employee = make_employee(root, hired=__import__("datetime").date(2024, 3, 1))
    user = User.objects.create_user("saraa", password="Old-pass-1")  # noqa: S106
    employee.user = user
    employee.save(update_fields=["user"])
    response = admin_client.post(f"/admin/accounts/user/{user.pk}/password/")
    entry = ActivityEntry.objects.get(employee=employee, message="Нууц үг шинэчилсэн")
    assert entry.by == root and _shown_password(response) not in str(entry.changes)


def test_staff_without_change_permission_cannot_reset(client: Client) -> None:
    clerk = User.objects.create_user("clerk", password="Clerk-pass-1", is_staff=True)  # noqa: S106
    target = User.objects.create_user("target", password="Target-pass-1")  # noqa: S106
    client.force_login(clerk)
    assert client.post(f"/admin/accounts/user/{target.pk}/password/").status_code == 403
    target.refresh_from_db()
    assert target.check_password("Target-pass-1")


def test_change_page_explains_temp_password(admin_client: Client) -> None:
    user = User.objects.create_user("tsetseg", password="Old-pass-1")  # noqa: S106
    page = admin_client.get(f"/admin/accounts/user/{user.pk}/change/").content.decode()
    assert "Түр нууц үг үүсгэх" in page and "../password/" in page


def test_user_page_carries_role_permissions(admin_client: Client) -> None:
    import json

    from django.contrib.auth.models import Group

    user = User.objects.create_user("perms", password="Old-pass-1")  # noqa: S106
    page = admin_client.get(f"/admin/accounts/user/{user.pk}/change/").content.decode()
    data = json.loads(page.split('id="role-permissions" type="application/json">')[1].split("</script>")[0])
    hr = Group.objects.get(name="HR")
    assert data[str(hr.pk)]["name"] == "HR"
    assert sorted(data[str(hr.pk)]["perms"]) == sorted(hr.permissions.values_list("pk", flat=True))
    assert "data-perm-count" in page


def test_switches_have_plain_labels(admin_client: Client) -> None:
    user = User.objects.create_user("labels", password="Old-pass-1")  # noqa: S106
    page = admin_client.get(f"/admin/accounts/user/{user.pk}/change/").content.decode()
    assert "Удирдлагын хэсэгт нэвтрэх" in page and "Бүх эрхтэй (супер админ)" in page


def _change_data(user: User, **override: object) -> dict[str, object]:
    data: dict[str, object] = {
        "username": user.username,
        "is_active": "on",
        "is_staff": "on",
        "is_superuser": "on",
        "date_joined_0": "2026-01-01",
        "date_joined_1": "00:00:00",
    }
    data.update(override)
    return {k: v for k, v in data.items() if v is not None}


def test_last_superuser_cannot_lose_rights(admin_client: Client) -> None:
    root = User.objects.get(username="root")
    url = f"/admin/accounts/user/{root.pk}/change/"
    for switch in ("is_superuser", "is_staff", "is_active"):
        admin_client.post(url, _change_data(root, **{switch: None}))  # locked: the posted value is ignored
        root.refresh_from_db()
        assert root.is_superuser and root.is_staff and root.is_active


def test_superuser_can_be_demoted_when_another_remains(admin_client: Client) -> None:
    other = User.objects.create_superuser("root2", password="Root-pass-2")  # noqa: S106
    response = admin_client.post(f"/admin/accounts/user/{other.pk}/change/", _change_data(other, is_superuser=None))
    assert response.status_code == 302
    other.refresh_from_db()
    assert not other.is_superuser


def test_last_superuser_cannot_be_deleted(admin_client: Client) -> None:
    root = User.objects.get(username="root")
    assert admin_client.post(f"/admin/accounts/user/{root.pk}/delete/", {"post": "yes"}).status_code == 403
    other = User.objects.create_user("plain", password="Plain-pass-1")  # noqa: S106
    admin_client.post(
        "/admin/accounts/user/",
        {"action": "delete_selected", "_selected_action": [root.pk, other.pk], "post": "yes"},
    )
    assert User.objects.filter(username="root").exists()


def test_superuser_deletable_when_another_remains(admin_client: Client) -> None:
    other = User.objects.create_superuser("root3", password="Root-pass-3")  # noqa: S106
    admin_client.post(f"/admin/accounts/user/{other.pk}/delete/", {"post": "yes"})
    assert not User.objects.filter(pk=other.pk).exists()


def test_last_superuser_switches_are_locked_on_page(admin_client: Client) -> None:
    root = User.objects.get(username="root")
    page = admin_client.get(f"/admin/accounts/user/{root.pk}/change/").content.decode()
    assert "Сүүлийн супер админ тул унтраах боломжгүй" in page
    User.objects.create_superuser("root4", password="Root-pass-4")  # noqa: S106
    page = admin_client.get(f"/admin/accounts/user/{root.pk}/change/").content.decode()
    assert "Сүүлийн супер админ тул унтраах боломжгүй" not in page


def test_form_still_refuses_if_lock_bypassed() -> None:
    from accounts.admin import LAST_ADMIN_MESSAGE, TempPasswordUserChangeForm

    root = User.objects.create_superuser("solo", password="Solo-pass-1")  # noqa: S106
    form = TempPasswordUserChangeForm(instance=root)
    form.fields["is_superuser"].disabled = False
    form.cleaned_data = {"is_active": True, "is_staff": True, "is_superuser": False}
    form._errors = form.error_class()
    with pytest.raises(Exception, match=LAST_ADMIN_MESSAGE[:20]):
        form.clean()
