"""Mongolian column labels of the workspace table: the pure rules (ws_labels.py) and what the table pane, the chips
and the copy text show (ws_views.py). No Firebird: the fake host and the gate fixtures of test_ws_views_table.py."""

# ruff: noqa: F811  (the imported fixtures are named again as test arguments)

import pytest
from django.test import Client
from django.urls import reverse
from sqlcore.catalogue import Column, View

from assistant.tests.test_ws_views_table import (  # noqa: F401  (fixtures)
    FakeHost,
    _clear_gate_cache,
    _tab,
    gate,
    host,
)
from assistant.ws_labels import COUNT_LABEL, display_names, view_labels

PEOPLE = View(
    name="GOV_EMPLOYEES",
    description="Employees",
    columns=(
        Column("ID", "employee id", label_mn="Ажилтны дугаар"),
        Column("NAME", "full name", label_mn="Нэр"),
        Column("BIRTH_DATE", "birth date", label_mn="Төрсөн огноо"),
        Column("STATE", "state", label_mn="Төлөв"),
        Column("NOTE", "no label here"),
    ),
)
CHILDREN = View(
    name="GOV_CHILDREN",
    description="Children",
    columns=(
        Column("ID", "employee id", label_mn="Ажилтны дугаар"),
        Column("BIRTH_DATE", "child's birth date", label_mn="Хүүхдийн төрсөн огноо"),
        Column("STATUS", "status", label_mn="Төлөв"),
    ),
)


def test_labels_come_only_from_views_the_sql_names() -> None:
    labels = view_labels((PEOPLE, CHILDREN), "select id, birth_date from gov_employees")

    assert labels == {"ID": "Ажилтны дугаар", "NAME": "Нэр", "BIRTH_DATE": "Төрсөн огноо", "STATE": "Төлөв"}


def test_a_view_name_inside_a_longer_word_does_not_count() -> None:
    assert view_labels((PEOPLE,), "SELECT ID FROM GOV_EMPLOYEES_OLD") == {}


def test_views_that_disagree_give_no_label_and_views_that_agree_do() -> None:
    labels = view_labels((PEOPLE, CHILDREN), "SELECT * FROM GOV_EMPLOYEES e JOIN GOV_CHILDREN c ON c.ID = e.ID")

    assert "BIRTH_DATE" not in labels  # «Төрсөн огноо» or «Хүүхдийн төрсөн огноо»: not known, so the name stays
    assert labels["ID"] == "Ажилтны дугаар"  # both views say the same


def test_display_names_keep_the_name_without_a_label_and_for_an_alias() -> None:
    names = display_names(("ID", "Note", "CNT"), {"ID": "Ажилтны дугаар"})

    assert names == {"ID": "Ажилтны дугаар", "NOTE": "Note", "CNT": "CNT"}


def test_two_columns_with_one_label_both_show_their_names() -> None:
    names = display_names(("STATE", "STATUS", "NAME"), {"STATE": "Төлөв", "STATUS": "Төлөв", "NAME": "Нэр"})

    assert names == {"STATE": "STATE", "STATUS": "STATUS", "NAME": "Нэр"}


def _pane(client: Client, tab, query: str = "") -> str:
    url = reverse("assistant:ws_table", args=[tab.pk])
    return client.get(f"{url}?{query}" if query else url, HTTP_HX_REQUEST="true").content.decode()


def test_table_shows_labels_and_keeps_names_in_values_and_addresses(
    db: None, client: Client, role_user, gate: dict[str, object], host: FakeHost
) -> None:
    gate["views"] = (PEOPLE,)
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    html = _pane(client, tab, "f=NAME|contains|a&page=0")

    assert ">Ажилтны дугаар</a>" in html and ">Нэр</a>" in html  # the sort links show the labels
    assert 'title="NAME"' in html  # the column name stays as the header's tooltip
    assert "sort=ID%3Aasc" in html  # addresses keep the column name
    assert '<option value="NAME">Нэр</option>' in html  # form values keep the column name
    assert "Нэр агуулсан «a»" in html  # the chip names the column by its label
    assert "NAME агуулсан" not in html


def test_table_without_labels_shows_the_names_as_before(
    db: None, client: Client, role_user, gate: dict[str, object], host: FakeHost
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    html = _pane(client, tab)

    assert ">ID</a>" in html and ">NAME</a>" in html
    assert 'title="NAME"' not in html  # no tooltip when the header is the name itself


def test_grouped_table_calls_the_count_column_by_a_word(
    db: None, client: Client, role_user, gate: dict[str, object], host: FakeHost
) -> None:
    gate["views"] = (PEOPLE,)
    user = role_user("staff")
    tab = _tab(user)
    host.columns = ("NAME", "N")
    host.rows = [("Aigerim", 2)]
    client.force_login(user)

    html = _pane(client, tab, "group=NAME&page=0")

    assert f">{COUNT_LABEL}<" in html.replace("\n", "").replace("  ", "")
    assert "Нэр" in html


def test_copy_text_has_the_labels_in_its_header_line(
    db: None, client: Client, role_user, gate: dict[str, object], host: FakeHost
) -> None:
    gate["views"] = (PEOPLE,)
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)

    text = client.get(reverse("assistant:ws_copy", args=[tab.pk]) + "?page=0").content.decode()

    assert text.split("\n")[0] == "Ажилтны дугаар\tНэр"


def test_a_label_failure_shows_the_names(
    db: None, client: Client, role_user, gate: dict[str, object], host: FakeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = role_user("staff")
    tab = _tab(user)
    client.force_login(user)
    _pane(client, tab)  # the gate answer is cached now, so the broken seam below is reached only by the labels

    def broken(user: object) -> tuple:
        raise RuntimeError("catalogue failed")

    monkeypatch.setattr("assistant.ws_views._catalogue_views", broken)
    html = _pane(client, tab)

    assert ">ID</a>" in html and ">NAME</a>" in html


def test_every_governed_column_has_a_short_label() -> None:
    """The real description files: a column without label_mn would show its database name on the page."""
    from hr_sql.descriptions import load_all

    missing = [
        f"{view.name}.{column.name}"
        for view in load_all().values()
        for column in view.columns
        if not column.label_mn or len(column.label_mn) > 30
    ]

    assert missing == []
