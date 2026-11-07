"""Saved view rules: who sees a view, the one default view per report, and the bare address that opens it."""

import re
from collections.abc import Callable
from typing import Any

import pytest
from accounts.models import User
from django.http import HttpResponseBase
from django.test import Client

from reports.forms import SavedViewForm
from reports.models import SavedView

pytestmark = pytest.mark.django_db

PAGE = "/reports/staff-list/"
NEW = "/reports/staff-list/views/new/"
COLS = "cols=code&cols=email"


def _create(client: Client, name: str, query: str = COLS, **fields: str) -> HttpResponseBase:
    return client.post(NEW, {"name": name, "query": query, **fields}, HTTP_HX_REQUEST="true")


def _defaults() -> list[str]:
    return list(SavedView.objects.filter(report="staff-list", is_default=True).values_list("name", flat=True))


def test_private_view_is_invisible_to_another_user(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "rule-author")
    _create(client, "Тусгай", visibility="private")
    other = Client()
    login_as(other, "HR", "rule-other")
    assert "Тусгай" not in other.get(PAGE).content.decode()


def test_private_view_is_404_for_another_user_even_with_manage_rights(
    client: Client, login_as: Callable[..., User]
) -> None:
    login_as(client, "HR", "rule-author2")
    _create(client, "Тусгай2", visibility="private")
    view = SavedView.objects.get(name="Тусгай2")
    manager = Client()
    login_as(manager, "Admin", "rule-admin")  # Admin holds reports.manage_saved_views
    assert manager.get(f"/reports/views/{view.pk}/").status_code == 404
    assert manager.post(f"/reports/views/{view.pk}/", {"name": "Жишээ"}, HTTP_HX_REQUEST="true").status_code == 404
    assert manager.post(f"/reports/views/{view.pk}/delete/", HTTP_HX_REQUEST="true").status_code == 404
    assert SavedView.objects.filter(pk=view.pk, name="Тусгай2").exists()


def test_author_sees_own_private_view_with_suffix(client: Client, login_hr: User) -> None:
    _create(client, "Миний", visibility="private")
    assert "Миний (хувийн)</option>" in client.get(PAGE).content.decode()


def test_shared_view_is_visible_to_both_users(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "share-author")
    _create(client, "Нийтлэг")
    other = Client()
    login_as(other, "HR", "share-other")
    page = other.get(PAGE).content.decode()
    assert "Нийтлэг</option>" in page and "Нийтлэг (хувийн)" not in page


def test_setting_a_second_default_leaves_exactly_one(client: Client, login_hr: User) -> None:
    _create(client, "Эхний", is_default="on")
    _create(client, "Хоёр", is_default="on")
    assert _defaults() == ["Хоёр"]


def test_editing_a_view_to_default_unsets_the_old_default(client: Client, login_hr: User) -> None:
    _create(client, "Эхний", is_default="on")
    _create(client, "Хоёр")
    view = SavedView.objects.get(name="Хоёр")
    resp = client.post(
        f"/reports/views/{view.pk}/",
        {"name": "Хоёр", "visibility": "shared", "is_default": "on"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 204
    assert _defaults() == ["Хоёр"]


def test_private_view_cannot_be_default(client: Client, login_hr: User) -> None:
    _create(client, "Хувийн", visibility="private", is_default="on")
    view = SavedView.objects.get(name="Хувийн")
    assert view.visibility == "private" and view.is_default is False
    assert _defaults() == []


def test_switching_a_default_to_private_clears_the_default(client: Client, login_hr: User) -> None:
    _create(client, "Үндсэн", is_default="on")
    view = SavedView.objects.get(name="Үндсэн")
    resp = client.post(
        f"/reports/views/{view.pk}/", {"name": "Үндсэн", "visibility": "private"}, HTTP_HX_REQUEST="true"
    )
    assert resp.status_code == 204
    view.refresh_from_db()
    assert view.visibility == "private" and view.is_default is False


def test_bare_address_redirects_to_the_default_view(client: Client, login_hr: User) -> None:
    _create(client, "Үндсэн", is_default="on")
    resp = client.get(PAGE)
    assert resp.status_code == 302
    assert resp["Location"] == f"{PAGE}?{COLS}"


def test_redirect_target_opens_without_looping(client: Client, login_hr: User) -> None:
    _create(client, "Үндсэн", is_default="on")
    followed = client.get(PAGE, follow=True)
    assert followed.redirect_chain == [(f"{PAGE}?{COLS}", 302)]
    assert followed.status_code == 200


def test_any_query_parameter_stops_the_redirect(client: Client, login_hr: User) -> None:
    _create(client, "Үндсэн", is_default="on")
    assert client.get(PAGE + "?x=1").status_code == 200


def test_htmx_request_does_not_redirect(client: Client, login_hr: User) -> None:
    _create(client, "Үндсэн", is_default="on")
    assert client.get(PAGE, HTTP_HX_REQUEST="true").status_code == 200


def test_default_redirect_drops_a_column_the_viewer_may_not_see(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "rule-acc")  # may use the salary threshold, HR may not
    _create(client, "Цалин", query="cols=code&salary_from=7654321", is_default="on")
    hr = Client()
    login_as(hr, "HR", "rule-hr")
    resp = hr.get(PAGE)
    assert resp.status_code == 302
    location = resp["Location"]
    assert location.startswith(f"{PAGE}?") and "cols=code" in location
    assert "salary" not in location and "7654321" not in location


def test_edit_modal_shows_the_current_visibility(client: Client, login_hr: User) -> None:
    _create(client, "Тусгай", visibility="private")
    view = SavedView.objects.get(name="Тусгай")
    html = client.get(f"/reports/views/{view.pk}/").content.decode()
    radio = re.search(r'<input[^>]*value="private"[^>]*>', html)
    assert radio is not None and " checked" in radio.group(0)
    assert 'data-default-row class="text-sm hidden"' in html  # the default box is hidden for a private view


def test_form_rejects_an_unknown_visibility() -> None:
    form = SavedViewForm({"name": "Жишээ", "visibility": "secret", "query": ""})
    assert not form.is_valid() and "visibility" in form.errors


def test_save_refuses_an_unknown_visibility(client: Client, login_hr: User) -> None:
    resp = _create(client, "Буруу", visibility="secret")
    assert resp.status_code == 200
    assert not SavedView.objects.filter(name="Буруу").exists()


def _option(page: Any, name: str) -> Any:
    return next(o for o in page.context["saved_options"] if o.name == name)


def test_empty_view_is_openable_and_its_address_skips_the_default(client: Client, login_hr: User) -> None:
    _create(client, "Үндсэн", is_default="on")
    _create(client, "Хоосон", query="")
    url = _option(client.get(PAGE + "?x=1"), "Хоосон").url
    assert url == f"{PAGE}?view=plain"
    opened = client.get(url)
    assert opened.status_code == 200
    assert opened.context["current_view"].name == "Хоосон"


def test_plain_option_opens_the_plain_report_when_a_default_exists(client: Client, login_hr: User) -> None:
    _create(client, "Үндсэн", is_default="on")
    plain_url = client.get(PAGE + "?x=1").context["plain_url"]
    assert plain_url == f"{PAGE}?view=plain"
    opened = client.get(plain_url)
    assert opened.status_code == 200
    assert opened.context["current_view"] is None


def test_plain_address_is_not_redirected_to_the_default(client: Client, login_hr: User) -> None:
    _create(client, "Үндсэн", is_default="on")
    assert client.get(f"{PAGE}?view=plain").status_code == 200


def test_non_manager_cannot_displace_another_users_default(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "def-owner")
    _create(client, "Эзэмшигчийн", is_default="on")
    other = Client()
    login_as(other, "HR", "def-other")
    resp = _create(other, "Өөрийн", is_default="on")
    assert resp.status_code == 204  # saved, but not as the default
    assert SavedView.objects.get(name="Өөрийн").is_default is False
    assert _defaults() == ["Эзэмшигчийн"]


def test_non_manager_edit_cannot_displace_another_users_default(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "edit-owner")
    _create(client, "Эзэмшигч2", is_default="on")
    other = Client()
    login_as(other, "HR", "edit-other")
    _create(other, "Хоёрдугаар")
    view = SavedView.objects.get(name="Хоёрдугаар")
    resp = other.post(
        f"/reports/views/{view.pk}/",
        {"name": "Хоёрдугаар", "visibility": "shared", "is_default": "on"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 204
    assert _defaults() == ["Эзэмшигч2"]


def test_manager_can_replace_a_default(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "mgr-owner")
    _create(client, "Анхны", is_default="on")
    manager = Client()
    login_as(manager, "Admin", "mgr-admin")
    _create(manager, "Шинэ", is_default="on")
    assert _defaults() == ["Шинэ"]


def test_author_can_replace_their_own_default(client: Client, login_hr: User) -> None:
    _create(client, "Нэг", is_default="on")
    _create(client, "Хоёр", is_default="on")
    assert _defaults() == ["Хоёр"]


def test_private_view_with_no_author_is_seen_and_changed_only_by_a_manager(
    client: Client, login_as: Callable[..., User]
) -> None:
    login_as(client, "HR", "orphan-author")
    _create(client, "Жорлон", visibility="private")
    SavedView.objects.filter(name="Жорлон").update(author=None)
    view = SavedView.objects.get(name="Жорлон")
    plain = Client()
    login_as(plain, "HR", "orphan-plain")
    assert plain.get(f"/reports/views/{view.pk}/").status_code == 404
    assert plain.post(f"/reports/views/{view.pk}/", {"name": "Жишээ"}, HTTP_HX_REQUEST="true").status_code == 404
    assert plain.post(f"/reports/views/{view.pk}/delete/", HTTP_HX_REQUEST="true").status_code == 404
    assert "Жорлон" not in plain.get(PAGE).content.decode()
    manager = Client()
    login_as(manager, "Admin", "orphan-admin")
    assert "Жорлон (хувийн)</option>" in manager.get(PAGE).content.decode()
    assert manager.get(f"/reports/views/{view.pk}/").status_code == 200
    assert manager.post(f"/reports/views/{view.pk}/delete/", HTTP_HX_REQUEST="true").status_code == 204
    assert not SavedView.objects.filter(pk=view.pk).exists()


def test_non_manager_gets_404_on_another_users_private_view(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "priv-author")
    _create(client, "Нууц", visibility="private")
    view = SavedView.objects.get(name="Нууц")
    other = Client()
    login_as(other, "HR", "priv-other")
    assert other.get(f"/reports/views/{view.pk}/").status_code == 404
    assert other.post(f"/reports/views/{view.pk}/", {"name": "Жишээ"}, HTTP_HX_REQUEST="true").status_code == 404
    assert other.post(f"/reports/views/{view.pk}/delete/", HTTP_HX_REQUEST="true").status_code == 404
    assert SavedView.objects.filter(pk=view.pk, name="Нууц").exists()


def test_other_users_page_shows_no_trace_of_a_private_view(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "trace-author")
    _create(client, "Тусгай", visibility="private")
    other = Client()
    login_as(other, "HR", "trace-other")
    page = other.get(PAGE).content.decode()
    assert "Тусгай" not in page
    assert "cols=code&amp;cols=email" not in page and "cols=code&cols=email" not in page


def test_user_without_report_access_gets_403_on_view_edit(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "access-author")
    _create(client, "Нийтлэг2")
    view = SavedView.objects.get(name="Нийтлэг2")
    outsider = Client()
    login_as(outsider, "Employee", "access-employee")
    assert outsider.get(f"/reports/views/{view.pk}/").status_code == 403
