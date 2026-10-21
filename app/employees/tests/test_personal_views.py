"""Personal tab rows: per-row add, edit and delete on the production tables (spec §4-§6)."""

import html
import json
import re
from datetime import date
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from macs.models import (
    AcademicDegree,
    AddressRow,
    BirthPlace,
    City,
    ContactRow,
    ContactType,
    Country,
    District,
    EducationLevel,
    FamilyRelation,
    FamilyRow,
    ForeignLanguage,
    LanguageLevel,
    PresentType,
    QualificationRow,
    SpecEduType,
    TalentKind,
)

from employees import access
from employees.forms import BIRTH_FIELDS
from employees.models import PERSONAL_FIELDS, ActivityEntry, Employee
from employees.services import history, personal_rows
from employees.services import personal_writes as pw

from .conftest import hire_values, named
from .test_screen_fields import _edit_post
from .test_views import login_as

pytestmark = pytest.mark.django_db


@pytest.fixture
def lists(db: None) -> dict[str, Any]:
    city = named(City, "Улаанбаатар")
    return {
        "relation": named(FamilyRelation, "Эцэг"),
        "edu_level": named(EducationLevel, "Бакалавр"),
        "grade": named(AcademicDegree, "Баклавр"),
        "country": named(Country, "Япон"),
        "talent": named(TalentKind, "Хөгжим"),
        "spec_edu": named(SpecEduType, "Жолооч"),
        "language": named(ForeignLanguage, "Англи"),
        "level": named(LanguageLevel, "Дунд"),
        "talent2": named(TalentKind, "Зураг"),
        "present": named(PresentType, "Шинэ жил"),
        "contact": named(ContactType, "Утас"),
        "city": city,
        "district": District.objects.get_or_create(name="Баянзүрх", city=city)[0],
    }


def values_for(kind: str, lists: dict[str, Any]) -> dict[str, Any]:
    """A valid POST for one add form."""
    return {
        "family": {
            "relation": lists["relation"].pk,
            "given_name": "Дорж",
            "surname": "Бат",
            "birth_date": "1960-01-02",
            "job": "",
            "phone": "99112233",
        },
        "education": {
            "org_name": "МУИС",
            "start_year": "2005",
            "end_year": "2009",
            "edu_level": lists["edu_level"].pk,
            "grade": lists["grade"].pk,
            "country": lists["country"].pk,
        },
        "talent": {"talent": lists["talent"].pk, "trained_year": "2010", "description": "Гитар"},
        "certificate": {
            "cert_type": lists["spec_edu"].pk,
            "org_edu": "МУИС",
            "profession": "Инженер",
            "certify_number": "C-100",
            "certify_date": "2010-01-02",
            "certify_year": "2011",
        },
        "training": {
            "tr_type": "1",
            "description": "Python курс",
            "start_year": "2024",
            "start_date": "2024-03-01",
            "days": "5",
            "amount": "250,000",
            "pay_type": "3",
            "training_center": "Мэдээллийн төв",
        },
        "language": {
            "language": lists["language"].pk,
            "understand_lvl": "Дунд",
            "speaking_lvl": "",
            "reading_lvl": "Дунд",
            "writing_lvl": "",
            "description": "Ярианы",
        },
        "gift": {
            "present_type": lists["present"].pk,
            "pdate": "2026-01-01",
            "given_year": "2026",
            "childqty": "2",
            "child_age": "5",
            "price": "50,000",
            "given": "on",
            "note": "Бэлэг",
        },
        "address": {"city": lists["city"].pk, "district": lists["district"].pk, "street": "БЗД 3-р хороо"},
        "contact": {"contact_type": lists["contact"].pk, "name": "Болд", "relative": "Ах", "value": "99887766"},
    }[kind]


CHANGES = {
    "family": {"given_name": "Болд"},
    "education": {"start_year": "2006", "org_name": "ШУТИС"},
    "talent": {"description": "Гитар хөгжим"},
    "gift": {"note": "Шинэ бэлэг"},
    "address": {"street": "Шинэ гудамж"},
    "contact": {"name": "Болд Ах"},
    "certificate": {"org_edu": "ШУТИС"},
    "training": {"description": "Шинэ курс"},
    "language": {"description": "Шинэ тайлбар"},
}


def shown_value(row: Any, name: str) -> Any:
    """A displayed value of one row: a production field (list ids as names) or an HR-only ext field."""
    return row.values[name] if name in row.values else row.ext[name]


def add_url(employee: Employee, kind: str) -> str:
    return reverse("employees:personal_add", args=[employee.pk, kind])


def edit_url(employee: Employee, kind: str, key: int) -> str:
    return reverse("employees:personal_edit", args=[employee.pk, kind, key])


def delete_url(employee: Employee, kind: str, key: int) -> str:
    return reverse("employees:personal_delete", args=[employee.pk, kind, key])


def edit_post(client: Client, employee: Employee, kind: str, key: int) -> dict[str, Any]:
    """The POST an edit form sends: its initial values (loaded_* included), without the empty ones."""
    response = client.get(edit_url(employee, kind, key))
    assert response.status_code == 200
    return {k: v for k, v in response.context["form"].initial.items() if v is not None}


def delete_post(client: Client, employee: Employee, kind: str, key: int) -> dict[str, Any]:
    """The POST the confirm pop-up sends: only the loaded values it carries."""
    response = client.get(delete_url(employee, kind, key))
    assert response.status_code == 200
    return {k: v for k, v in response.context["form"].initial.items() if k.startswith("loaded_") and v is not None}


def only_key(employee: Employee, kind: str) -> Any:
    rows = personal_rows.rows(kind, employee)
    assert len(rows) == 1
    return rows[0].key


@pytest.mark.parametrize("kind", list(pw.KINDS))
def test_add_edit_delete_each_kind_view(client: Client, hired: Employee, lists: dict[str, Any], kind: str) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, kind), values_for(kind, lists)).status_code == 204
    key = only_key(hired, kind)

    added = personal_rows.rows(kind, hired)[0]
    for name in CHANGES[kind]:
        assert str(shown_value(added, name)) == str(values_for(kind, lists)[name]), name
    post = edit_post(client, hired, kind, key)
    assert client.post(edit_url(hired, kind, key), {**post, **CHANGES[kind]}).status_code == 204
    changed = personal_rows.rows(kind, hired)[0]
    for name, expected in CHANGES[kind].items():
        assert str(shown_value(changed, name)) == expected, name

    assert client.post(delete_url(hired, kind, key), delete_post(client, hired, kind, key)).status_code == 204
    assert personal_rows.rows(kind, hired) == []
    assert ActivityEntry.objects.filter(employee=hired, personal=True).count() == 3


def test_stale_edit_message_view(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "family"), values_for("family", lists))
    key = only_key(hired, "family")
    post = edit_post(client, hired, "family", key)
    FamilyRow.objects.filter(pk=key).update(job="Багш")  # another user changed the row meanwhile
    response = client.post(edit_url(hired, "family", key), {**post, "given_name": "Болд"})
    assert response.status_code == 200
    assert pw.STALE in response.content.decode()
    assert FamilyRow.objects.get(pk=key).given_name == "Дорж"  # nothing overwritten
    assert response.context["form"]["given_name"].value() == "Болд"  # values kept


def test_stale_delete_message_view(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "contact"), values_for("contact", lists))
    key = only_key(hired, "contact")
    loaded = delete_post(client, hired, "contact", key)
    ContactRow.objects.filter(pk=key).update(name="Өөр")
    response = client.post(delete_url(hired, "contact", key), loaded)
    assert response.status_code == 200
    assert pw.STALE in response.content.decode()
    assert ContactRow.objects.filter(pk=key).exists()


def test_old_address_bad_district_shown_and_deletable(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    other_city = named(City, "Дархан")
    AddressRow.objects.create(employee=hired, city=other_city, district=lists["district"], street="Хуучин")
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Хуучин" in body and "Баянзүрх" in body
    key = only_key(hired, "address")
    assert client.post(delete_url(hired, "address", key), delete_post(client, hired, "address", key)).status_code == 204
    assert AddressRow.objects.count() == 0


def test_district_city_mismatch_refused(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    other_city = named(City, "Дархан")
    login_as(client, "HR")
    data = {**values_for("address", lists), "city": other_city.pk}
    response = client.post(add_url(hired, "address"), data)
    assert response.status_code == 200
    assert "харьяалагдахгүй" in response.content.decode()
    assert not AddressRow.objects.exists()


def test_empty_contact_type_list_message(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    ContactType.objects.all().delete()
    login_as(client, "HR")
    body = client.get(add_url(hired, "contact")).content.decode()
    assert "жагсаалт хоосон байна" in body
    assert reverse("lists:list", args=["contact_type"]) in body


def test_permission_required(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "Accountant", "acc")
    assert client.get(add_url(hired, "family")).status_code == 403
    assert client.post(add_url(hired, "family"), values_for("family", lists)).status_code == 403
    assert not FamilyRow.objects.exists()


def test_unknown_kind_404(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    assert client.get(f"/employees/{hired.pk}/personal/bogus/add/").status_code == 404


def test_limits_refused(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    long_name = {**values_for("family", lists), "given_name": "А" * 41}
    response = client.post(add_url(hired, "family"), long_name)
    assert response.status_code == 200 and not FamilyRow.objects.exists()
    long_rel = {**values_for("contact", lists), "relative": "А" * 11}
    response = client.post(add_url(hired, "contact"), long_rel)
    assert response.status_code == 200 and not ContactRow.objects.exists()


def test_gift_duplicate_is_a_form_error(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "gift"), values_for("gift", lists)).status_code == 204
    response = client.post(add_url(hired, "gift"), values_for("gift", lists))
    assert response.status_code == 200
    assert pw.GIFT_DUPLICATE in response.content.decode()


def test_talent_duplicate_is_a_form_error(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "talent"), values_for("talent", lists)).status_code == 204
    response = client.post(add_url(hired, "talent"), values_for("talent", lists))
    assert response.status_code == 200
    assert pw.TALENT_DUPLICATE in response.content.decode()


def test_talent_edit_touches_one_row(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "talent"), values_for("talent", lists))
    client.post(add_url(hired, "talent"), {"talent": lists["talent2"].pk, "trained_year": "", "description": "Зурсан"})
    first = lists["talent"].pk
    post = edit_post(client, hired, "talent", first)
    assert client.post(edit_url(hired, "talent", first), {**post, "description": "Шинэ"}).status_code == 204
    by_talent = {r.key: r.values["description"] for r in personal_rows.rows("talent", hired)}
    assert by_talent == {first: "Шинэ", lists["talent2"].pk: "Зурсан"}


def test_old_education_row_is_editable(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    row = QualificationRow.objects.create(employee=hired, org_name="Хуучин", start_year=2001, end_year=2005)
    login_as(client, "HR")
    post = edit_post(client, hired, "education", row.pk)
    assert client.post(edit_url(hired, "education", row.pk), {**post, "org_name": "МУИС"}).status_code == 204
    assert QualificationRow.objects.get(pk=row.pk).org_name == "МУИС"


def test_education_edit_keeps_free_text_country(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    """A row whose country is legacy free text: the edit pop-up shows it blank, and an unchanged save keeps it."""
    row = QualificationRow.objects.create(
        employee=hired, org_name="МУИС", start_year=2001, end_year=2005, country="Монгол"
    )
    login_as(client, "HR")
    popup = client.get(edit_url(hired, "education", row.pk)).content.decode()
    assert 'name="loaded_country"' in popup
    post = edit_post(client, hired, "education", row.pk)
    assert client.post(edit_url(hired, "education", row.pk), post).status_code == 204
    assert QualificationRow.objects.get(pk=row.pk).country == "Монгол"


def test_personal_tab_renders_six_sections(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    titles = ["Хаяг", "Яаралтай үед холбогдох", "Гэр бүл", "Боловсрол", "Авьяас", "Олгосон бэлэг"]
    positions = [body.index(f">{title}") for title in titles]
    assert positions == sorted(positions)
    # address, contact, family, education, certificate, training, language, talent, gift are empty
    assert body.count("бүртгэгдээгүй") == 9


ANKETA_ORDER = (
    "identity",
    "contact",
    "family",
    "education",
    "certificate",
    "training",
    "language",
    "talent",
    "gift",
    "other",
)


def test_personal_tab_sections_in_anketa_order(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    positions = [body.index(f'id="sec-{name}"') for name in ANKETA_ORDER]
    assert positions == sorted(positions)


def _nav_count(body: str, section: str) -> str:
    """The grey count shown in the section menu link of one section."""
    found = re.search(rf'data-sec="{section}"(?:(?!</a>).)*?text-xs text-slate-400">([^<]*)</span>', body, re.S)
    assert found is not None, section
    return found.group(1)


def test_personal_nav_counts(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "address"), values_for("address", lists)).status_code == 204
    second = {**values_for("address", lists), "street": "Шинэ гудамж"}
    assert client.post(add_url(hired, "address"), second).status_code == 204
    Employee.objects.filter(pk=hired.pk).update(prior_service_years=3)
    with_service = _nav_count(client.get(f"/employees/{hired.pk}/").content.decode(), "other")
    Employee.objects.filter(pk=hired.pk).update(prior_service_years=0)
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert _nav_count(body, "contact") == "2"
    assert _nav_count(body, "gift") == "0"  # list sections always show their count, 0 included
    without_service = _nav_count(body, "other")
    assert without_service.endswith("/10")
    assert int(with_service.split("/")[0]) == int(without_service.split("/")[0]) + 1


def test_personal_tab_has_no_emp_form_inputs(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    start = body.index('id="tab-personal"')
    end = body.find('id="tab-salary"', start)
    if end == -1:
        end = body.index('id="activity-backdrop"', start)
    assert 'form="emp-form"' not in body[start:end]
    assert 'id="personal-nav"' in body[start:end]


def test_work_tab_save_ignores_personal_change_by_other_program(client: Client, hired: Employee) -> None:
    """The old program changed a personal field after the page opened: the Ажил save still succeeds,
    writes its own change and keeps the other program's value (no conflict on a field the tab never shows)."""
    login_as(client, "HR")
    page = client.get(f"/employees/{hired.pk}/").content.decode()
    found = re.search(r'name="loaded" value="([^"]*)"', page)
    assert found is not None
    loaded = html.unescape(found.group(1))
    Employee.objects.filter(pk=hired.pk).update(clan_name="Өөр")
    data = _edit_post(hired, work_phone="99112233")
    for name in (*PERSONAL_FIELDS, *BIRTH_FIELDS):
        data.pop(name, None)
    response = client.post(f"/employees/{hired.pk}/save/", data | {"loaded": loaded})
    assert response.status_code == 303, response.context["form"].errors
    row = Employee.objects.get(pk=hired.pk)
    assert row.work_phone == "99112233"
    assert row.clan_name == "Өөр"


def test_work_tab_save_keeps_personal_fields(client: Client, hired: Employee) -> None:
    """The Ажил tab posts no personal fields any more: the save must still pass and leave them alone."""
    login_as(client, "HR")
    data = _edit_post(hired, work_phone="99112233")
    for name in (*PERSONAL_FIELDS, *BIRTH_FIELDS):
        data.pop(name, None)
    response = client.post(f"/employees/{hired.pk}/save/", data)
    assert response.status_code == 303, response.context["form"].errors
    row = Employee.objects.get(pk=hired.pk)
    assert row.work_phone == "99112233"
    assert row.register_no == hired.register_no and row.birth_date == hired.birth_date


def test_work_tab_save_keeps_birthplace_saved_in_section(
    client: Client, hired: Employee, lists: dict[str, Any]
) -> None:
    """The page opened with the old birthplace; the identity section then saves a new one. The Ажил save with a
    work change and the OLD `loaded` must keep the new birthplace (the Ажил tab never posts birth fields)."""
    login_as(client, "HR")
    page = client.get(f"/employees/{hired.pk}/").content.decode()
    found = re.search(r'name="loaded" value="([^"]*)"', page)
    assert found is not None
    old_loaded = html.unescape(found.group(1))
    section = client.get(f"/employees/{hired.pk}/section/identity/?edit=1").content.decode()
    section_found = re.search(r'name="loaded" value="([^"]*)"', section)
    assert section_found is not None
    saved = client.post(
        f"/employees/{hired.pk}/section/identity/",
        {
            "birth_city": lists["city"].pk,
            "birth_district": lists["district"].pk,
            "birth_place_text": "Шинэ газар",
            "loaded": html.unescape(section_found.group(1)),
        },
    )
    assert saved.status_code == 200
    assert BirthPlace.objects.get(employee=hired).city_id == lists["city"].pk  # the section saved it
    data = _edit_post(hired, work_phone="99112233")
    for name in (*PERSONAL_FIELDS, *BIRTH_FIELDS):
        data.pop(name, None)
    response = client.post(f"/employees/{hired.pk}/save/", data | {"loaded": old_loaded})
    assert response.status_code == 303, response.context["form"].errors
    place = BirthPlace.objects.get(employee=hired)
    assert place.city_id == lists["city"].pk
    assert place.description == "Шинэ газар"


def test_personal_lists_hidden_from_accountant(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "gift"), values_for("gift", lists))
    assert "Олгосон бэлэг" in client.get(f"/employees/{hired.pk}/").content.decode()
    login_as(client, "Accountant", "acc")
    assert "Олгосон бэлэг" not in client.get(f"/employees/{hired.pk}/").content.decode()


def test_gift_year_defaults_to_date_year_on_add_only(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    data = {k: v for k, v in values_for("gift", lists).items() if k != "given_year"}
    assert client.post(add_url(hired, "gift"), data).status_code == 204
    key = only_key(hired, "gift")
    saved = personal_rows.row("gift", hired, key)
    assert saved is not None
    assert saved.values["given_year"] == 2026
    post = edit_post(client, hired, "gift", key)
    assert client.post(edit_url(hired, "gift", key), {**post, "pdate": "2025-03-01"}).status_code == 204
    edited = personal_rows.row("gift", hired, key)
    assert edited is not None
    assert edited.values["given_year"] == 2026  # never changed on edit


def test_district_choices_filtered_by_city(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    other = named(City, "Дархан")
    other_district = District.objects.get_or_create(name="Дархан хот", city=other)[0]
    login_as(client, "HR")
    url = add_url(hired, "address")
    shown = client.get(url, {"city": lists["city"].pk}).context["form"].fields["district"].queryset
    assert list(shown) == [lists["district"]]
    assert list(client.get(url, {"city": other.pk}).context["form"].fields["district"].queryset) == [other_district]
    assert list(client.get(url).context["form"].fields["district"].queryset) == []  # no city chosen yet
    client.post(url, values_for("address", lists))
    key = only_key(hired, "address")
    edit = client.get(edit_url(hired, "address", key)).context["form"]
    assert list(edit.fields["district"].queryset) == [lists["district"]]


def test_get_cannot_override_loaded_values(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "family"), values_for("family", lists))
    key = only_key(hired, "family")
    url = edit_url(hired, "family", key)
    response = client.get(url, {"loaded_given_name": json.dumps("Х"), "given_name": "Ү"})
    form = response.context["form"]
    assert form["loaded_given_name"].value() == json.dumps("Дорж")  # the value in the database, not the query string
    assert form["given_name"].value() == "Дорж"


def test_address_city_refetch_still_works(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    other = named(City, "Дархан")
    other_district = District.objects.get_or_create(name="Дархан хот", city=other)[0]
    login_as(client, "HR")
    client.post(add_url(hired, "address"), values_for("address", lists))
    key = only_key(hired, "address")
    url = edit_url(hired, "address", key)
    query = {"city": other.pk, "street": "Шинэ гудамж", "loaded_street": json.dumps("Х")}
    edit = client.get(url, query).context["form"]
    assert list(edit.fields["district"].queryset) == [other_district]
    assert edit["city"].value() == str(other.pk)
    assert edit["street"].value() == "Шинэ гудамж"  # typed text survives the city change
    assert edit["loaded_street"].value() == json.dumps("БЗД 3-р хороо")  # GET never sets loaded values
    add = client.get(add_url(hired, "address"), {"city": other.pk}).context["form"]
    assert list(add.fields["district"].queryset) == [other_district]


def test_address_shared_id_other_employee_untouched(
    client: Client, hired: Employee, lists: dict[str, Any], actor: User, job_values: dict[str, Any]
) -> None:
    other = history.hire(hire_values("УБ99112234"), {}, start=date(2026, 1, 5), job=job_values, salary=None, by=actor)
    with connection.cursor() as cur:  # the production key is (address_id, employee_ident): the same id may repeat
        for employee, street in ((hired, "Нэг"), (other, "Хоёр")):
            cur.execute(
                "INSERT INTO address (address_id, employee_ident, address, city_id, district)"
                " VALUES (%s, %s, %s, %s, %s)",
                [7001, employee.pk, street, lists["city"].pk, lists["district"].pk],
            )
    login_as(client, "HR")
    post = edit_post(client, hired, "address", 7001)
    assert client.post(edit_url(hired, "address", 7001), {**post, "street": "Шинэ"}).status_code == 204
    assert AddressRow.objects.get(pk=7001, employee=hired).street == "Шинэ"
    assert AddressRow.objects.get(pk=7001, employee=other).street == "Хоёр"

    assert (
        client.post(delete_url(hired, "address", 7001), delete_post(client, hired, "address", 7001)).status_code == 204
    )
    assert not AddressRow.objects.filter(pk=7001, employee=hired).exists()
    assert AddressRow.objects.get(pk=7001, employee=other).street == "Хоёр"


def test_personal_views_require_view_personal(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    manager = User.objects.create_user("manager", password="x-long-pass-123")  # noqa: S106
    for codename in ("manage_employees", "view_employees"):  # manage, but not view_personal
        manager.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="macs"))
    manager = User.objects.get(pk=manager.pk)  # fresh permission cache
    assert access.can_manage(manager) and not access.can_view_personal(manager, hired)
    client.force_login(manager)
    assert client.get(add_url(hired, "family")).status_code == 403
    assert client.post(add_url(hired, "family"), values_for("family", lists)).status_code == 403
    assert not FamilyRow.objects.exists()


def test_personal_edit_and_delete_require_view_personal(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "family"), values_for("family", lists))
    key = only_key(hired, "family")
    manager = User.objects.create_user("manager2", password="x-long-pass-123")  # noqa: S106
    manager.user_permissions.add(Permission.objects.get(codename="manage_employees", content_type__app_label="macs"))
    manager.user_permissions.add(Permission.objects.get(codename="view_employees", content_type__app_label="macs"))
    client.force_login(User.objects.get(pk=manager.pk))
    assert client.get(edit_url(hired, "family", key)).status_code == 403
    assert client.post(edit_url(hired, "family", key), {"given_name": "Болд"}).status_code == 403
    assert client.get(delete_url(hired, "family", key)).status_code == 403
    assert client.post(delete_url(hired, "family", key), {}).status_code == 403
    assert FamilyRow.objects.get(pk=key).given_name == "Дорж"


def test_district_options_requires_permission(client: Client, lists: dict[str, Any]) -> None:
    login_as(client, "Accountant", "acc")
    url = reverse("employees:district_options")
    assert client.get(url, {"addr-city": lists["city"].pk}).status_code == 403


def test_edit_popup_has_delete_link(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "family"), values_for("family", lists))
    key = only_key(hired, "family")
    body = client.get(edit_url(hired, "family", key)).content.decode()
    assert delete_url(hired, "family", key) in body
    assert 'hx-get="' + delete_url(hired, "family", key) + '"' in body
    assert "text-red-600" in body and "Устгах" in body


def test_add_popup_has_no_delete(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    client.post(add_url(hired, "family"), values_for("family", lists))
    key = only_key(hired, "family")
    body = client.get(add_url(hired, "family")).content.decode()
    assert delete_url(hired, "family", key) not in body
    assert "Устгах" not in body


def test_personal_tab_has_no_row_delete_buttons(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    delete_urls = []
    for kind in pw.KINDS:
        assert client.post(add_url(hired, kind), values_for(kind, lists)).status_code == 204
        delete_urls.append(delete_url(hired, kind, only_key(hired, kind)))
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    for url in delete_urls:
        assert url not in body
    family_key = only_key(hired, "family")
    assert edit_url(hired, "family", family_key) in body  # the row itself still opens the edit pop-up


def render_section(name: str, employee: Employee) -> str:
    """A list-section template rendered with the context the detail view gives it."""
    from django.template.loader import render_to_string

    personal = {kind: personal_rows.rows(kind, employee) for kind in pw.KINDS}
    return render_to_string(
        f"employees/_section_{name}.html", {"employee": employee, "personal": personal, "can_manage": True}
    )


def test_education_table_shows_qualification_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    post = {**values_for("education", lists), "diplom_number": "D-778", "credit_score": "3.5"}
    assert client.post(add_url(hired, "education"), post).status_code == 204
    body = client.get(f"/employees/{hired.pk}/section/education/").content.decode()
    for header in ["Сургууль", "Улс", "Он", "Боловсрол", "Мэргэжил", "Мэргэшил", "Зэрэг", "Голч", "Диплом №"]:
        assert f">{header}</th>" in body, header
    assert "2005–2009" in body
    assert "Япон" in body and "D-778" in body and "МУИС" in body
    key = only_key(hired, "education")
    assert edit_url(hired, "education", key) in body
    assert delete_url(hired, "education", key) not in body


def test_new_sections_render_rows(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "certificate"), values_for("certificate", lists)).status_code == 204
    assert client.post(add_url(hired, "training"), {**values_for("training", lists), "tr_type": "2"}).status_code == 204
    assert client.post(add_url(hired, "language"), values_for("language", lists)).status_code == 204
    certificate = render_section("certificate", hired)
    for header in ["Төрөл", "Байгууллага", "Мэргэжил", "Сертификат №", "Огноо", "Он"]:
        assert f">{header}</th>" in certificate, header
    assert "C-100" in certificate and "Жолооч" in certificate
    training = render_section("training", hired)
    for header in ["Он", "Сургалт", "Төв", "Хэлбэр", "Хоног", "Төлбөр", "Төлсөн"]:
        assert f">{header}</th>" in training, header
    assert "Гадаад" in training and "Байгууллага" in training and "250,000₮" in training
    language = render_section("language", hired)
    for header in ["Хэл", "Сонсох", "Ярих", "Унших", "Бичих", "Тайлбар"]:
        assert f">{header}</th>" in language, header
    assert "Англи" in language and "Дунд" in language


def test_empty_list_shows_not_registered(hired: Employee) -> None:
    body = render_section("certificate", hired)
    assert "бүртгэгдээгүй" in body
    assert ">Төрөл</th>" not in body
    assert "<table" not in body


def _add_rows(client: Client, employee: Employee, lists: dict[str, Any], numbers: range) -> None:
    """Add one row per number to every personal list kind; lookup-keyed kinds get a fresh lookup value per number."""
    for kind in pw.KINDS:
        for i in numbers:
            data = dict(values_for(kind, lists))
            if kind == "talent":
                data["talent"] = named(TalentKind, f"Авьяас {i}").pk
            elif kind == "gift":
                data["present_type"] = named(PresentType, f"Бэлэг {i}").pk
                data["pdate"] = f"2026-01-{i + 1:02d}"
            elif kind == "language":
                data["language"] = named(ForeignLanguage, f"Хэл {i}").pk
            elif kind == "family":
                data["surname"] = f"Овог {i}"
            elif kind == "contact":
                data["name"] = f"Нэр {i}"
            assert client.post(add_url(employee, kind), data).status_code == 204, (kind, i)


# Measured 2026-10-21 with 1 row per personal list kind (9 kinds): 98 queries for the GET of the employee page
# (97 on 2026-10-20, +1 for the old «Амралт» list in the leave block).
PERSONAL_TAB_QUERIES = 98


def test_personal_tab_query_count(
    client: Client, hired: Employee, lists: dict[str, Any], django_assert_max_num_queries: Any
) -> None:
    """Lists must not add a query per row: the page costs no more with 3 rows per kind than the 1-row count."""
    login_as(client, "HR")
    _add_rows(client, hired, lists, range(0, 1))
    with CaptureQueriesContext(connection) as one_row:
        assert client.get(f"/employees/{hired.pk}/").status_code == 200
    assert len(one_row.captured_queries) == PERSONAL_TAB_QUERIES
    _add_rows(client, hired, lists, range(1, 3))
    with django_assert_max_num_queries(PERSONAL_TAB_QUERIES):
        response = client.get(f"/employees/{hired.pk}/")
    assert response.status_code == 200
    assert "Нэр 2" in response.content.decode()  # the last row added (contact, i=2) is shown
