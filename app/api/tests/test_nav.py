import secrets

import pytest
from accounts import modules
from accounts.models import User
from accounts.nav import top_nav
from accounts.roles import HR
from django.contrib.auth.models import Group, Permission
from django.test import Client, RequestFactory
from django.urls import resolve
from employees.templatetags.hr import own_record
from leave.templatetags.leave_tags import requests_nav

pytestmark = pytest.mark.django_db

PASSWORD = secrets.token_urlsafe(16)
SLOT_LABEL = "Орон тооны төлөвлөгөө"
STAFF_LABEL = "Ажилтнууд"


@pytest.fixture(autouse=True)
def _fresh_module_cache() -> object:
    modules.clear_cache()
    yield
    modules.clear_cache()


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("nav-hr", password=PASSWORD, is_active=True)
    user.groups.add(Group.objects.get_or_create(name=HR)[0])
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="employees", codename="manage_position_slots")
    )
    return user


def _direct_groups(user: User, path: str) -> list[object]:
    request = RequestFactory().get("/")
    request.user = user
    request.resolver_match = resolve(path)
    context = {"request": request}
    return top_nav(request, bool(own_record(context)), requests_nav(context))


def test_nav_matches_template(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    body = client.get("/api/v1/nav", {"path": "/employees/"}).json()

    assert [g["key"] for g in body] == [g.key for g in _direct_groups(hr_user, "/employees/")]


def test_nav_active_from_path(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    body = client.get("/api/v1/nav", {"path": "/employees/"}).json()

    active_groups = [g["key"] for g in body if g["active"]]
    assert active_groups == ["employees"]
    employees = next(g for g in body if g["key"] == "employees")
    staff_items = [i for i in employees["items"] if i["label"] == STAFF_LABEL]
    assert staff_items and staff_items[0]["active"] is True


def test_nav_module_off_hides(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)
    before = client.get("/api/v1/nav", {"path": "/employees/"}).json()
    assert SLOT_LABEL in [i["label"] for g in before for i in g["items"]]

    modules.set_state({"slots": False})
    after = client.get("/api/v1/nav", {"path": "/employees/"}).json()

    assert SLOT_LABEL not in [i["label"] for g in after for i in g["items"]]


def test_nav_anonymous_401(client: Client) -> None:
    response = client.get("/api/v1/nav", {"path": "/employees/"})

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_nav_ignores_query_in_path(client: Client, hr_user: User) -> None:
    client.force_login(hr_user)

    body = client.get("/api/v1/nav", {"path": "/employees/?x=1"}).json()

    assert [g["key"] for g in body if g["active"]] == ["employees"]
