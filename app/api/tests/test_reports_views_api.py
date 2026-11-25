"""The saved-view routes of the report API: the «Хадгалах», «Засах» and «Устгах» pop-ups (GET forms) and their writes.

The rules are reports.services.saved_views (its own tests cover them); these tests pin the API's shape: 401 without a
login, 404 for a report without saved views or a private view of another user (the name is never in that body), 403
for a view the viewer may not change, a refused write as 200 with ok false and the form's errors, the redirects, the
no-store header on the forms, and the CSRF check every /api/v1 write has.
"""

import json
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse
from reports.models import SavedView
from reports.registry import REPORTS
from reports.services.saved_views import DUPLICATE_NAME
from reports.types import Column, Report

from api.popups import FORBIDDEN, NOT_FOUND
from api.tests.logs_support import NOT_LOGGED_IN

pytestmark = pytest.mark.django_db

KEY = "api-report-views-test"
BASE = f"/api/v1/reports/{KEY}"
NEW_URL = f"{BASE}/views/new"
VIEWS_URL = f"{BASE}/views"
NOT_FOUND_BODY = {"field_errors": {}, "form_errors": [NOT_FOUND]}
FORBIDDEN_BODY = {"field_errors": {}, "form_errors": [FORBIDDEN], "code": "forbidden"}
PASSWORD = "x-long-pass-123"  # noqa: S105
PRIVATE_NAME = "Тусгай нууц харагдац"


def _login(role: str, name: str, *, enforce_csrf: bool = False) -> Client:
    """A client signed in as a user of the role (created once per name)."""
    client = Client(enforce_csrf_checks=enforce_csrf)
    user = User.objects.filter(username=name).first()
    if user is None:
        user = User.objects.create_user(name, password=PASSWORD)
        user.groups.add(Group.objects.get(name=role))
    client.force_login(User.objects.get(pk=user.pk))
    return client


def _register(monkeypatch: pytest.MonkeyPatch, *, saved_views: bool = True) -> Report:
    """A report with a name column (everyone may see it) and saved views on or off."""
    report = Report(
        key=KEY,
        title="Тестийн тайлан",
        filters=(),
        columns=(Column(key="name", label="Нэр", value=lambda r: r.name, group="Ажилтан"),),
        default_columns=("name",),
        rows=lambda user, filters: [],
        saved_views=saved_views,
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    return report


def _post(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, json.dumps(body), content_type="application/json")


def _view(author: User, name: str, *, visibility: str = "shared", is_default: bool = False) -> SavedView:
    return SavedView.objects.create(
        report=KEY,
        name=name,
        query="cols=name",
        author=author,
        visibility=visibility,
        is_default=is_default,
    )


@pytest.fixture
def registered(monkeypatch: pytest.MonkeyPatch) -> Report:
    return _register(monkeypatch)


def test_new_form_prefills_viewers_own_query(registered: Report) -> None:
    # initial_query is only parse_filters of the viewer's own address (the unknown keys are dropped); the server
    # cleans it for the viewer on save, so this prefill is not a privacy guarantee
    client = _login("HR", "views_api_form_hr")

    response = client.get(f"{NEW_URL}?cols=name&bogus=1&sort=--x")

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "cols=name"
    assert body["name"] == "" and body["visibility"] == "shared" and body["is_default"] is False
    assert body["can_delete"] is False and body["view_id"] is None
    assert response["Cache-Control"] == "no-store"


def test_every_saved_view_route_needs_a_signed_in_user(registered: Report) -> None:
    anonymous = Client()
    view = _view(_login_user("views_api_anon_author"), "Холбоо")

    responses = [
        anonymous.get(NEW_URL),
        anonymous.get(f"/api/v1/reports/views/{view.pk}"),
        _post(anonymous, VIEWS_URL, {"name": "Шинэ"}),
        _post(anonymous, f"/api/v1/reports/views/{view.pk}", {"name": "Шинэ"}),
        _post(anonymous, f"/api/v1/reports/views/{view.pk}/delete", {}),
    ]
    for response in responses:
        assert response.status_code == 401
        assert response.json() == NOT_LOGGED_IN


def _login_user(name: str) -> User:
    user = User.objects.filter(username=name).first()
    if user is None:
        user = User.objects.create_user(name, password=PASSWORD)
        user.groups.add(Group.objects.get(name="HR"))
    return user


def test_create_returns_view_address(registered: Report) -> None:
    client = _login("HR", "views_api_create_hr")

    response = _post(client, VIEWS_URL, {"name": "Холбоо", "query": "cols=name&bogus=1"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": True,
        "redirect": f"/reports/{KEY}/?cols=name",
        "error": "",
        "form_errors": [],
        "field_errors": {},
    }
    view = SavedView.objects.get(name="Холбоо")
    assert view.query == "cols=name" and view.visibility == "shared"


def test_create_duplicate_name_is_field_error(registered: Report) -> None:
    client = _login("HR", "views_api_dup_hr")
    _post(client, VIEWS_URL, {"name": "Холбоо", "query": "cols=name"})

    response = _post(client, VIEWS_URL, {"name": "Холбоо ", "query": "cols=name"})  # the name is trimmed

    body = response.json()
    assert body["ok"] is False and body["redirect"] == ""
    assert body["field_errors"] == {"name": [DUPLICATE_NAME]}
    assert SavedView.objects.filter(report=KEY, name="Холбоо").count() == 1


def test_create_blank_name_is_field_error(registered: Report) -> None:
    client = _login("HR", "views_api_blank_hr")

    body = _post(client, VIEWS_URL, {"name": "   ", "query": "cols=name"}).json()

    assert body["ok"] is False
    assert "name" in body["field_errors"] and body["field_errors"]["name"]
    assert not SavedView.objects.filter(report=KEY).exists()


def test_create_for_report_without_saved_views_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(monkeypatch, saved_views=False)
    client = _login("HR", "views_api_nosaved_hr")

    assert client.get(NEW_URL).json() == NOT_FOUND_BODY
    assert _post(client, VIEWS_URL, {"name": "Холбоо"}).status_code == 404


def test_edit_form_and_update_keep_query(registered: Report) -> None:
    author = _login("HR", "views_api_edit_author")
    _post(author, VIEWS_URL, {"name": "Холбоо", "query": "cols=name"})
    view = SavedView.objects.get(name="Холбоо")

    form = author.get(f"/api/v1/reports/views/{view.pk}")
    assert form.status_code == 200
    body = form.json()
    assert body["name"] == "Холбоо" and body["visibility"] == "shared" and body["is_default"] is False
    assert body["query"] == "" and body["can_delete"] is True and body["view_id"] == view.pk
    assert form["Cache-Control"] == "no-store"

    saved = _post(author, f"/api/v1/reports/views/{view.pk}", {"name": "Жишээ", "query": "cols=other"})

    assert saved.json() == {"ok": True, "redirect": "", "error": "", "form_errors": [], "field_errors": {}}
    view.refresh_from_db()
    assert view.name == "Жишээ" and view.query == "cols=name"  # the query is not used on an edit


def test_edit_form_never_returns_stored_query(monkeypatch: pytest.MonkeyPatch) -> None:
    # The author may see the salary column; the manager (reports.manage_saved_views) does not, so the stored
    # query naming it must not reach the manager's edit form.
    report = Report(
        key=KEY,
        title="Тестийн тайлан",
        filters=(),
        columns=(
            Column(key="name", label="Нэр", value=lambda r: r.name, group="Ажилтан"),
            Column(key="pay", label="Цалин", value=lambda r: None, group="Ажилтан", needs="macs.view_salary"),
        ),
        default_columns=("name",),
        rows=lambda user, filters: [],
        saved_views=True,
    )
    monkeypatch.setitem(REPORTS, KEY, report)
    author = _login_user("views_api_hidden_author")
    view = SavedView.objects.create(
        report=KEY, name="Цалинтай", query="cols=name,pay", author=author, visibility="shared"
    )
    manager = _login_user("views_api_hidden_manager")
    manage = Permission.objects.get(codename="manage_saved_views", content_type__app_label="reports")
    manager.user_permissions.add(manage)
    client = Client()
    client.force_login(User.objects.get(pk=manager.pk))

    response = client.get(f"/api/v1/reports/views/{view.pk}")

    assert response.status_code == 200
    assert response.json()["query"] == ""
    assert "pay" not in response.content.decode()


def test_update_without_visibility_keeps_the_private_view_private(registered: Report) -> None:
    author = _login("HR", "views_api_vis_author")
    view = _view(User.objects.get(username="views_api_vis_author"), "Миний", visibility="private")

    body = _post(author, f"/api/v1/reports/views/{view.pk}", {"name": "Миний шинэ"}).json()

    assert body["ok"] is True
    view.refresh_from_db()
    assert view.name == "Миний шинэ" and view.visibility == "private"


def test_update_without_is_default_keeps_it(registered: Report) -> None:
    author = _login("HR", "views_api_default_author")
    view = _view(User.objects.get(username="views_api_default_author"), "Үндсэн", is_default=True)

    body = _post(author, f"/api/v1/reports/views/{view.pk}", {"name": "Үндсэн шинэ"}).json()

    assert body["ok"] is True
    view.refresh_from_db()
    assert view.name == "Үндсэн шинэ" and view.is_default is True


def test_edit_other_users_private_view_404(registered: Report) -> None:
    owner = _login("HR", "views_api_priv_owner")
    other = _login("HR", "views_api_priv_other")
    _post(owner, VIEWS_URL, {"name": PRIVATE_NAME, "query": "cols=name", "visibility": "private"})
    view = SavedView.objects.get(name=PRIVATE_NAME)

    form = other.get(f"/api/v1/reports/views/{view.pk}")
    write = _post(other, f"/api/v1/reports/views/{view.pk}", {"name": "Өөр"})
    delete = _post(other, f"/api/v1/reports/views/{view.pk}/delete", {})

    for response in (form, write, delete):
        assert response.status_code == 404
        assert response.json() == NOT_FOUND_BODY
        assert PRIVATE_NAME not in response.content.decode()
    assert SavedView.objects.filter(pk=view.pk, name=PRIVATE_NAME).exists()


def test_edit_by_non_author_403(registered: Report) -> None:
    author = _login("HR", "views_api_shared_author")
    other = _login("HR", "views_api_shared_other")
    _post(author, VIEWS_URL, {"name": "Холбоо", "query": "cols=name"})
    view = SavedView.objects.get(name="Холбоо")

    assert other.get(f"/api/v1/reports/views/{view.pk}").json() == FORBIDDEN_BODY
    assert _post(other, f"/api/v1/reports/views/{view.pk}", {"name": "Өөр"}).json() == FORBIDDEN_BODY
    assert _post(other, f"/api/v1/reports/views/{view.pk}/delete", {}).json() == FORBIDDEN_BODY
    view.refresh_from_db()
    assert view.name == "Холбоо"


def test_delete_redirects_to_bare_report(registered: Report) -> None:
    author = _login("HR", "views_api_delete_author")
    _post(author, VIEWS_URL, {"name": "Холбоо", "query": "cols=name"})
    view = SavedView.objects.get(name="Холбоо")

    response = _post(author, f"/api/v1/reports/views/{view.pk}/delete", {})

    assert response.json() == {
        "ok": True,
        "redirect": reverse("reports:report", args=[KEY]),
        "error": "",
        "form_errors": [],
        "field_errors": {},
    }
    assert not SavedView.objects.filter(pk=view.pk).exists()


def test_delete_requires_post(registered: Report) -> None:
    author = _login("HR", "views_api_getdel_author")
    view = _view(User.objects.get(username="views_api_getdel_author"), "Холбоо")

    assert author.get(f"/api/v1/reports/views/{view.pk}/delete").status_code == 405
    assert SavedView.objects.filter(pk=view.pk).exists()


def test_writes_need_csrf_like_other_routes(registered: Report) -> None:
    client = _login("HR", "views_api_csrf_hr", enforce_csrf=True)

    response = _post(client, VIEWS_URL, {"name": "Холбоо", "query": "cols=name"})

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
    assert not SavedView.objects.filter(report=KEY).exists()


def test_page_api_has_no_save_url(registered: Report) -> None:
    client = _login("HR", "views_api_page_hr")
    _view(User.objects.get(username="views_api_page_hr"), "Холбоо")

    body = client.get(BASE).json()

    assert body["head"] is not None and body["head"]["saved"] is not None
    assert "save_url" not in body["head"]["saved"]
    assert set(body["head"]["saved"]) == {
        "plain_url",
        "options",
        "templates",
        "current_view",
        "template_current",
        "can_edit_view",
    }
