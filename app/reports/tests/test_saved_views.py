import re
import string
from collections.abc import Callable
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError
from django.test import Client
from django.utils import timezone

from reports.models import SavedView
from reports.registry import REPORTS
from reports.types import Column, Report

pytestmark = pytest.mark.django_db

NEW = "/reports/staff-list/views/new/"
SELECTED_HOLBOO = re.compile(r'<option value="[^"]*" selected>Холбоо</option>')
LETTERS = string.ascii_lowercase


def _key(i: int, pad: str) -> str:
    """A 40-character column key made of letters only (the address allows [a-z_], up to 40)."""
    return f"{LETTERS[i // 26]}{LETTERS[i % 26]}".ljust(40, pad)


@pytest.fixture
def wide_report(monkeypatch: pytest.MonkeyPatch) -> Report:
    """A report with 60 columns of 40-character keys: a full address is longer than the stored query allows."""
    columns = tuple(Column(key=_key(i, "x"), label=f"Багана {i}", value=lambda r: r) for i in range(60))
    report = Report(
        key="wide",
        title="Өргөн тайлан",
        filters=(),
        columns=columns,
        default_columns=(columns[0].key,),
        rows=lambda user, filters: [],
        saved_views=True,
    )
    monkeypatch.setitem(REPORTS, "wide", report)
    return report


def _save(client: Client, name: str, query: str = "cols=code&cols=email") -> Any:
    return client.post(NEW, {"name": name, "query": query}, HTTP_HX_REQUEST="true")


def test_save_view_stores_cleaned_query(client: Client, login_hr: User) -> None:
    resp = client.post(
        NEW,
        {"name": "Холбоо", "query": "cols=code&cols=email&bogus=1&sort=--x"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 204
    assert resp["HX-Redirect"] == "/reports/staff-list/?cols=code&cols=email"
    view = SavedView.objects.get(name="Холбоо")
    assert view.query == "cols=code&cols=email" and view.author == login_hr


def test_duplicate_name_is_refused(client: Client, login_hr: User) -> None:
    _save(client, "Холбоо")
    resp = _save(client, "Холбоо")
    assert resp.status_code == 200 and "Ийм нэртэй харагдац байна." in resp.content.decode()
    assert SavedView.objects.filter(name="Холбоо").count() == 1


def test_views_are_shared_but_only_author_or_manager_edits(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "hr-author")
    _save(client, "Холбоо")
    view = SavedView.objects.get(name="Холбоо")

    login_as(client, "HR", "hr-other")
    assert "Холбоо" in client.get("/reports/staff-list/").content.decode()
    assert client.get(f"/reports/views/{view.pk}/").status_code == 403
    assert client.post(f"/reports/views/{view.pk}/", {"name": "Жишээ"}, HTTP_HX_REQUEST="true").status_code == 403
    assert client.post(f"/reports/views/{view.pk}/delete/", HTTP_HX_REQUEST="true").status_code == 403
    assert SavedView.objects.filter(pk=view.pk, name="Холбоо").exists()

    login_as(client, "Admin", "admin-manager")
    resp = client.post(f"/reports/views/{view.pk}/delete/", HTTP_HX_REQUEST="true")
    assert resp.status_code == 204 and resp["HX-Redirect"] == "/reports/staff-list/"
    assert not SavedView.objects.filter(pk=view.pk).exists()


def test_report_page_selects_the_view_matching_the_address(client: Client, login_hr: User) -> None:
    _save(client, "Холбоо")
    page = client.get("/reports/staff-list/?cols=code&cols=email").content.decode()
    assert SELECTED_HOLBOO.search(page)
    assert 'value="/reports/staff-list/?cols=code&amp;cols=email"' in page
    assert "Засах" in page  # the author may edit it


def test_edit_button_hidden_from_other_users(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "hr-author")
    _save(client, "Холбоо")
    login_as(client, "HR", "hr-other")
    page = client.get("/reports/staff-list/?cols=code&cols=email").content.decode()
    assert "Холбоо" in page and "Засах" not in page


def test_new_modal_carries_the_current_query(client: Client, login_hr: User) -> None:
    resp = client.get(NEW + "?cols=code&cols=email")
    assert resp.status_code == 200 and 'value="cols=code&amp;cols=email"' in resp.content.decode()


def test_author_renames_view(client: Client, login_hr: User) -> None:
    _save(client, "Холбоо")
    view = SavedView.objects.get(name="Холбоо")
    resp = client.post(f"/reports/views/{view.pk}/", {"name": "Жишээ"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 204 and resp["HX-Refresh"] == "true"
    view.refresh_from_db()
    assert view.name == "Жишээ"


def test_rename_refuses_blank_name(client: Client, login_hr: User) -> None:
    _save(client, "Холбоо")
    view = SavedView.objects.get(name="Холбоо")
    resp = client.post(f"/reports/views/{view.pk}/", {"name": "   "}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    view.refresh_from_db()
    assert view.name == "Холбоо"


def test_saved_views_need_the_report_to_open(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee", "emp")
    assert client.get(NEW).status_code == 403


def test_unknown_view_is_404(client: Client, login_hr: User) -> None:
    assert client.get("/reports/views/999999/").status_code == 404


def test_report_without_saved_views_has_no_saved_view_routes(
    client: Client, login_hr: User, fake_report: object
) -> None:
    assert client.get("/reports/fake/views/new/").status_code == 404


def test_overflowing_address_is_refused_not_a_500(client: Client, login_hr: User, wide_report: Report) -> None:
    query = "&".join(f"cols={c.key}" for c in wide_report.columns)  # 60 known keys, about 2.7k characters
    resp = client.post("/reports/wide/views/new/", {"name": "Дэлгэрэнгүй", "query": query}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200 and "Харагдац хэт урт байна." in resp.content.decode()
    assert not SavedView.objects.filter(report="wide").exists()


def test_unknown_keys_are_dropped_from_the_stored_query(client: Client, login_hr: User) -> None:
    unknown = [_key(i, "z") for i in range(60)]  # 60 unknown 40-character keys
    query = "cols=code&" + "&".join(f"cols={k}" for k in unknown) + "&group=nope&sort=-nope"
    resp = client.post(NEW, {"name": "Нууц", "query": query}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert SavedView.objects.get(name="Нууц").query == "cols=code"


def test_other_integrity_errors_are_not_hidden(client: Client, login_hr: User, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(**kwargs: Any) -> None:
        raise IntegrityError("some other constraint")

    monkeypatch.setattr(SavedView.objects, "create", refuse)
    with pytest.raises(IntegrityError):
        _save(client, "Холбоо")


def test_edit_and_delete_need_the_report_to_open(client: Client, login_hr: User) -> None:
    _save(client, "Холбоо")
    view = SavedView.objects.get(name="Холбоо")
    hr = Group.objects.get(name="HR")
    hr.permissions.remove(Permission.objects.get(codename="view_reports", content_type__app_label="reports"))
    assert client.get(f"/reports/views/{view.pk}/").status_code == 403
    assert client.post(f"/reports/views/{view.pk}/", {"name": "Жишээ"}, HTTP_HX_REQUEST="true").status_code == 403
    assert client.post(f"/reports/views/{view.pk}/delete/", HTTP_HX_REQUEST="true").status_code == 403
    assert SavedView.objects.filter(pk=view.pk, name="Холбоо").exists()


def test_saving_today_as_of_stores_none(client: Client, login_hr: User) -> None:
    today = timezone.localdate().isoformat()
    resp = _save(client, "Өнөөдөр", f"as_of={today}&cols=code")
    assert resp.status_code == 204
    assert SavedView.objects.get(name="Өнөөдөр").query == "cols=code"


def test_saving_a_past_as_of_stores_it(client: Client, login_hr: User) -> None:
    resp = _save(client, "Өмнөх", "as_of=2026-03-01&cols=code")
    assert resp.status_code == 204
    assert SavedView.objects.get(name="Өмнөх").query == "as_of=2026-03-01&cols=code"
