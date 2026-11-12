"""The saved report views are entries built per user, as users add, rename and delete them."""

from collections.abc import Callable

import pytest
from accounts.models import User
from reports.models import SavedView

from assistant.entries import ENTRY_BY_KEY, allowed_entries
from assistant.tests.conftest import TODAY

pytestmark = pytest.mark.django_db


def _view_keys(user: User) -> list[str]:
    return [e.key for e in allowed_entries(user, TODAY) if e.key.startswith("report.view.")]


def _make(author: User | None, name: str, visibility: str = "shared", query: str = "") -> SavedView:
    return SavedView.objects.create(report="staff-list", name=name, query=query, author=author, visibility=visibility)


def test_a_shared_view_becomes_an_entry_for_a_user_who_may_open_the_report(role_user: Callable[[str], User]) -> None:
    hr = role_user("hr")
    view = _make(role_user("accountant"), "Санхүүгийн ажилтнууд", query="department=3")
    entries = {e.key: e for e in allowed_entries(hr, TODAY)}
    entry = entries[f"report.view.{view.pk}"]
    assert "Санхүүгийн ажилтнууд" in entry.title
    assert entry.url().endswith("/staff-list/?department=3")
    # «<name> тайлан» must find the view and not the general report list
    assert "Санхүүгийн ажилтнууд тайлан" in entry.words
    assert "Санхүүгийн ажилтнууд тайлан" in entry.examples
    assert "тайлан" in entry.title
    assert entry.key not in ENTRY_BY_KEY  # built per request, not a fixed entry


def test_a_view_with_no_query_opens_the_plain_report(role_user: Callable[[str], User]) -> None:
    view = _make(role_user("hr"), "Бүгд")
    entry = next(e for e in allowed_entries(role_user("hr"), TODAY) if e.key == f"report.view.{view.pk}")
    assert entry.url().endswith("/staff-list/?view=plain")


def test_a_private_view_is_offered_to_its_author_only(role_user: Callable[[str], User]) -> None:
    author, other = role_user("hr"), role_user("hr")
    view = _make(author, "Миний жагсаалт", visibility="private")
    key = f"report.view.{view.pk}"
    assert key in _view_keys(author)
    assert key not in _view_keys(other)
    mine = next(e for e in allowed_entries(author, TODAY) if e.key == key)
    assert mine.note


def test_a_user_without_the_report_right_gets_no_view_entries(role_user: Callable[[str], User]) -> None:
    _make(role_user("hr"), "Хамтын харагдац")
    assert _view_keys(role_user("staff")) == []
    assert _view_keys(role_user("none")) == []


def test_a_view_of_a_report_the_user_may_not_open_is_left_out(role_user: Callable[[str], User]) -> None:
    """The accountant may open the staff list (checked first), so a view of a report only HR may open is the case."""
    from reports import registry

    accountant, hr = role_user("accountant"), role_user("hr")
    closed = next(
        r for r in registry.REPORTS.values() if registry.can_open(hr, r) and not registry.can_open(accountant, r)
    )
    view = SavedView.objects.create(report=closed.key, name="Закрытый", author=hr, visibility="shared")
    assert f"report.view.{view.pk}" in _view_keys(hr)
    assert f"report.view.{view.pk}" not in _view_keys(accountant)


def test_a_view_of_an_unknown_report_is_left_out(role_user: Callable[[str], User]) -> None:
    hr = role_user("hr")
    SavedView.objects.create(report="no-such-report", name="Хуучин", author=hr, visibility="shared")
    assert _view_keys(hr) == []


def test_entries_follow_the_views_as_users_change_them(role_user: Callable[[str], User]) -> None:
    hr = role_user("hr")
    view = _make(hr, "Эхний нэр")
    key = f"report.view.{view.pk}"
    assert key in _view_keys(hr)
    view.name = "Шинэ нэр"
    view.save()
    entry = next(e for e in allowed_entries(hr, TODAY) if e.key == key)
    assert "Шинэ нэр" in entry.title
    view.delete()
    assert key not in _view_keys(hr)


@pytest.mark.parametrize("question", ["АБ-12", "АБ-12 тайлан", "аб-12 ТАЙЛАНГ", "АБ-12 загвар"])
def test_the_view_the_question_names_is_kept_and_first(role_user: Callable[[str], User], question: str) -> None:
    """Typing the view's name, with or without «тайлан», must put that view first among the entries the model sees,
    ahead of the general report list that shares the word «тайлан» with the question."""
    from assistant.matching import named_first, narrow_entries
    from assistant.services import PLAN_ENTRIES

    hr = role_user("hr")
    view = _make(hr, "АБ-12", query="department=3")
    allowed = allowed_entries(hr, TODAY)
    narrowed = named_first(question, allowed, narrow_entries(question, allowed, limit=PLAN_ENTRIES))
    keys = [e.key for e in narrowed]
    assert keys[0] == f"report.view.{view.pk}", keys[:5]
    assert len(keys) == len(set(keys))


def test_a_view_the_question_does_not_name_is_not_forced(role_user: Callable[[str], User]) -> None:
    from assistant.matching import named_first, narrow_entries
    from assistant.services import PLAN_ENTRIES

    hr = role_user("hr")
    view = _make(hr, "АБ-12", query="department=3")
    allowed = allowed_entries(hr, TODAY)
    question = "тайлангууд хаана байдаг вэ"
    narrowed = named_first(question, allowed, narrow_entries(question, allowed, limit=PLAN_ENTRIES))
    assert narrowed[0].key != f"report.view.{view.pk}"
