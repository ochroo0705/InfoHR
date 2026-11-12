"""Saving a workspace tab as a saved table (saved tables Task 4): the save pop-up in the table pane and ws_save_table.

No Firebird: the gate and the fake host come from test_ws_views_table (fixtures `gate` and `host`).
"""

from collections.abc import Callable

from accounts.models import User
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.test import Client
from django.urls import reverse

from assistant.models import SavedTable, WorkspaceTab
from assistant.tests import test_ws_views_table as table_tests
from assistant.tests.test_ws_views_table import BASE_SQL, FakeHost, _pane, _url
from assistant.ws_service import add_version, new_tab
from assistant.ws_sql import Filter, Spec, spec_from_json, spec_to_json

# The fixtures of the table tests, bound under their own names (re-importing them would shadow the names).
_clear_gate_cache = table_tests._clear_gate_cache
gate = table_tests.gate
host = table_tests.host

COLUMNS = ("ID", "NAME")
LABELS = '{"NAME": "Нэр"}'


def _tab_with(user: User, settings: str = "", sql: str = BASE_SQL) -> WorkspaceTab:
    tab = new_tab(user, "Тест хүснэгт")
    add_version(tab, "Асуулт", sql, settings, labels=LABELS)
    return tab


def _save(client: Client, tab: WorkspaceTab, data: dict[str, str]) -> HttpResponse:
    return client.post(reverse("assistant:ws_save_table", args=[tab.pk]), data)


def _messages(response: HttpResponse) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def test_save_stores_the_sql_labels_settings_author_and_visibility(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with(user)
    client.force_login(user)

    response = _save(
        client,
        tab,
        {
            "name": "  Ажилтнууд  ",
            "visibility": "private",
            "sort": "NAME:desc",
            "f": "ID|gt|1",
            "cols": "ID,NAME",
            "group": "",
        },
    )

    table = SavedTable.objects.get()
    assert response.status_code == 302
    assert response["Location"] == reverse("assistant:saved_page", args=[table.pk])
    assert table.name == "Ажилтнууд"
    assert table.sql == BASE_SQL
    assert table.labels == LABELS
    assert table.author == user
    assert table.visibility == "private"
    spec = spec_from_json(table.settings, COLUMNS)
    assert spec.sort == (("NAME", "desc"),)
    assert spec.filters == (Filter("ID", "gt", "1"),)
    assert spec.columns == ("ID", "NAME")


def test_posted_settings_win_over_the_tabs_saved_settings(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with(user, settings=spec_to_json(Spec(sort=(("ID", "asc"),))))
    client.force_login(user)

    _save(client, tab, {"name": "Жагсаалт", "sort": "NAME:desc"})

    spec = spec_from_json(SavedTable.objects.get().settings, COLUMNS)
    assert spec.sort == (("NAME", "desc"),)


def test_without_tool_parameters_the_tabs_saved_settings_are_kept(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with(user, settings=spec_to_json(Spec(sort=(("ID", "asc"),))))
    client.force_login(user)

    _save(client, tab, {"name": "Жагсаалт"})

    spec = spec_from_json(SavedTable.objects.get().settings, COLUMNS)
    assert spec.sort == (("ID", "asc"),)


def test_visibility_defaults_to_shared_and_an_unknown_value_is_shared(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with(user)
    client.force_login(user)

    _save(client, tab, {"name": "Первый"})
    _save(client, tab, {"name": "Хоёр", "visibility": "everyone"})

    assert set(SavedTable.objects.values_list("visibility", flat=True)) == {"shared"}


def test_blank_name_saves_nothing_and_says_why(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with(user)
    client.force_login(user)

    response = _save(client, tab, {"name": "   "})

    assert response.status_code == 302
    assert response["Location"] == reverse("assistant:workspace_tab", args=[tab.pk])
    assert not SavedTable.objects.exists()
    assert "Нэр оруулна уу." in _messages(response)


def test_an_empty_tab_saves_nothing(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = new_tab(user, "Хоосон")
    client.force_login(user)

    response = _save(client, tab, {"name": "Жагсаалт"})

    assert not SavedTable.objects.exists()
    assert "Хүснэгт хоосон байна." in _messages(response)


def test_a_refused_base_run_saves_nothing(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with(user)
    host.views_empty = True
    client.force_login(user)

    response = _save(client, tab, {"name": "Жагсаалт"})

    assert not SavedTable.objects.exists()
    assert "Танд асуух өгөгдлийн хүснэгт алга." in _messages(response)


def test_another_users_tab_is_404(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    owner, intruder = role_user("staff"), role_user("staff")
    tab = _tab_with(owner)
    client.force_login(intruder)

    response = _save(client, tab, {"name": "Бусад"})

    assert response.status_code == 404
    assert not SavedTable.objects.exists()


def test_save_is_post_only(db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost) -> None:
    user = role_user("staff")
    tab = _tab_with(user)
    client.force_login(user)

    assert client.get(reverse("assistant:ws_save_table", args=[tab.pk])).status_code == 405


def test_the_table_pane_offers_the_save_pop_up_and_the_saved_page_does_not(
    db: None, client: Client, role_user: Callable[[str], User], gate, host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab_with(user)
    client.force_login(user)

    html = _pane(client, _url(tab, "sort=NAME:desc&page=0"))

    assert "Тайланд хадгалах" in html
    assert reverse("assistant:ws_save_table", args=[tab.pk]) in html
    assert 'name="visibility"' in html
    assert 'name="sort" value="NAME:desc"' in html  # the current settings travel with the form

    table = SavedTable.objects.create(name="Хадгалсан", sql=BASE_SQL, author=user)
    saved_html = client.get(reverse("assistant:saved_page", args=[table.pk])).content.decode()
    assert "Тайланд хадгалах" not in saved_html
