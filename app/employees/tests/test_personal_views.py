"""Personal tab rows: per-row add, edit and delete on the production tables (spec §4-§6)."""

import html
import json
import re
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from macs.models import (
    AcademicDegree,
    AddressRow,
    ArmyRankRow,
    AwardRow,
    BeforeWorkRow,
    BirthPlace,
    Branch,
    City,
    ComplaintRow,
    ContactRow,
    ContactType,
    Country,
    Department,
    DisciplineRow,
    DisciplineType,
    District,
    DriverRow,
    DriverType,
    EducationLevel,
    FamilyRelation,
    FamilyRow,
    ForeignLanguage,
    LanguageLevel,
    MaterialHelpType,
    MilitaryRow,
    Position,
    PresentType,
    QualificationRow,
    RelativeRow,
    SkillWorkRow,
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
        "material_type": named(MaterialHelpType, "Эмчилгээ"),
        "discipline_type": named(DisciplineType, "Анхааруулга"),
        "driver_type": named(DriverType, "B ангилал"),
        "contact": named(ContactType, "Утас"),
        "city": city,
        "district": District.objects.get_or_create(name="Баянзүрх", city=city)[0],
        "branch": named(Branch, "Төв салбар"),
        "department": named(Department, "Санхүү"),
        "position": named(Position, "Нярав"),
    }


def values_for(kind: str, lists: dict[str, Any]) -> dict[str, Any]:
    """A valid POST for one add form."""
    return {
        "before_work": {
            "worked_place": "Анод ХХК",
            "start_text": "2019 оны 3-р сар",
            "end_text": "2021 оны 6-р сар",
            "profession": "Нягтлан",
            "shaltgaan": "Өөрийн хүсэлт",
            "start_year": "2019",
            "end_year": "2021",
        },
        "relative": {
            "given_name": "Дорж",
            "father_name": "Бат",
            "phone": "99112233",
            "description": "Эхнэр",
            "branch": lists["branch"].pk,
            "department": lists["department"].pk,
            "position": lists["position"].pk,
        },
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
        "material_help": {
            "material_type": lists["material_type"].pk,
            "amount": "1,250,000",
            "help_date": "2026-01-15",
            "description": "Эмнэлгийн зардал",
        },
        "skill": {
            "description": "Excel ашиглах",
            "norm": "1.50",
            "department": lists["department"].pk,
            "sdate": "2026-01-15",
            "comment": "Туршилт",
        },
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
        "award": {
            "give_org": "Засгийн газар",
            "award_name": "Гавьяа медаль",
            "award_date": "2026-03-08",
            "description": "Жилийн үр дүн",
        },
        "discipline": {
            "from_discipline": "Санхүүгийн алба",
            "discipline_type": lists["discipline_type"].pk,
            "discipline_date": "2026-02-01",
            "description": "Хоцорсон",
            "discipline_sal_percent": "12.50",
            "discipline_enddate": "2026-05-01",
        },
        "complaint": {"cdate": "2026-02-01", "ctype": 1, "complaint_name": 2, "comment": "Хүлээн авалт"},
        "body": {
            "inserted_ognoo": "2026-02-01",
            "term_type": "Жилийн",
            "end_date": "2027-02-01",
            "own_letter": "Тийм",
            "ear": "Хэвийн",
            "dotor": "Хэвийн",
            "medrel": "Хэвийн",
            "setgel_medrel": "Хэвийн",
            "mes_zasal": "Хэвийн",
            "nud": "Хэвийн",
            "female": "Хэвийн",
            "rentgen": "Хэвийн",
            "skin": "Хэвийн",
            "conclusion": "Ажилд тохиромжтой",
            "sign": "Б.Болд",
        },
        "driver": {
            "driver_type": lists["driver_type"].pk,
            "number_driver": "1234567",
            "inserted_ognoo": "2026-03-01",
        },
        "army_rank": {"rank_date": "2025-06-01", "rank": "Ахлагч", "addition_r": "15.00"},
        "military": {
            "army_rank": "Ахлагч",
            "mil_rank": "Бэлтгэл-1",
            "study_type": "2 жил",
            "sacking_date": "2026-03-01",
            "sacking_reason": "Хугацаа дууссан",
        },
        "address": {"city": lists["city"].pk, "district": lists["district"].pk, "street": "БЗД 3-р хороо"},
        "contact": {"contact_type": lists["contact"].pk, "name": "Болд", "relative": "Ах", "value": "99887766"},
    }[kind]


CHANGES = {
    "before_work": {"worked_place": "Шинэ газар"},
    "relative": {"given_name": "Болд"},
    "family": {"given_name": "Болд"},
    "education": {"start_year": "2006", "org_name": "ШУТИС"},
    "talent": {"description": "Гитар хөгжим"},
    "skill": {"description": "Word ашиглах"},
    "material_help": {"description": "Шинэ тайлбар"},
    "award": {"award_name": "Шинэ шагнал"},
    "discipline": {"description": "Шинэ тайлбар"},
    "complaint": {"comment": "Шинэ тайлбар"},
    "body": {"conclusion": "Шинэ дүгнэлт"},
    "driver": {"number_driver": "7654321"},
    "military": {"army_rank": "Сержант"},
    "army_rank": {"rank": "Сержант"},
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
    start = body.index('id="tab-personal"')
    positions = [body.index(f">{title}", start) for title in titles]
    assert positions == sorted(positions)
    # address, contact, family, education, certificate, training, language, talent, gift are empty (9),
    # plus the 11 new personal lists, each empty list adds one more: 9 + 11 = 20
    assert body.count("бүртгэгдээгүй") == 20


ANKETA_ORDER = (
    "identity",
    "contact",
    "family",
    "relative",
    "education",
    "before_work",
    "certificate",
    "training",
    "language",
    "talent",
    "skill",
    "award",
    "discipline",
    "complaint",
    "gift",
    "material_help",
    "body",
    "driver",
    "military",
    "army_rank",
    "other",
)


def test_personal_tab_sections_in_anketa_order(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    positions = [body.index(f'id="sec-{name}"') for name in ANKETA_ORDER]
    assert positions == sorted(positions)
    # the menu links follow the same order, and each group header sits right before its first entry
    menu = [body.index(f'href="#sec-{name}"') for name in ANKETA_ORDER]
    assert menu == sorted(menu)
    for key, first in (("basic", "identity"), ("edu", "education"), ("award", "award"), ("health", "body"), ("other", "other")):
        assert body.index(f'data-group="{key}"') < body.index(f'href="#sec-{first}"')


def _nav_count(body: str, section: str) -> str:
    """The grey count shown in the section menu link of one section."""
    found = re.search(rf'data-sec="{section}"(?:(?!</a>).)*?text-xs text-slate-[34]00">([^<]*)</span>', body, re.S)
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
    assert 'id="personal-nav"' not in body[start:end]  # the section menu lives in the page rail
    assert 'id="personal-nav"' in body[body.index('id="emp-rail"'):start]


def test_personal_tab_comes_last_in_rail_and_tab_bar(client: Client, hired: Employee) -> None:
    """«Хувийн» opens into a long section menu, so it is the last tab: «Цалин, даатгал» stays near the top
    (UI_RULES §8)."""
    login_as(client, "Admin")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    rail = body[body.index('id="emp-rail"') :]
    assert rail.index('href="#work"') < rail.index('href="#salary"') < rail.index('href="#personal"')
    bar = body[body.index('<nav class="flex gap-6') :]
    assert bar.index('href="#work"') < bar.index('href="#salary"') < bar.index('href="#personal"')


def test_rail_names_the_employee_for_a_scrolled_page(client: Client, hired: Employee) -> None:
    """The rail carries the employee's name, hidden until the page header scrolls away (UI_RULES §8)."""
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    rail = body[body.index('id="emp-rail"') : body.index("</aside>", body.index('id="emp-rail"'))]
    who = rail[rail.index('id="rail-who"') : rail.index("</div>", rail.index('id="rail-who"'))]
    assert "hidden" in who
    assert hired.full_name in who


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
    section = client.get(f"/employees/{hired.pk}/section/identity/").content.decode()
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


def test_relative_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "relative"), values_for("relative", lists)).status_code == 204
    body = render_section("relative", hired)
    for header in ["Нэр", "Эцэг/эхийн нэр", "Ажилтны хэн болох", "Утас", "Ажилладаг салбар", "Хэлтэс", "Албан тушаал"]:
        assert f">{header}</th>" in body, header
    assert "Дорж" in body and "Бат" in body and "Нярав" in body and "Төв салбар" in body
    assert "Санхүү" in body and "Эхнэр" in body and "99112233" in body
    key = only_key(hired, "relative")
    assert edit_url(hired, "relative", key) in body


def test_relative_row_all_optional_null_is_editable(client: Client, hired: Employee) -> None:
    row = RelativeRow.objects.create(employee=hired, given_name="Дорж", description="Эхнэр")
    login_as(client, "HR")
    popup = client.get(edit_url(hired, "relative", row.pk))
    assert popup.status_code == 200
    post = edit_post(client, hired, "relative", row.pk)
    assert client.post(edit_url(hired, "relative", row.pk), post).status_code == 204
    row.refresh_from_db()
    assert (row.given_name, row.description, row.branch_id) == ("Дорж", "Эхнэр", None)


def test_relative_menu_after_family(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Хамаатан садан</span>" in body
    family, relative, education = (body.index(f'href="#sec-{s}"') for s in ("family", "relative", "education"))
    assert family < relative < education


def test_before_work_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "before_work"), values_for("before_work", lists)).status_code == 204
    body = render_section("before_work", hired)
    headers = ["Газар", "Мэргэжил", "Хугацаа", "Гарсан шалтгаан"]  # one period column (UI_RULES §4)
    for header in headers:
        assert f">{header}</th>" in body, header
    assert "Анод ХХК" in body and "Нягтлан" in body and "2019 оны 3-р сар" in body
    assert "2021 оны 6-р сар" in body and "Өөрийн хүсэлт" in body
    assert edit_url(hired, "before_work", only_key(hired, "before_work")) in body


def test_before_work_text_dates_unchanged_edit_is_not_stale(
    client: Client, hired: Employee, lists: dict[str, Any]
) -> None:
    row = BeforeWorkRow.objects.create(
        employee=hired,
        worked_place="Анод ХХК",
        start_text="2019 оны 3-р сар",
        end_text="2021 оны 6-р сар",
        start_year=2019,
        end_year=2021,
    )
    login_as(client, "HR")
    post = edit_post(client, hired, "before_work", row.pk)
    assert client.post(edit_url(hired, "before_work", row.pk), post).status_code == 204
    row.refresh_from_db()
    assert (row.start_text, row.end_text) == ("2019 оны 3-р сар", "2021 оны 6-р сар")


@pytest.mark.parametrize("missing", ["start_year", "end_year"])
def test_before_work_requires_years(client: Client, hired: Employee, lists: dict[str, Any], missing: str) -> None:
    login_as(client, "HR")
    post = {k: v for k, v in values_for("before_work", lists).items() if k != missing}
    response = client.post(add_url(hired, "before_work"), post)
    assert response.status_code == 200
    assert response.context["form"].errors[missing]
    assert not BeforeWorkRow.objects.filter(employee=hired).exists()


def test_before_work_menu_between_education_and_certificate(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Ажлын туршлага</span>" in body
    education, before_work, certificate = (
        body.index(f'href="#sec-{s}"') for s in ("education", "before_work", "certificate")
    )
    assert education < before_work < certificate


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
            elif kind == "material_help":
                data["material_type"] = named(MaterialHelpType, f"Төрөл {i}").pk
            elif kind == "discipline":
                data["discipline_type"] = named(DisciplineType, f"Шийтгэл {i}").pk
            elif kind == "family":
                data["surname"] = f"Овог {i}"
            elif kind == "contact":
                data["name"] = f"Нэр {i}"
            assert client.post(add_url(employee, kind), data).status_code == 204, (kind, i)


# Measured 2026-10-22 with 1 row per personal list kind (20 kinds): 152 queries for the GET of the employee page.
# Same count with 4 rows per kind (no per-row query) and 115 with no personal rows at all.
# Before the 11 new lists it was 98 (9 kinds, 1 row each; 97 on 2026-10-20, +1 for the old «Амралт» list).
# 156 with the on-the-spot «Хувийн мэдээлэл» (UI_RULES §2f, 2026-10-22), 164 once every field section is on the spot:
# their dropdowns load their lists on page load (a constant cost, not per row).
# 165 since Task 7b: the Work tab looks up the employee's waiting changes (+1 query, even with none).
# With one waiting change the page costs more again: see WAITING_ONE_QUERIES in test_waiting_display.py.
PERSONAL_TAB_QUERIES = 165


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


# Measured 2026-10-26 (Task 7b): the same page with one waiting change (a job change that waits for its order).
# One more query than PERSONAL_TAB_QUERIES: the baseline already counts the waiting-events lookup, and with a
# waiting event the order lookup runs too (views._awaiting_rows); with no waiting event that lookup is skipped.
WAITING_ONE_QUERIES = 166


def test_personal_tab_query_count_with_one_waiting_change(
    client: Client, hired: Employee, lists: dict[str, Any]
) -> None:
    from employees.models import Position
    from employees.services import events

    user = login_as(client, "HR")
    _add_rows(client, hired, lists, range(0, 1))
    with CaptureQueriesContext(connection) as before:
        assert client.get(f"/employees/{hired.pk}/").status_code == 200
    assert len(before.captured_queries) == PERSONAL_TAB_QUERIES
    events.record(
        hired,
        type="promotion",
        effective=date(2026, 12, 1),
        changes={"position": Position.objects.create(name="Ахлах тест")},
        salary=None,
        reason="",
        note="",
        by=user,
    )
    with CaptureQueriesContext(connection) as after:
        assert client.get(f"/employees/{hired.pk}/").status_code == 200
    assert len(after.captured_queries) == WAITING_ONE_QUERIES


def test_menu_item_partial_has_no_number() -> None:
    """Entries have no анкет numbers since 2026-10-22 (UI_RULES §8); a stray `number` is ignored."""
    plain = render_to_string(
        "employees/_personal_menu_item.html",
        {"sec": "language", "title": "Гадаад хэл", "count": "3", "number": 7},
    )
    assert "7." not in plain
    assert 'href="#sec-language"' in plain
    assert "Гадаад хэл" in plain
    assert ">3<" in plain


def _menu(page: str) -> str:
    """The personal tab's section menu out of a whole employee page."""
    start = page.index('id="personal-nav"')
    return page[start : page.index("</nav>", start)]


def test_menu_group_partial_links_to_its_group_page() -> None:
    """A group header opens that topic group as its own page (UI_RULES §8), it no longer folds."""
    group = render_to_string("employees/_personal_menu_group.html", {"title": "Бусад жагсаалт", "key": "other"})
    assert "Бусад жагсаалт" in group
    assert 'href="#personal-other"' in group
    assert 'data-pgroup-link="other"' in group
    assert "<button" not in group


def test_personal_tab_groups_match_the_menu(client: Client, hired: Employee) -> None:
    """Every menu group has a [data-pgroup] block on the tab; only the first starts shown."""
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    menu_keys = re.findall(r'data-pgroup-link="(\w+)"', _menu(body))
    tab = body[body.index('id="tab-personal"') :]
    assert menu_keys == ["basic", "edu", "award", "health", "other"]
    assert re.findall(r'<div data-pgroup="(\w+)"', tab) == menu_keys
    assert '<div data-pgroup="basic">' in tab
    assert all(f'<div data-pgroup="{k}" data-off>' in tab for k in menu_keys[1:])
    assert tab.index('<div data-pgroup="edu"') < tab.index('id="sec-talent"') < tab.index('<div data-pgroup="award"')


def test_menu_item_partial_without_count_has_no_count_span() -> None:
    plain = render_to_string("employees/_personal_menu_item.html", {"sec": "identity", "title": "Хувийн мэдээлэл"})
    assert "Хувийн мэдээлэл" in plain
    assert 'href="#sec-identity"' in plain
    assert "text-xs text-slate-400" not in plain


def test_skill_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "skill"), values_for("skill", lists)).status_code == 204
    body = render_section("skill", hired)
    for header in ("Огноо", "Даалгавар", "Нормын тоо", "Хэлтэс", "Тайлбар"):
        assert f">{header}</th>" in body, header
    assert "Excel ашиглах" in body and "2026-01-15" in body and "1.50" in body and "Туршилт" in body
    assert edit_url(hired, "skill", only_key(hired, "skill")) in body


def test_skill_department_shows_name(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "skill"), values_for("skill", lists)).status_code == 204
    [row] = personal_rows.rows("skill", hired)
    assert row.values["department"] == "Санхүү"
    assert "Санхүү" in render_section("skill", hired)


def test_skill_norm_unchanged_edit_is_not_stale(client: Client, hired: Employee) -> None:
    row = SkillWorkRow.objects.create(employee=hired, description="Excel", norm=Decimal("1.50"))
    login_as(client, "HR")
    post = edit_post(client, hired, "skill", row.pk)
    assert client.post(edit_url(hired, "skill", row.pk), post).status_code == 204
    row.refresh_from_db()
    assert row.norm == Decimal("1.50")


def test_skill_menu_between_talent_and_gift(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Ур чадварын даалгавар</span>" in body
    talent, skill, gift = (body.index(f'href="#sec-{s}"') for s in ("talent", "skill", "gift"))
    assert talent < skill < gift


def test_material_help_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "material_help"), values_for("material_help", lists)).status_code == 204
    body = render_section("material_help", hired)
    for header in ("Огноо", "Үндэслэл", "Мөнгөний дүн", "Тайлбар"):
        assert f">{header}</th>" in body, header
    assert "2026-01-15" in body and "Эмчилгээ" in body and "1,250,000" in body and "Эмнэлгийн зардал" in body
    assert edit_url(hired, "material_help", only_key(hired, "material_help")) in body


def test_material_help_menu_after_gift(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Буцалтгүй тусламж</span>" in body
    gift, material_help, other = (body.index(f'href="#sec-{s}"') for s in ("gift", "material_help", "other"))
    assert gift < material_help < other


def test_award_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "award"), values_for("award", lists)).status_code == 204
    body = render_section("award", hired)
    for header in ("Шагналын нэр", "Хаанаас", "Огноо", "Тайлбар"):
        assert f">{header}</th>" in body, header
    assert "Гавьяа медаль" in body and "Засгийн газар" in body and "2026-03-08" in body and "Жилийн үр дүн" in body
    assert edit_url(hired, "award", only_key(hired, "award")) in body


def test_award_empty_description_saves_empty_string(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    data = {**values_for("award", lists), "description": ""}
    assert client.post(add_url(hired, "award"), data).status_code == 204
    assert AwardRow.objects.get(employee=hired).description == ""
    key = only_key(hired, "award")
    post = edit_post(client, hired, "award", key)
    assert client.post(edit_url(hired, "award", key), {**post, "description": ""}).status_code == 204
    assert AwardRow.objects.get(pk=key).description == ""


def test_award_group_label_before_award_section(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    label = '<li class="menu-group" data-group="award">'
    assert label in body
    talent, group, award = (body.index(s) for s in ('href="#sec-skill"', label, 'href="#sec-award"'))
    assert talent < group < award
    assert "Шагнал урамшил</span>" in body


def test_discipline_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "discipline"), values_for("discipline", lists)).status_code == 204
    body = render_section("discipline", hired)
    for header in ("Огноо", "Шийтгэлийн нэр", "Хаанаас", "Шийтгэлийн хувь", "Дуусах огноо", "Тайлбар"):
        assert f">{header}</th>" in body, header
    for value in ("2026-02-01", "Анхааруулга", "Санхүүгийн алба", "12.50", "2026-05-01", "Хоцорсон"):
        assert value in body, value
    assert edit_url(hired, "discipline", only_key(hired, "discipline")) in body


def test_discipline_percent_and_dates_unchanged_edit_not_stale(
    client: Client, hired: Employee, lists: dict[str, Any]
) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "discipline"), values_for("discipline", lists)).status_code == 204
    key = only_key(hired, "discipline")
    assert DisciplineRow.objects.get(pk=key).discipline_sal_percent == Decimal("12.50")
    post = edit_post(client, hired, "discipline", key)
    assert client.post(edit_url(hired, "discipline", key), post).status_code == 204
    row = DisciplineRow.objects.get(pk=key)
    assert row.discipline_sal_percent == Decimal("12.50")
    assert row.discipline_date == date(2026, 2, 1)
    assert row.discipline_enddate == date(2026, 5, 1)


def test_discipline_menu_after_award(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Сахилгын шийтгэл</span>" in body
    award, discipline = (body.index(f'href="#sec-{s}"') for s in ("award", "discipline"))
    assert award < discipline


def test_complaint_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "complaint"), values_for("complaint", lists)).status_code == 204
    body = render_section("complaint", hired)
    for header in ("Огноо", "Төрөл", "Гомдол", "Тайлбар"):
        assert f">{header}</th>" in body, header
    for value in ("2026-02-01", "Санал асуулга", "Хүлээн авалт"):
        assert value in body, value
    assert edit_url(hired, "complaint", only_key(hired, "complaint")) in body


def test_complaint_codes_show_labels(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "complaint"), values_for("complaint", lists)).status_code == 204
    second = {**values_for("complaint", lists), "ctype": 2, "complaint_name": 1}
    assert client.post(add_url(hired, "complaint"), second).status_code == 204
    body = render_section("complaint", hired)
    for label in ("Харилцаа", "Ур чадвар", "Аман", "Санал асуулга"):
        assert label in body, label


def test_complaint_unknown_code_shows_number_and_stays_editable(
    client: Client, hired: Employee, lists: dict[str, Any]
) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "complaint"), values_for("complaint", lists)).status_code == 204
    key = only_key(hired, "complaint")
    ComplaintRow.objects.filter(pk=key).update(ctype=3)
    assert ">3</td>" in render_section("complaint", hired)
    assert client.get(edit_url(hired, "complaint", key)).status_code == 200
    post = edit_post(client, hired, "complaint", key)
    assert client.post(edit_url(hired, "complaint", key), post).status_code == 204
    assert ComplaintRow.objects.get(pk=key).ctype == 3


def test_complaint_menu_after_discipline(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Үйлчлүүлэгчийн гомдол</span>" in body
    body = _menu(body)  # the page also shows the group as a divider (UI_RULES §8)
    assert body.count("Шагнал, сахилга") == 1
    discipline, complaint = (body.index(f'href="#sec-{s}"') for s in ("discipline", "complaint"))
    assert discipline < complaint


BODY_FIELDS = (
    "inserted_ognoo",
    "term_type",
    "end_date",
    "own_letter",
    "ear",
    "dotor",
    "medrel",
    "setgel_medrel",
    "mes_zasal",
    "nud",
    "female",
    "rentgen",
    "skin",
    "conclusion",
    "sign",
)


def test_body_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "body"), values_for("body", lists)).status_code == 204
    body = render_section("body", hired)
    for header in ("Үзлэгийн огноо", "Үзлэгийн төрөл", "Дуусах хугацаа", "Дүгнэлт"):
        assert f">{header}</th>" in body, header
    for value in ("2026-02-01", "Жилийн", "2027-02-01", "Ажилд тохиромжтой"):
        assert value in body, value
    assert edit_url(hired, "body", only_key(hired, "body")) in body


def test_body_edit_popup_shows_every_field(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "body"), values_for("body", lists)).status_code == 204
    page = client.get(edit_url(hired, "body", only_key(hired, "body"))).content.decode()
    for name in BODY_FIELDS:
        assert f'name="{name}"' in page, name


def test_body_group_label_after_complaint(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    full = client.get(f"/employees/{hired.pk}/").content.decode()
    page = _menu(full)  # the page also shows the group as a divider (UI_RULES §8)
    assert page.count("Эрүүл мэнд, цэрэг") == 1
    group = page.index("Эрүүл мэнд, цэрэг")
    assert page[: group].rindex('<li class="menu-group') > page.index('href="#sec-complaint"')  # header opens its own <li>
    complaint, entry = (page.index(f'href="#sec-{s}"') for s in ("complaint", "body"))
    assert complaint < group < entry
    assert "Эрүүл мэндийн үзлэг</span>" in page
    assert full.index('id="sec-complaint"') < full.index('id="sec-body"')


def test_military_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "military"), values_for("military", lists)).status_code == 204
    body = render_section("military", hired)
    for header in ("Цэргийн цол", "Бэлтгэл зэрэг", "Алба хаасан жил", "Халагдсан огноо", "Халагдсан шалтгаан"):
        assert f">{header}</th>" in body, header
    for value in ("Ахлагч", "Бэлтгэл-1", "2 жил", "2026-03-01", "Хугацаа дууссан"):
        assert value in body, value
    assert edit_url(hired, "military", only_key(hired, "military")) in body


def test_military_row_all_optional_null_is_editable(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    empty = {"army_rank": "", "mil_rank": "", "study_type": "", "sacking_date": "", "sacking_reason": ""}
    assert client.post(add_url(hired, "military"), empty).status_code == 204
    key = only_key(hired, "military")
    row = MilitaryRow.objects.get(pk=key)
    assert row.army_rank is None
    assert row.sacking_date is None
    assert client.get(edit_url(hired, "military", key)).status_code == 200
    post = edit_post(client, hired, "military", key)
    assert client.post(edit_url(hired, "military", key), post).status_code == 204
    row.refresh_from_db()
    assert row.army_rank is None


def test_military_edit_popup_shows_every_field(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "military"), values_for("military", lists)).status_code == 204
    page = client.get(edit_url(hired, "military", only_key(hired, "military"))).content.decode()
    for name in ("army_rank", "mil_rank", "study_type", "sacking_date", "sacking_reason"):
        assert f'name="{name}"' in page, name


def test_military_menu_after_driver(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    body = _menu(body)  # the page also shows the group as a divider (UI_RULES §8)
    assert body.count("Эрүүл мэнд, цэрэг") == 1
    assert "Цэргийн алба</span>" in body
    driver, military = (body.index(f'href="#sec-{s}"') for s in ("driver", "military"))
    assert driver < military


def test_army_rank_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "army_rank"), values_for("army_rank", lists)).status_code == 204
    body = render_section("army_rank", hired)
    for header in ("Цэргийн цол", "Цол олгосон огноо", "Нэмэгдлийн хэмжээ"):
        assert f">{header}</th>" in body, header
    for value in ("Ахлагч", "2025-06-01", "15.00"):
        assert value in body, value
    assert edit_url(hired, "army_rank", only_key(hired, "army_rank")) in body


def test_army_rank_row_all_optional_null_is_editable(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    empty = {"rank_date": "", "rank": "", "addition_r": ""}
    assert client.post(add_url(hired, "army_rank"), empty).status_code == 204
    key = only_key(hired, "army_rank")
    row = ArmyRankRow.objects.get(pk=key)
    assert row.rank is None
    assert row.addition_r is None
    assert client.get(edit_url(hired, "army_rank", key)).status_code == 200
    post = edit_post(client, hired, "army_rank", key)
    assert client.post(edit_url(hired, "army_rank", key), post).status_code == 204
    row.refresh_from_db()
    assert row.rank is None


def test_army_rank_addition_unchanged_edit_not_stale(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "army_rank"), values_for("army_rank", lists)).status_code == 204
    key = only_key(hired, "army_rank")
    assert ArmyRankRow.objects.get(pk=key).addition_r == Decimal("15.00")
    post = edit_post(client, hired, "army_rank", key)
    assert client.post(edit_url(hired, "army_rank", key), post).status_code == 204
    assert ArmyRankRow.objects.get(pk=key).addition_r == Decimal("15.00")


def test_military_and_army_rank_are_separate_lists(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "military"), values_for("military", lists)).status_code == 204
    assert ArmyRankRow.objects.filter(employee=hired).count() == 0
    assert client.post(add_url(hired, "army_rank"), values_for("army_rank", lists)).status_code == 204
    assert MilitaryRow.objects.filter(employee=hired).count() == 1
    assert ArmyRankRow.objects.filter(employee=hired).count() == 1
    response = client.get(f"/employees/{hired.pk}/")
    assert response.context["section_counts"]["military"] == 1
    assert response.context["section_counts"]["army_rank"] == 1


def test_army_rank_menu_after_military(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    assert "Цэргийн цол</span>" in body
    military, army_rank = (body.index(f'href="#sec-{s}"') for s in ("military", "army_rank"))
    assert military < army_rank
    assert body.index('id="sec-military"') < body.index('id="sec-army_rank"')


def test_driver_section_renders_columns(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "driver"), values_for("driver", lists)).status_code == 204
    body = render_section("driver", hired)
    for header in ("Жолооны ангилал", "Үнэмлэхний дугаар", "Үнэмлэх авсан огноо"):
        assert f">{header}</th>" in body, header
    for value in ("B ангилал", "1234567", "2026-03-01"):
        assert value in body, value
    assert edit_url(hired, "driver", only_key(hired, "driver")) in body


def test_driver_edit_popup_shows_every_field(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "driver"), values_for("driver", lists)).status_code == 204
    page = client.get(edit_url(hired, "driver", only_key(hired, "driver"))).content.decode()
    for name in ("driver_type", "number_driver", "inserted_ognoo"):
        assert f'name="{name}"' in page, name


def test_driver_unchanged_edit_not_stale(client: Client, hired: Employee, lists: dict[str, Any]) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, "driver"), values_for("driver", lists)).status_code == 204
    key = only_key(hired, "driver")
    post = edit_post(client, hired, "driver", key)
    assert client.post(edit_url(hired, "driver", key), post).status_code == 204
    row = DriverRow.objects.get(pk=key)
    assert row.number_driver == "1234567"
    assert row.inserted_ognoo == date(2026, 3, 1)


def test_driver_menu_after_body(client: Client, hired: Employee) -> None:
    login_as(client, "HR")
    body = client.get(f"/employees/{hired.pk}/").content.decode()
    body = _menu(body)  # the page also shows the group as a divider (UI_RULES §8)
    assert body.count("Эрүүл мэнд, цэрэг") == 1
    assert "Жолоо</span>" in body
    entry, driver = (body.index(f'href="#sec-{s}"') for s in ("body", "driver"))
    assert entry < driver


NEW_KINDS = [
    "relative",
    "before_work",
    "skill",
    "material_help",
    "award",
    "discipline",
    "complaint",
    "body",
    "driver",
    "military",
    "army_rank",
]


def _user_with_perms(client: Client, *codenames: str) -> User:
    user = User.objects.create_user("limited", password="x-long-pass-123")  # noqa: S106
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="macs"))
    user = User.objects.get(pk=user.pk)  # fresh permission cache
    client.force_login(user)
    return user


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_new_list_hidden_without_personal_right(
    client: Client, hired: Employee, lists: dict[str, Any], kind: str
) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, kind), values_for(kind, lists)).status_code == 204
    key = only_key(hired, kind)
    assert f'id="sec-{kind}"' in client.get(f"/employees/{hired.pk}/").content.decode()  # HR sees it
    entries = ActivityEntry.objects.count()

    login_as(client, "Accountant", "acc")
    page = client.get(f"/employees/{hired.pk}/").content.decode()
    assert pw.TITLES[kind] not in page
    assert f'id="sec-{kind}"' not in page
    assert f'href="#sec-{kind}"' not in page
    assert client.get(add_url(hired, kind)).status_code in (403, 404)
    assert client.post(add_url(hired, kind), values_for(kind, lists)).status_code in (403, 404)
    assert client.get(edit_url(hired, kind, key)).status_code in (403, 404)
    assert client.post(edit_url(hired, kind, key), values_for(kind, lists)).status_code in (403, 404)
    assert client.get(delete_url(hired, kind, key)).status_code in (403, 404)
    assert client.post(delete_url(hired, kind, key), {}).status_code in (403, 404)
    assert len(personal_rows.rows(kind, hired)) == 1
    assert ActivityEntry.objects.count() == entries


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_new_list_needs_manage_to_edit(client: Client, hired: Employee, lists: dict[str, Any], kind: str) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, kind), values_for(kind, lists)).status_code == 204
    key = only_key(hired, kind)
    entries = ActivityEntry.objects.count()

    _user_with_perms(client, "view_employees", "view_personal")  # view-personal, but not manage
    assert f'id="sec-{kind}"' in client.get(f"/employees/{hired.pk}/").content.decode()
    assert client.get(add_url(hired, kind)).status_code in (403, 404)
    assert client.post(add_url(hired, kind), values_for(kind, lists)).status_code in (403, 404)
    assert client.post(edit_url(hired, kind, key), values_for(kind, lists)).status_code in (403, 404)
    assert client.post(delete_url(hired, kind, key), {}).status_code in (403, 404)
    assert len(personal_rows.rows(kind, hired)) == 1
    assert ActivityEntry.objects.count() == entries


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_new_list_activity_is_personal(client: Client, hired: Employee, lists: dict[str, Any], kind: str) -> None:
    login_as(client, "HR")
    assert client.post(add_url(hired, kind), values_for(kind, lists)).status_code == 204
    entry = ActivityEntry.objects.get(employee=hired, message__startswith=f"{pw.TITLES[kind]}:")
    assert entry.personal is True
    assert entry.message.startswith(f"{pw.TITLES[kind]}: ")
