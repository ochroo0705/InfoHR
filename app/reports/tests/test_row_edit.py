"""Report cell edit of children and contacts rows (reports.row_edit, D-080 follow-up)."""

from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import urlencode

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from employees.models import ActivityEntry, Employee
from employees.tests.conftest import named
from macs.models import ContactRow, ContactType, FamilyRelation, FamilyRow

pytestmark = pytest.mark.django_db

STALE = "Өөр хэрэглэгч өөрчилсөн байна, дахин ачаална уу"


def _url(person: int, kind: str, key: int, field: str) -> str:
    return reverse("reports:row_cell") + "?" + urlencode({"person": person, "kind": kind, "key": key, "field": field})


def _editor_post(client: Client, url: str) -> dict[str, Any]:
    """The POST the editor sends: the values it was opened with (loaded_* included), without the empty ones."""
    response = client.get(url)
    assert response.status_code == 200
    return {k: v for k, v in response.context["form"].initial.items() if v is not None}


def _child(employee: Employee, given: str = "Бат", birth: date | None = date(2015, 1, 2)) -> FamilyRow:
    relation = FamilyRelation.objects.create(name=f"Хүү {given}", fm_type="son")
    return FamilyRow.objects.create(employee=employee, relation=relation, given_name=given, birth_date=birth)


def _contact(employee: Employee, value: str = "99112233") -> ContactRow:
    return ContactRow.objects.create(
        employee=employee, contact_type=named(ContactType, "Утас"), value=value, name="Эх", relative="Ээж"
    )


def test_child_given_name_is_saved_with_history(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    child = _child(hired)
    url = _url(hired.pk, "family", child.pk, "given_name")
    post = _editor_post(client, url)
    post["given_name"] = "Болд"
    entries = ActivityEntry.objects.filter(employee=hired).count()

    response = client.post(url, post)

    assert response.status_code == 200
    assert "<span data-cell-value>Болд</span>" in response.content.decode()
    child.refresh_from_db()
    assert child.given_name == "Болд"
    assert ActivityEntry.objects.filter(employee=hired).count() == entries + 1


def test_invalid_birth_date_shows_error_and_keeps_the_row(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    child = _child(hired)
    url = _url(hired.pk, "family", child.pk, "birth_date")
    post = _editor_post(client, url)
    post["birth_date"] = "2015-13-45"

    response = client.post(url, post)

    assert response.status_code == 200
    assert "data-cell-error" in response.content.decode()
    child.refresh_from_db()
    assert child.birth_date == date(2015, 1, 2)


def test_contact_value_is_saved(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    contact = _contact(hired)
    url = _url(hired.pk, "contact", contact.pk, "value")
    post = _editor_post(client, url)
    post["value"] = "99887766"

    response = client.post(url, post)

    assert response.status_code == 200
    assert "<span data-cell-value>99887766</span>" in response.content.decode()
    contact.refresh_from_db()
    assert contact.value == "99887766"


def test_stale_row_refuses_the_save(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    child = _child(hired)
    url = _url(hired.pk, "family", child.pk, "given_name")
    post = _editor_post(client, url)
    FamilyRow.objects.filter(pk=child.pk).update(given_name="Өөр")  # another user changed it after the editor opened
    post["given_name"] = "Болд"

    response = client.post(url, post)

    assert response.status_code == 200
    assert STALE in response.content.decode()
    child.refresh_from_db()
    assert child.given_name == "Өөр"


def test_viewer_without_rights_gets_403(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "Accountant")  # sees the reports, but may not manage employees
    child = _child(hired)
    url = _url(hired.pk, "family", child.pk, "given_name")
    assert client.get(url).status_code == 403
    assert client.post(url, {"given_name": "Болд"}).status_code == 403


def test_row_of_another_employee_is_404(
    client: Client, login_as: Callable[..., User], hired: Employee, left_employee: Employee
) -> None:
    login_as(client, "HR")
    other_child = _child(left_employee, given="Сарнай")
    assert client.get(_url(hired.pk, "family", other_child.pk, "given_name")).status_code == 404


def test_stale_save_reopens_the_editor_with_the_current_value_and_a_retry_succeeds(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    child = _child(hired)
    url = _url(hired.pk, "family", child.pk, "given_name")
    post = _editor_post(client, url)
    FamilyRow.objects.filter(pk=child.pk).update(given_name="Өөр")  # another user changed it after the editor opened
    post["given_name"] = "Болд"

    stale = client.post(url, post)

    assert STALE in stale.content.decode()
    shown = stale.context["form"]
    assert shown.initial["given_name"] == "Өөр"  # the editor shows what is stored now, not the user's refused text
    retry = {k: v for k, v in shown.initial.items() if v is not None}
    retry["given_name"] = "Болд"

    response = client.post(url, retry)

    assert "<span data-cell-value>Болд</span>" in response.content.decode()
    child.refresh_from_db()
    assert child.given_name == "Болд"


def test_hr_children_report_renders_row_edit_cells(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    child = _child(hired)

    response = client.get(reverse("reports:report", args=["children"]))

    html = response.content.decode()
    assert response.status_code == 200
    assert f"kind=family&amp;key={child.pk}&amp;field=given_name" in html
    assert f"kind=family&amp;key={child.pk}&amp;field=relation" in html
    assert f"kind=family&amp;key={child.pk}&amp;field=birth_date" in html
    assert "data-row-edit" in html


def test_hr_contacts_report_renders_row_edit_cells(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    contact = _contact(hired)

    response = client.get(reverse("reports:report", args=["contacts"]))

    html = response.content.decode()
    assert response.status_code == 200
    assert f"kind=contact&amp;key={contact.pk}&amp;field=value" in html
    assert f"kind=contact&amp;key={contact.pk}&amp;field=contact_type" in html
    assert "data-row-edit" in html


def test_viewer_who_cannot_manage_sees_the_children_rows_without_row_edit_cells(
    client: Client, hired: Employee
) -> None:
    viewer = User.objects.create_user("row-viewer", password="x-long-pass-123")  # noqa: S106
    for codename, app in (("view_reports", "reports"), ("view_employees", "macs"), ("view_personal", "macs")):
        viewer.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label=app))
    client.force_login(viewer)
    _child(hired, given="Бат")

    response = client.get(reverse("reports:report", args=["children"]))

    html = response.content.decode()
    assert response.status_code == 200
    assert "Бат" in html  # the row is there, only its editor is not
    assert "data-row-edit" not in html
    assert "kind=family" not in html
