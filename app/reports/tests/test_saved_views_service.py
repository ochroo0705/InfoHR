"""The request-free saved-view service (services/saved_views.py): what a save may store, which default it may displace,
the name clash, and who may rename or delete a view. The Django views and the React API both call these."""

from collections.abc import Callable

import pytest
from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.http import Http404, QueryDict
from django.test import Client

from reports import registry
from reports.models import SavedView
from reports.services import saved_views
from reports.services.saved_views import (
    DUPLICATE_NAME,
    TOO_LONG,
    create_view,
    delete_view,
    initial_query,
    update_view,
    view_for,
)
from reports.types import Report

pytestmark = pytest.mark.django_db

REPORT_KEY = "staff-list"
COLS = "cols=code&cols=email"


def _report() -> Report:
    report = registry.get(REPORT_KEY)
    assert report is not None
    return report


def _view(author: User | None, name: str, **fields: object) -> SavedView:
    return SavedView.objects.create(report=REPORT_KEY, name=name, query=COLS, author=author, **fields)


def _defaults() -> list[str]:
    return list(SavedView.objects.filter(report=REPORT_KEY, is_default=True).values_list("name", flat=True))


def test_create_cleans_query_and_drops_hidden_column(hr_user: User) -> None:
    # HR may not see salary: the salary threshold of the address is not stored
    result = create_view(hr_user, _report(), {"name": "Холбоо", "query": "cols=code&salary_from=7654321&bogus=1"})
    assert result.view is not None
    assert result.field_errors == {} and result.form_errors == []
    assert "cols=code" in result.view.query
    assert "salary" not in result.view.query and "7654321" not in result.view.query
    assert "bogus" not in result.view.query


def test_create_private_view_is_never_default(hr_user: User) -> None:
    result = create_view(
        hr_user, _report(), {"name": "Хувийн", "query": COLS, "visibility": "private", "is_default": "on"}
    )
    assert result.view is not None
    assert result.view.visibility == "private" and result.view.is_default is False
    assert _defaults() == []


def test_create_default_displaces_own_default(hr_user: User) -> None:
    create_view(hr_user, _report(), {"name": "Эхний", "query": COLS, "is_default": "on"})
    create_view(hr_user, _report(), {"name": "Хоёр", "query": COLS, "is_default": "on"})
    assert _defaults() == ["Хоёр"]


def test_plain_author_cannot_displace_someone_elses_default(hr_user: User, login_as: Callable[..., User]) -> None:
    other = login_as(Client(), "HR", "svc-default-owner")
    _view(other, "Бусад", is_default=True)
    result = create_view(hr_user, _report(), {"name": "Миний", "query": COLS, "is_default": "on"})
    assert result.view is not None and result.view.is_default is False
    assert _defaults() == ["Бусад"]


def test_refused_save_keeps_old_default(hr_user: User) -> None:
    _view(hr_user, "Эхний", is_default=True)
    _view(hr_user, "Тэмдэг")
    # the save clears the old default first, then the name clash rolls that back
    result = create_view(hr_user, _report(), {"name": "Тэмдэг", "query": COLS, "is_default": "on"})
    assert result.view is None
    assert result.field_errors == {"name": [DUPLICATE_NAME]}
    assert _defaults() == ["Эхний"]


def test_name_clash_returns_field_error_and_changes_nothing(hr_user: User) -> None:
    create_view(hr_user, _report(), {"name": "Нэг", "query": "cols=code"})
    result = create_view(hr_user, _report(), {"name": "Нэг", "query": "cols=email"})
    assert result.view is None
    assert result.field_errors == {"name": [DUPLICATE_NAME]} and result.form_errors == []
    stored = SavedView.objects.get(report=REPORT_KEY, name="Нэг")
    assert stored.query == "cols=code"


def test_name_too_long_is_a_field_error(hr_user: User) -> None:
    result = create_view(hr_user, _report(), {"name": "а" * 61, "query": COLS})
    assert result.view is None
    assert "name" in result.field_errors
    assert not SavedView.objects.filter(report=REPORT_KEY).exists()


def test_query_over_limit_is_a_form_error(hr_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(saved_views, "QUERY_LIMIT", 10)  # COLS is longer than this
    result = create_view(hr_user, _report(), {"name": "Урт", "query": COLS})
    assert result.view is None
    assert result.form_errors == [TOO_LONG] and result.field_errors == {}
    assert not SavedView.objects.filter(report=REPORT_KEY).exists()


def test_update_keeps_visibility_when_none_posted(hr_user: User) -> None:
    view = _view(hr_user, "Тусгай", visibility="private")
    result = update_view(hr_user, view, {"name": "Шинэ нэр"})
    assert result.view is not None
    view.refresh_from_db()
    assert view.name == "Шинэ нэр" and view.visibility == "private"


def test_update_by_non_author_is_403_and_manager_may(hr_user: User, login_as: Callable[..., User]) -> None:
    view = _view(hr_user, "Хамтын")  # shared: another HR user sees it, but may not change it
    other = login_as(Client(), "HR", "svc-other-hr")
    with pytest.raises(PermissionDenied):
        view_for(other, view.pk)
    admin = login_as(Client(), "Admin", "svc-admin")
    assert view_for(admin, view.pk).pk == view.pk


def test_private_view_of_another_user_is_404_from_view_for(hr_user: User, login_as: Callable[..., User]) -> None:
    # view_for is the one gate in front of update_view and delete_view: it answers 404 before either can run
    view = _view(hr_user, "Тусгай хувийн", visibility="private")
    other = login_as(Client(), "HR", "svc-private-other")
    with pytest.raises(Http404):
        view_for(other, view.pk)
    admin = login_as(Client(), "Admin", "svc-private-admin")  # a manager sees no one else's private view either
    with pytest.raises(Http404):
        view_for(admin, view.pk)
    assert SavedView.objects.filter(pk=view.pk, name="Тусгай хувийн", visibility="private").exists()


def test_refused_update_leaves_view_object_unchanged(hr_user: User) -> None:
    _view(hr_user, "Эхний")
    view = _view(hr_user, "Хоёр", visibility="private")
    # the name clashes with «Эхний»; the save asks for shared and default, and both are refused with the name
    result = update_view(hr_user, view, {"name": "Эхний", "visibility": "shared", "is_default": "on"})
    assert result.view is None and result.field_errors == {"name": [DUPLICATE_NAME]}
    assert (view.name, view.visibility, view.is_default) == ("Хоёр", "private", False)
    stored = SavedView.objects.get(pk=view.pk)
    assert (stored.name, stored.visibility, stored.is_default) == ("Хоёр", "private", False)


def test_delete_returns_report_key_and_removes_row(hr_user: User) -> None:
    view = _view(hr_user, "Устгах")
    key = delete_view(hr_user, view)
    assert key == REPORT_KEY
    assert not SavedView.objects.filter(pk=view.pk).exists()


def test_initial_query_is_cleaned_address() -> None:
    query = initial_query(QueryDict("cols=code&bogus=1"))
    assert "cols=code" in query
    assert "bogus" not in query
