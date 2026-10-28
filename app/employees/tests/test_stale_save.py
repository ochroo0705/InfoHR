"""Employee page save while the old MACS program changes the same row (employees.stale)."""

import html
import re

import pytest
from django.test import Client
from macs.models import Employee

from .test_views import login_as, save_payload

pytestmark = pytest.mark.django_db


def _loaded(page: str, name: str = "loaded") -> str:
    found = re.search(rf'name="{name}" value="([^"]*)"', page)
    assert found is not None
    return html.unescape(found.group(1))


def _open(client: Client, employee: Employee) -> dict[str, str]:
    """What the open page will post back if the user changes nothing."""
    page = client.get(f"/employees/{employee.pk}/").content.decode()
    return save_payload(employee) | {"loaded": _loaded(page)}


def _old_program_sets(employee: Employee, **values: str) -> None:
    Employee.objects.filter(pk=employee.pk).update(**values)


def test_change_by_old_program_survives_unrelated_save(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = _open(client, hired)
    _old_program_sets(hired, private_phone="99001122")
    response = client.post(f"/employees/{hired.pk}/save/", data | {"email": "new@example.mn"})
    assert response.status_code == 303
    hired.refresh_from_db()
    assert hired.private_phone == "99001122" and hired.email == "new@example.mn"


def test_hr_change_is_written_when_nobody_else_changed_it(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = _open(client, hired)
    assert client.post(f"/employees/{hired.pk}/save/", data | {"private_phone": "88112233"}).status_code == 303
    hired.refresh_from_db()
    assert hired.private_phone == "88112233"


def test_both_changed_same_field_asks_and_saves_nothing(client: Client, hired: Employee) -> None:
    """The phone is in the contact section now: both changed it, so the section asks and saves nothing."""
    login_as(client, "HR")
    loaded = _loaded(client.get(f"/employees/{hired.pk}/section/contact/").content.decode())
    _old_program_sets(hired, private_phone="99001122")
    response = client.post(f"/employees/{hired.pk}/section/contact/", {"private_phone": "88112233", "loaded": loaded})
    body = response.content.decode()
    assert response.status_code == 200
    assert "«99001122» болгож өөрчилсөн" in body and 'value="theirs"' in body
    hired.refresh_from_db()
    assert hired.private_phone == "99001122"


def test_after_clash_keep_mine_writes_mine(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = _open(client, hired)
    _old_program_sets(hired, private_phone="99001122")
    body = client.post(f"/employees/{hired.pk}/save/", data | {"private_phone": "88112233"}).content.decode()
    again = data | {"loaded": _loaded(body), "private_phone": "88112233", "resolve-private_phone": "mine"}
    assert client.post(f"/employees/{hired.pk}/save/", again).status_code == 303
    hired.refresh_from_db()
    assert hired.private_phone == "88112233"


def test_after_clash_keep_theirs_keeps_old_program_value(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    data = _open(client, hired)
    _old_program_sets(hired, private_phone="99001122")
    body = client.post(f"/employees/{hired.pk}/save/", data | {"private_phone": "88112233"}).content.decode()
    again = data | {"loaded": _loaded(body), "private_phone": "88112233", "resolve-private_phone": "theirs"}
    assert client.post(f"/employees/{hired.pk}/save/", again).status_code == 303
    hired.refresh_from_db()
    assert hired.private_phone == "99001122"


def test_salary_fields_keep_old_program_change(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    page = client.get(f"/employees/{hired.pk}/").content.decode()
    data = {"si-loaded": _loaded(page, "si-loaded"), "si-account_no": hired.account_no or "", "si-taxpayer_no": "T1"}
    _old_program_sets(hired, account_no="5000123456")
    assert client.post(f"/employees/{hired.pk}/save/", data).status_code == 303
    hired.refresh_from_db()
    assert hired.account_no == "5000123456" and hired.taxpayer_no == "T1"
