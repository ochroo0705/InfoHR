"""Saved workspace tables: who may see a saved table and who may delete it (saved tables Task 1)."""

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission

from assistant.models import SavedTable
from assistant.saved_tables import can_delete, visible_to

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture
def people(db: None) -> dict[str, User]:
    return {name: User.objects.create_user(name, password=PASSWORD) for name in ("ann", "ben", "cyn")}


def _table(author: User | None, name: str, visibility: str = "shared") -> SavedTable:
    return SavedTable.objects.create(name=name, sql="SELECT 1 FROM t", author=author, visibility=visibility)


def test_visible_to_is_shared_plus_own_private(people: dict[str, User]) -> None:
    ann, ben = people["ann"], people["ben"]
    _table(ben, "Ben shared")
    _table(ben, "Ben private", visibility="private")
    _table(ann, "Ann private", visibility="private")
    _table(ann, "Ann shared")

    names = list(visible_to(ann).values_list("name", flat=True))

    assert names == ["Ann private", "Ann shared", "Ben shared"]


def test_visible_to_orders_by_name(people: dict[str, User]) -> None:
    _table(people["ben"], "Зүүн")
    _table(people["ben"], "Ага")

    names = list(visible_to(people["ann"]).values_list("name", flat=True))

    assert names == ["Ага", "Зүүн"]


def test_default_visibility_is_shared(people: dict[str, User]) -> None:
    table = SavedTable.objects.create(name="Нэр", sql="SELECT 1 FROM t")
    assert table.visibility == "shared"
    assert table.labels == ""
    assert table.settings == ""


def test_author_can_delete_own_table_only(people: dict[str, User]) -> None:
    ann, ben = people["ann"], people["ben"]
    own = _table(ann, "Ann shared")
    other = _table(ann, "Ann other")

    assert can_delete(ann, own) is True
    assert can_delete(ben, other) is False


def test_permission_holder_can_delete_any_table(people: dict[str, User]) -> None:
    ann, cyn = people["ann"], people["cyn"]
    table = _table(ann, "Ann shared")
    permission = Permission.objects.get(codename="manage_saved_tables", content_type__app_label="assistant")
    cyn.user_permissions.add(permission)
    cyn = User.objects.get(pk=cyn.pk)  # reload so the permission cache is fresh

    assert can_delete(cyn, table) is True


def test_deleted_author_keeps_shared_table_for_others(people: dict[str, User]) -> None:
    ann, ben = people["ann"], people["ben"]
    table = _table(ann, "Ann shared")
    ann.delete()
    table.refresh_from_db()

    assert table.author is None
    assert list(visible_to(ben)) == [table]
    assert can_delete(ben, table) is False
