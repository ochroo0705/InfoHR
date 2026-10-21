"""Per-section save of the employee's personal tab (employees.sections)."""

import html
import re

import pytest
from django.test import Client
from macs.models import BirthPlace, City, Country, Employee

from .test_views import login_as

pytestmark = pytest.mark.django_db


def _loaded(page: str) -> str:
    found = re.search(r'name="loaded" value="([^"]*)"', page)
    assert found is not None
    return html.unescape(found.group(1))


def _open(client: Client, employee: Employee, section: str = "identity") -> str:
    """The hidden `loaded` the section form posts when opened for editing."""
    return _loaded(client.get(f"/employees/{employee.pk}/section/{section}/?edit=1").content.decode())


def _url(employee: Employee, section: str = "identity") -> str:
    return f"/employees/{employee.pk}/section/{section}/"


def test_section_save_writes_only_its_fields(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    loaded = _open(client, hired)
    response = client.post(_url(hired), {"clan_name": "Ботгон", "loaded": loaded})
    assert response.status_code == 200
    body = response.content.decode()
    assert 'class="mt-1 text-xs text-red-600"' not in body  # work_phone was not posted, yet no required error
    hired.refresh_from_db()
    assert hired.clan_name == "Ботгон" and hired.work_phone == "99112233"


def test_section_save_keeps_other_section_change(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    loaded = _open(client, hired)
    Employee.objects.filter(pk=hired.pk).update(private_phone="99001122")  # the contact section changed it
    assert client.post(_url(hired), {"clan_name": "Ботгон", "loaded": loaded}).status_code == 200
    hired.refresh_from_db()
    assert hired.clan_name == "Ботгон" and hired.private_phone == "99001122"


def test_section_save_conflict_shows_choice(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    loaded = _open(client, hired)
    Employee.objects.filter(pk=hired.pk).update(clan_name="Өөр")  # the old program changed it meanwhile
    response = client.post(_url(hired), {"clan_name": "Шинэ", "loaded": loaded})
    assert response.status_code == 200
    assert "хуучин программ" in response.content.decode()
    hired.refresh_from_db()
    assert hired.clan_name == "Өөр"


def test_section_unknown_404(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    assert client.get(_url(hired, "nope")).status_code == 404


def test_section_requires_manage(client: Client, hired: Employee) -> None:
    login_as(client, "Accountant")
    assert client.get(_url(hired)).status_code == 403
    assert client.post(_url(hired), {"clan_name": "Ботгон"}).status_code == 403
    hired.refresh_from_db()
    assert hired.clan_name != "Ботгон"


def test_section_get_read_and_edit(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    read = client.get(_url(hired)).content.decode()
    assert 'name="clan_name"' not in read
    edit = client.get(_url(hired) + "?edit=1").content.decode()
    assert 'name="clan_name"' in edit and 'form="sec-identity-form"' in edit


def test_section_save_ignores_blank_required_outside_section(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    loaded = _open(client, hired)
    Employee.objects.filter(pk=hired.pk).update(work_phone="")  # old data: required field outside the section
    response = client.post(_url(hired), {"clan_name": "Ботгон", "loaded": loaded})
    assert response.status_code == 200
    assert 'class="mt-1 text-xs text-red-600"' not in response.content.decode()
    hired.refresh_from_db()
    assert hired.clan_name == "Ботгон"


def test_section_db_refused_saves_nothing(client: Client, hired: Employee, monkeypatch: pytest.MonkeyPatch) -> None:
    from django.db import DataError

    from employees.services import records
    from employees.views import DB_REFUSED

    def refuse(*args: object, **kwargs: object) -> None:
        raise DataError("value too long")

    login_as(client, "HR")
    loaded = _open(client, hired)
    monkeypatch.setattr(records, "update_employee", refuse)
    response = client.post(_url(hired), {"clan_name": "Ботгон", "loaded": loaded})
    assert response.status_code == 200
    assert DB_REFUSED in response.content.decode()
    hired.refresh_from_db()
    assert hired.clan_name != "Ботгон"


def _read(client: Client, employee: Employee, section: str) -> str:
    return client.get(_url(employee, section)).content.decode()


def test_identity_read_mode_merges_citizenship(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    mongolia = Country.objects.create(name="Монгол")
    Employee.objects.filter(pk=hired.pk).update(citizenship=mongolia, foreign_emp=0)
    body = _read(client, hired, "identity")
    assert "Монгол · гадаад иргэн биш" in body
    assert ">Гадаад иргэн</dt>" not in body  # one line with the citizenship, no row of its own
    Employee.objects.filter(pk=hired.pk).update(foreign_emp=1)
    assert "Монгол · гадаад иргэн" in _read(client, hired, "identity")


def test_passport_hidden_unless_foreign(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    Employee.objects.filter(pk=hired.pk).update(passport_no="AB1234567", foreign_emp=0)
    assert "AB1234567" not in _read(client, hired, "identity")
    Employee.objects.filter(pk=hired.pk).update(foreign_emp=1)
    assert "AB1234567" in _read(client, hired, "identity")


def test_other_section_read_mode_lists_every_field_even_when_empty(client: Client, hired: Employee) -> None:
    """«Бусад мэдээлэл» shows all its labels in read mode (a dash for empty ones), not a folded name list."""
    login_as(client, "HR")
    read = client.get(_url(hired, "other")).content.decode()
    for label in ("Цусны бүлэг", "Цэргийн алба", "Нийгмийн гарал", "Орон байрны нөхцөл", "Гутлын хэмжээ"):
        assert f">{label}</dt>" in read
    assert "<details" not in read
    Employee.objects.filter(pk=hired.pk).update(shoe_size=None)
    empty = _read(client, hired, "other")
    assert '>Гутлын хэмжээ</dt><dd><span class="text-slate-300">—</span></dd>' in empty


def test_edit_mode_has_save_and_cancel(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(_url(hired, "identity") + "?edit=1").content.decode()
    assert "Хадгалах" in body and "Болих" in body
    assert f'hx-get="{_url(hired, "identity")}"' in body  # Болих returns to read mode


def test_edit_mode_shows_error_of_field_outside_section(client: Client, hired: Employee) -> None:
    """A contact save fails on a birth-place error (the birth place is not in the contact section): it must show."""
    login_as(client, "HR")
    city = City.objects.create(name="Улаанбаатар")
    BirthPlace.objects.create(employee=hired, city=city, district=None)  # a city without a district: invalid
    loaded = _open(client, hired, "contact")
    response = client.post(_url(hired, "contact"), {"private_phone": "99001122", "loaded": loaded})
    body = response.content.decode()
    assert response.status_code == 200
    assert "Сум, дүүрэг сонгоогүй байна." in body
    assert 'name="private_phone"' in body  # still in edit mode
    hired.refresh_from_db()
    assert hired.private_phone != "99001122"
