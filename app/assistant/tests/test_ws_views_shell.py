"""The workspace page shell: login, the access gate, own tabs only, POST-only actions, and the nav entry.

No Firebird: the gate's switch and database seams are monkeypatched on assistant.sqlanswer, and the catalogue seam is
assistant.ws_views._catalogue_views.
"""

from collections.abc import Iterator

import pytest
from accounts.models import User
from accounts.nav import top_nav
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import Client, RequestFactory
from django.urls import resolve, reverse
from sqlcore.catalogue import Column, View

from assistant import sqlanswer, ws_views
from assistant.models import WorkspaceTab
from assistant.ws_limits import MAX_TABS
from assistant.ws_service import new_tab

EMPLOYEES = View(
    name="GOV_EMPLOYEES",
    description="Employees you may see",
    columns=(Column("ID", "employee id"), Column("NAME", "full name")),
)
NO_REQUESTS = {"show": False, "count": 0}


@pytest.fixture(autouse=True)
def _clear_gate_cache() -> Iterator[None]:
    """The gate answer is cached per user for a minute: every test starts with an empty cache, and leaves none behind."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """The gate starts closed (switch off). A test opens it with `open_gate()`."""
    state: dict[str, object] = {"views": ()}
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    monkeypatch.setattr(sqlanswer, "_database_ready", lambda: True)
    monkeypatch.setattr(ws_views, "_catalogue_views", lambda user: state["views"])
    return state


def open_gate(monkeypatch: pytest.MonkeyPatch, state: dict[str, object]) -> None:
    """Open the gate for every user. Clears the cached answers, since the gate changed within the test."""
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    state["views"] = (EMPLOYEES,)
    cache.clear()


def test_workspace_requires_login(db: None, client: Client, gate: dict[str, object]) -> None:
    response = client.get(reverse("assistant:workspace"))
    assert response.status_code == 302
    assert "login" in response["Location"]


def test_gate_off_gives_404(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    client.force_login(user)
    tab = new_tab(user)  # a real tab, so the 404 is the gate's and not a missing row

    # The switch is off: every workspace address answers 404.
    assert client.get(reverse("assistant:workspace")).status_code == 404
    assert client.get(reverse("assistant:workspace_tab", args=[tab.pk])).status_code == 404
    assert client.post(reverse("assistant:ws_new")).status_code == 404
    assert client.post(reverse("assistant:ws_rename", args=[tab.pk]), {"title": "Х"}).status_code == 404
    assert client.post(reverse("assistant:ws_close", args=[tab.pk])).status_code == 404
    assert WorkspaceTab.objects.filter(pk=tab.pk, owner=user).exists()

    # The switch is on but the viewer has no view to read: still 404.
    open_gate(monkeypatch, gate)
    gate["views"] = ()
    cache.clear()  # the gate changed within this test
    assert client.get(reverse("assistant:workspace")).status_code == 404


def test_other_users_tab_404(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    owner = role_user("staff")
    intruder = role_user("staff")
    tab = new_tab(owner, "Миний хүснэгт")
    open_gate(monkeypatch, gate)
    client.force_login(intruder)

    assert client.get(reverse("assistant:workspace_tab", args=[tab.pk])).status_code == 404
    assert client.post(reverse("assistant:ws_rename", args=[tab.pk]), {"title": "Бусад"}).status_code == 404
    assert client.post(reverse("assistant:ws_close", args=[tab.pk])).status_code == 404

    tab.refresh_from_db()
    assert tab.title == "Миний хүснэгт"
    assert WorkspaceTab.objects.filter(pk=tab.pk).exists()


def test_new_close_rename_post_only_and_own_tabs(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    open_gate(monkeypatch, gate)
    client.force_login(user)

    # GET is refused on the three actions.
    assert client.get(reverse("assistant:ws_new")).status_code == 405
    tab = new_tab(user, "Анхны")
    assert client.get(reverse("assistant:ws_rename", args=[tab.pk])).status_code == 405
    assert client.get(reverse("assistant:ws_close", args=[tab.pk])).status_code == 405

    # POST new makes one tab for the viewer and opens it.
    response = client.post(reverse("assistant:ws_new"))
    assert response.status_code == 302
    created = WorkspaceTab.objects.filter(owner=user).exclude(pk=tab.pk).get()
    assert response["Location"] == reverse("assistant:workspace_tab", args=[created.pk])

    # POST rename changes the title; an empty title changes nothing.
    client.post(reverse("assistant:ws_rename", args=[tab.pk]), {"title": "  Шинэ нэр  "})
    tab.refresh_from_db()
    assert tab.title == "Шинэ нэр"
    client.post(reverse("assistant:ws_rename", args=[tab.pk]), {"title": "   "})
    tab.refresh_from_db()
    assert tab.title == "Шинэ нэр"

    # POST close deletes the tab and sends the viewer to the workspace.
    response = client.post(reverse("assistant:ws_close", args=[tab.pk]))
    assert response.status_code == 302
    assert not WorkspaceTab.objects.filter(pk=tab.pk).exists()


def test_workspace_page_lists_own_tabs_and_opens_newest(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    older = new_tab(user, "Эхний")
    newer = new_tab(user, "Сүүлийн")
    open_gate(monkeypatch, gate)
    client.force_login(user)

    response = client.get(reverse("assistant:workspace"))
    assert response.status_code == 200
    assert response.context["current"].pk == newer.pk
    assert [t.pk for t in response.context["tabs"]] == [older.pk, newer.pk]
    assert 'id="ws-table-pane"' in response.content.decode()
    assert 'id="ws-chat-pane"' in response.content.decode()


def test_new_past_limit_shows_message_and_redirects(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    for _ in range(MAX_TABS):
        new_tab(user)
    open_gate(monkeypatch, gate)
    client.force_login(user)

    response = client.post(reverse("assistant:ws_new"), follow=True)

    assert response.status_code == 200  # the page renders; no 500
    assert response.redirect_chain[-1][0] == reverse("assistant:workspace")
    assert "Нээлттэй хүснэгт" in response.content.decode()
    assert WorkspaceTab.objects.filter(owner=user).count() == MAX_TABS


def test_rename_cuts_title_to_80(db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]) -> None:
    user = role_user("staff")
    tab = new_tab(user)
    open_gate(monkeypatch, gate)
    client.force_login(user)

    client.post(reverse("assistant:ws_rename", args=[tab.pk]), {"title": "я" * 100})

    tab.refresh_from_db()
    assert tab.title == "я" * 80


def test_tab_title_is_escaped_on_the_page(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    tab = new_tab(user, "<script>alert(1)</script>")
    open_gate(monkeypatch, gate)
    client.force_login(user)

    content = client.get(reverse("assistant:workspace_tab", args=[tab.pk])).content.decode()

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content
    assert "<script>alert(1)</script>" not in content


def test_gate_error_fails_closed_without_500(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object], caplog: pytest.LogCaptureFixture
) -> None:
    user = role_user("staff")
    open_gate(monkeypatch, gate)

    def broken(_user: object) -> tuple:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(ws_views, "_catalogue_views", broken)
    client.force_login(user)

    # The workspace page answers 404 (the gate is closed when it cannot be worked out).
    assert client.get(reverse("assistant:workspace")).status_code == 404
    # A normal page still renders: the nav check fails safe, with no entry.
    assert client.get(reverse("employees:today")).status_code < 500
    request = RequestFactory().get("/")
    request.user = User.objects.get(pk=user.pk)
    request.resolver_match = resolve(reverse("assistant:workspace"))
    labels = [item.label for group in top_nav(request, False, NO_REQUESTS) for item in group.items]
    assert "Асуулт, хүснэгт" not in labels
    # Only the exception's type name is logged, never its message.
    assert "RuntimeError" in caplog.text
    assert "secret detail" not in caplog.text


def test_nav_entry_only_when_gate_open(
    db: None, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    user = User.objects.get(pk=user.pk)  # fresh object: no cached permissions

    def reports_items() -> list[str]:
        request = RequestFactory().get("/")
        request.user = user
        request.resolver_match = resolve(reverse("assistant:workspace"))
        groups = top_nav(request, False, NO_REQUESTS)
        return [item.label for group in groups if group.key == "assistant" for item in group.items]

    assert "Асуулт, хүснэгт" not in reports_items()
    assert "Хадгалсан хүснэгт" not in reports_items()

    open_gate(monkeypatch, gate)
    assert "Асуулт, хүснэгт" in reports_items()
    assert "Хадгалсан хүснэгт" in reports_items()

    gate["views"] = ()  # the catalogue is empty for this viewer: no entry
    cache.clear()  # the gate changed within this test
    assert "Асуулт, хүснэгт" not in reports_items()


def test_gate_answer_is_cached_for_the_viewer(
    db: None, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    calls: list[int] = []

    def counted(viewer: User) -> tuple:
        calls.append(viewer.pk)
        return (EMPLOYEES,)

    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(ws_views, "_catalogue_views", counted)

    assert ws_views.can_use_workspace(user) is True
    assert ws_views.can_use_workspace(user) is True
    assert calls == [user.pk]  # the second call, within the window, did not build the catalogue again


def test_gate_answer_is_per_user(
    db: None, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    allowed = role_user("staff")
    closed = role_user("staff")
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(ws_views, "_catalogue_views", lambda viewer: (EMPLOYEES,) if viewer.pk == allowed.pk else ())

    assert ws_views.can_use_workspace(allowed) is True
    assert ws_views.can_use_workspace(closed) is False
    assert ws_views.can_use_workspace(allowed) is True


def test_gate_error_is_not_cached(
    db: None, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    state = {"broken": True}

    def flaky(viewer: User) -> tuple:
        if state["broken"]:
            raise RuntimeError("secret detail")
        return (EMPLOYEES,)

    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: True)
    monkeypatch.setattr(ws_views, "_catalogue_views", flaky)

    assert ws_views.can_use_workspace(user) is False  # fails closed
    state["broken"] = False
    assert ws_views.can_use_workspace(user) is True  # the error was not kept as the answer


def test_anonymous_user_never_reaches_the_gate(
    db: None, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: calls.append("setting") or True)
    monkeypatch.setattr(ws_views, "_catalogue_views", lambda viewer: calls.append("catalogue") or (EMPLOYEES,))

    assert ws_views.can_use_workspace(AnonymousUser()) is False
    assert calls == []


def test_close_says_so_and_the_page_has_the_menu_and_a_live_region(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    tab = new_tab(user, "Туршилт")
    other = new_tab(user, "Өөр")
    open_gate(monkeypatch, gate)
    client.force_login(user)

    page = client.get(reverse("assistant:workspace_tab", args=[tab.pk])).content.decode()
    assert "Үйлдэл ▾" in page
    assert "Хүснэгтийг хаах" in page
    assert 'id="ws-live"' in page
    assert "bg-red-600" not in page  # «Хаах» is red text in the menu, no longer a solid red button
    assert "Шинэ</button>" in page

    followed = client.post(reverse("assistant:ws_close", args=[tab.pk]), follow=True)
    assert "«Туршилт» хүснэгт хаагдлаа." in followed.content.decode()
    assert other.title in followed.content.decode()


def test_workspace_with_no_tab_opens_a_new_empty_tab(
    db: None, client: Client, role_user, monkeypatch: pytest.MonkeyPatch, gate: dict[str, object]
) -> None:
    user = role_user("staff")
    open_gate(monkeypatch, gate)
    client.force_login(user)

    response = client.get(reverse("assistant:workspace"))
    tab = WorkspaceTab.objects.get(owner=user)
    assert response.status_code == 302
    assert response["Location"] == reverse("assistant:workspace_tab", args=[tab.pk])
    client.get(reverse("assistant:workspace"))
    assert WorkspaceTab.objects.filter(owner=user).count() == 1  # a second visit opens it, makes no other
