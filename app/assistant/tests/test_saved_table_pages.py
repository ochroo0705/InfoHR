"""Saved workspace tables, the pages (saved tables Task 3): the list, the page with the table tools and no chat, the
exports and the delete rule.

No Firebird: the gate and the fake host come from test_ws_views_table (fixtures `gate` and `host`), and the saved
tables are made here. Note: test_saved_views.py is a different feature (report saved views) and is not used here.
"""

from collections.abc import Callable

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from assistant import sqlanswer
from assistant.models import SavedTable
from assistant.tests import test_ws_views_table as table_tests
from assistant.tests.test_ws_views_table import BASE_SQL, FakeHost
from assistant.ws_sql import Spec, spec_to_json

# The fixtures of the table tests, bound under their own names (re-importing them would shadow the names).
_clear_gate_cache = table_tests._clear_gate_cache
gate = table_tests.gate
host = table_tests.host

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _saved(
    author: User | None,
    name: str = "Жагсаалт",
    visibility: str = "shared",
    sql: str = BASE_SQL,
    settings: str = "",
) -> SavedTable:
    return SavedTable.objects.create(
        name=name, sql=sql, labels="", settings=settings, author=author, visibility=visibility
    )


def _page(table: SavedTable) -> str:
    return reverse("assistant:saved_page", args=[table.pk])


def _table(table: SavedTable, query: str = "") -> str:
    base = reverse("assistant:saved_table", args=[table.pk])
    return f"{base}?{query}" if query else base


def _delete(table: SavedTable) -> str:
    return reverse("assistant:saved_delete", args=[table.pk])


def _manage_perm() -> Permission:
    return Permission.objects.get(codename="manage_saved_tables", content_type__app_label="assistant")


def test_list_shows_shared_and_own_private_only(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    ann, ben = role_user("staff"), role_user("staff")
    _saved(ben, "Хамтын жагсаалт", "shared")
    _saved(ben, "Бенийн хувийн", "private")
    _saved(ann, "Аннын хувийн", "private")
    client.force_login(ann)

    html = client.get(reverse("assistant:saved_list")).content.decode()

    assert "Хамтын жагсаалт" in html
    assert "Аннын хувийн" in html
    assert "Бенийн хувийн" not in html


def test_list_gives_a_delete_control_to_the_author_only(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    ann, ben = role_user("staff"), role_user("staff")
    shared = _saved(ben, "Хамтын жагсаалт")
    mine = _saved(ann, "Миний жагсаалт")
    client.force_login(ann)

    html = client.get(reverse("assistant:saved_list")).content.decode()

    assert _delete(mine) in html
    assert _delete(shared) not in html


def test_list_gives_a_delete_control_on_others_tables_with_the_permission(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    ann, ben = role_user("staff"), role_user("staff")
    shared = _saved(ben, "Хамтын жагсаалт")
    ann.user_permissions.add(_manage_perm())
    client.force_login(User.objects.get(pk=ann.pk))

    html = client.get(reverse("assistant:saved_list")).content.decode()

    assert _delete(shared) in html


def test_empty_list_says_so(db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost) -> None:
    client.force_login(role_user("staff"))

    html = client.get(reverse("assistant:saved_list")).content.decode()

    assert "Хадгалсан хүснэгт бүртгэгдээгүй" in html


def test_closed_gate_gives_404_on_every_saved_address(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("staff")
    table = _saved(user)
    monkeypatch.setattr(sqlanswer, "_setting_enabled", lambda: False)
    client.force_login(user)

    assert client.get(reverse("assistant:saved_list")).status_code == 404
    assert client.get(_page(table)).status_code == 404
    assert client.get(_table(table)).status_code == 404
    assert client.get(reverse("assistant:saved_excel", args=[table.pk])).status_code == 404
    assert client.post(_delete(table)).status_code == 404
    assert SavedTable.objects.filter(pk=table.pk).exists()


def test_another_users_private_table_is_404(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    ann, ben = role_user("staff"), role_user("staff")
    private = _saved(ben, "Бенийн хувийн", "private")
    client.force_login(ann)

    assert client.get(_page(private)).status_code == 404
    assert client.get(_table(private)).status_code == 404
    assert client.get(reverse("assistant:saved_excel", args=[private.pk])).status_code == 404
    assert client.get(reverse("assistant:saved_print", args=[private.pk])).status_code == 404
    assert client.get(reverse("assistant:saved_copy", args=[private.pk])).status_code == 404
    assert client.post(_delete(private)).status_code == 404
    assert SavedTable.objects.filter(pk=private.pk).exists()


def test_page_shows_the_table_and_no_chat(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    table = _saved(user, "Ажилтнууд", "shared")
    client.force_login(user)

    response = client.get(_page(table))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Ажилтнууд" in html
    assert "Хадгалсан хүснэгт · Хамтын" in html
    assert 'id="ws-table-pane"' in html
    assert "Aigerim" in html
    assert "ws-chat-pane" not in html
    assert "GOV_EMPLOYEES" in host.page_sql()  # the saved SQL runs, as the viewer, through the governed path


def test_page_opens_with_the_saved_settings(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    table = _saved(user, settings=spec_to_json(Spec(sort=(("NAME", "desc"),))))
    client.force_login(user)

    client.get(_page(table))

    assert "ORDER BY NAME DESC" in host.page_sql()


def test_htmx_request_gets_the_pane_alone(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    table = _saved(user)
    client.force_login(user)

    response = client.get(_table(table), HTTP_HX_REQUEST="true")
    html = response.content.decode()

    assert response.status_code == 200
    assert "<!doctype" not in html.lower()
    assert "Aigerim" in html


def test_a_viewer_tool_is_not_saved_back(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    table = _saved(user)
    client.force_login(user)

    response = client.get(_table(table, "sort=NAME:desc&page=0"), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert "ORDER BY NAME DESC" in host.page_sql()
    table.refresh_from_db()
    assert table.settings == ""


def test_excel_print_and_copy_serve_the_saved_rows(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    table = _saved(user)
    client.force_login(user)

    excel = client.get(reverse("assistant:saved_excel", args=[table.pk]))
    printed = client.get(reverse("assistant:saved_print", args=[table.pk]))
    copied = client.get(reverse("assistant:saved_copy", args=[table.pk]))

    assert excel.status_code == 200
    assert excel["Content-Type"] == XLSX_TYPE
    assert excel.content[:2] == b"PK"
    assert printed.status_code == 200
    assert "Aigerim" in printed.content.decode()
    assert copied.status_code == 200
    assert "Aigerim" in copied.content.decode()


def test_author_deletes_and_is_sent_to_the_list(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    table = _saved(user)
    client.force_login(user)

    response = client.post(_delete(table))

    assert response.status_code == 302
    assert response["Location"] == reverse("assistant:saved_list")
    assert not SavedTable.objects.filter(pk=table.pk).exists()


def test_delete_is_post_only(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    table = _saved(user)
    client.force_login(user)

    assert client.get(_delete(table)).status_code == 405
    assert SavedTable.objects.filter(pk=table.pk).exists()


def test_another_user_gets_403_on_a_shared_table(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    ann, ben = role_user("staff"), role_user("staff")
    shared = _saved(ben, "Хамтын жагсаалт")
    client.force_login(ann)

    response = client.post(_delete(shared))

    assert response.status_code == 403
    assert SavedTable.objects.filter(pk=shared.pk).exists()


def test_permission_holder_may_delete_someone_elses_table(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    ann, ben = role_user("staff"), role_user("staff")
    shared = _saved(ben, "Хамтын жагсаалт")
    ann.user_permissions.add(_manage_perm())
    client.force_login(User.objects.get(pk=ann.pk))

    response = client.post(_delete(shared))

    assert response.status_code == 302
    assert not SavedTable.objects.filter(pk=shared.pk).exists()
