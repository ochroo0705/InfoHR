"""The catalogue's sections (reports.services.catalogue_page.sections_for): which cards a user sees, greyed or open,
empty or not. The Django catalogue view and GET /api/v1/reports/catalogue both read these sections, so these tests
pin the rules both share."""

import pytest
from accounts.models import User
from django.contrib.auth.models import AnonymousUser, Group

from reports.catalogue import CATALOGUE, Entry
from reports.models import SavedView
from reports.registry import REPORTS
from reports.services import catalogue_page
from reports.services.catalogue_page import Section, sections_for
from reports.types import Report

pytestmark = pytest.mark.django_db


def _user(role: str) -> User:
    user = User.objects.create_user(f"catalogue_{role.lower()}", password="x-long-pass-123")  # noqa: S106
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _card(sections: list[Section], key: str):  # type: ignore[no-untyped-def]
    rows = [row for section in sections for row in section.rows if row.entry.key == key]
    assert len(rows) == 1, key
    return rows[0]


def _report(key: str, **fields: object) -> Report:
    base: dict[str, object] = {
        "key": key,
        "title": "Туршилт",
        "filters": (),
        "columns": (),
        "default_columns": (),
        "rows": lambda user, filters: [],
    }
    return Report(**{**base, **fields})  # type: ignore[arg-type]


def test_sections_hide_a_built_report_the_user_may_not_open(monkeypatch: pytest.MonkeyPatch) -> None:
    # The report needs a right HR does not hold, so it is not listed at all (not greyed).
    monkeypatch.setitem(REPORTS, "staff-list", _report("staff-list", needs=("reports.manage_saved_views",)))
    sections = sections_for(_user("HR"))
    keys = [row.entry.key for section in sections for row in section.rows]
    assert "staff-list" not in keys
    assert "children" in keys  # the other cards of the group still show


def test_sections_list_unbuilt_report_greyed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every catalogue entry is built by now, so an unbuilt one is added for this test only.
    later = Entry("not-built-yet", "other", "Хийгдээгүй тайлан", "", "Удахгүй", ())
    monkeypatch.setattr(catalogue_page, "CATALOGUE", (*CATALOGUE, later))
    assert "not-built-yet" not in REPORTS
    row = _card(sections_for(_user("HR")), "not-built-yet")
    assert row.link is False
    assert row.empty is False


def test_sections_mark_empty_report(monkeypatch: pytest.MonkeyPatch) -> None:
    # The main table (SavedView) has no rows in a fresh test database, so the built report is marked empty.
    monkeypatch.setitem(REPORTS, "annual-leave", _report("annual-leave", source=SavedView))
    row = _card(sections_for(_user("HR")), "annual-leave")
    assert row.link is True
    assert row.empty is True


def test_sections_mark_a_built_report_without_source_as_not_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(REPORTS, "annual-leave", _report("annual-leave", source=None))
    row = _card(sections_for(_user("HR")), "annual-leave")
    assert row.link is True
    assert row.empty is False


def test_sections_need_the_view_right_to_list_anything() -> None:
    # Without reports.view_reports no built report opens, so every built card is hidden.
    sections = sections_for(_user("Employee"))
    assert all(row.entry.key not in REPORTS for section in sections for row in section.rows)


def test_sections_drop_a_group_whose_only_card_is_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalogue_page, "CATALOGUE", (Entry("staff-list", "staff", "Жагсаалт", "", "", ()),))
    monkeypatch.setitem(REPORTS, "staff-list", _report("staff-list", needs=("reports.manage_saved_views",)))
    assert sections_for(_user("HR")) == []


def test_sections_accept_an_anonymous_user_without_rows() -> None:
    assert sections_for(AnonymousUser()) == []
