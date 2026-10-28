from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.db import connection
from macs.models import (
    AcademicDegree,
    AddressRow,
    Branch,
    CertificateRow,
    City,
    ContactRow,
    ContactType,
    Country,
    Department,
    DisciplineType,
    District,
    DriverType,
    EducationLevel,
    EducRow,
    EduType,
    FamilyRelation,
    FamilyRow,
    ForeignLanguage,
    LanguageRow,
    MaterialHelpType,
    Position,
    PresentRow,
    PresentType,
    QualificationRow,
    SpecEduType,
    TalentKind,
    TrainingRow,
)

from employees.models import ActivityEntry, ActivityKind, Employee, GiftExt
from employees.services import personal_writes as pw
from employees.services.personal_writes import PersonalConflict


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("pw_actor", password="x-long-pass-123")  # noqa: S106


@pytest.fixture
def emp(hired: Employee) -> Employee:
    return hired


@pytest.fixture
def lists(db: None) -> dict[str, Any]:
    city = City.objects.create(name="Улаанбаатар")
    return {
        "relation": FamilyRelation.objects.create(name="Хүү", fm_type="son").pk,
        "edu": EduType.objects.create(name="Бакалавр").pk,
        "talent": TalentKind.objects.create(name="Хөгжим").pk,
        "talent2": TalentKind.objects.create(name="Спорт").pk,
        "present": PresentType.objects.create(name="Мөнгө").pk,
        "material_type": MaterialHelpType.objects.create(name="Эмчилгээ").pk,
        "discipline_type": DisciplineType.objects.create(name="Анхааруулга").pk,
        "driver_type": DriverType.objects.create(name="B ангилал").pk,
        "contact": ContactType.objects.create(name="Утас").pk,
        "city": city.pk,
        "district": District.objects.create(name="Баянгол", city=city).pk,
        "spec_edu_type": SpecEduType.objects.create(name="Инженер").pk,
        "language": ForeignLanguage.objects.create(name="Англи").pk,
        "edu_level": EducationLevel.objects.create(name="Бакалавр").pk,
        "grade": AcademicDegree.objects.create(name="Баклавр").pk,
        "country": Country.objects.create(name="Япон").pk,
        "branch": Branch.objects.create(name="Төв салбар").pk,
        "department": Department.objects.create(name="Санхүү").pk,
        "position": Position.objects.create(name="Нярав").pk,
    }


def _values(kind: str, lists: dict[str, Any]) -> dict[str, object]:
    if kind == "before_work":
        return {
            "worked_place": "Анод ХХК",
            "start_text": "2019 оны 3-р сар",
            "end_text": "2021 оны 6-р сар",
            "profession": "Нягтлан",
            "shaltgaan": "Өөрийн хүсэлт",
            "start_year": 2019,
            "end_year": 2021,
        }
    if kind == "relative":
        return {
            "given_name": "Дорж",
            "father_name": "Бат",
            "phone": "99112233",
            "description": "Эхнэр",
            "branch_id": lists["branch"],
            "department_id": lists["department"],
            "position_id": lists["position"],
        }
    if kind == "family":
        return {"relation_id": lists["relation"], "given_name": "Болд", "surname": "Бат", "job": "Багш"}
    if kind == "education":
        return {
            "org_name": "МУИС",
            "start_year": 2010,
            "end_year": 2014,
            "edu_level_id": lists["edu_level"],
            "grade_id": lists["grade"],
            "country": str(lists["country"]),
        }
    if kind == "talent":
        return {"talent_ident": lists["talent"], "trained_year": 2015, "description": "Хийл"}
    if kind == "skill":
        return {
            "description": "Excel",
            "norm": Decimal("1.50"),
            "department_id": lists["department"],
            "sdate": date(2026, 1, 15),
            "comment": "Туршилт",
        }
    if kind == "gift":
        return {
            "present_type_id": lists["present"],
            "pdate": date(2025, 3, 8),
            "given_year": 2025,
            "childqty": 1,
            "price": 50000,
            "child_age": 3,
            "given": 1,
        }
    if kind == "material_help":
        return {
            "material_type_id": lists["material_type"],
            "amount": Decimal("1250000"),
            "help_date": date(2026, 1, 15),
            "description": "Эмнэлгийн зардал",
        }
    if kind == "award":
        return {
            "give_org": "Засгийн газар",
            "award_name": "Гавьяа медаль",
            "award_date": date(2026, 3, 8),
            "description": "Жилийн үр дүн",
        }
    if kind == "discipline":
        return {
            "from_discipline": "Санхүүгийн алба",
            "discipline_type_id": lists["discipline_type"],
            "discipline_date": date(2026, 2, 1),
            "description": "Хоцорсон",
            "discipline_sal_percent": Decimal("12.50"),
            "discipline_enddate": date(2026, 5, 1),
        }
    if kind == "driver":
        return {
            "driver_type_id": lists["driver_type"],
            "number_driver": "1234567",
            "inserted_ognoo": date(2026, 3, 1),
        }
    if kind == "army_rank":
        return {"rank_date": date(2025, 6, 1), "rank": "Ахлагч", "addition_r": Decimal("15.00")}
    if kind == "military":
        return {
            "army_rank": "Ахлагч",
            "mil_rank": "Бэлтгэл-1",
            "study_type": "2 жил",
            "sacking_date": date(2026, 3, 1),
            "sacking_reason": "Хугацаа дууссан",
        }
    if kind == "complaint":
        return {"cdate": date(2026, 2, 1), "ctype": 1, "complaint_name": 2, "comment": "Хүлээн авалт"}
    if kind == "body":
        return {
            "inserted_ognoo": date(2026, 2, 1),
            "term_type": "Жилийн",
            "end_date": date(2027, 2, 1),
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
        }
    if kind == "address":
        return {"city_id": lists["city"], "district_id": lists["district"], "street": "Жуулчин 12"}
    if kind == "certificate":
        return {
            "cert_type_id": lists["spec_edu_type"],
            "org_edu": "ШУТИС",
            "certify_year": 2020,
            "certify_number": "C-1",
        }
    if kind == "training":
        return {
            "tr_type": 1,
            "description": "Excel сургалт",
            "amount": Decimal("150000"),
            "pay_type": 3,
            "start_year": 2024,
            "days": 3,
        }
    if kind == "language":
        return {"language_id": lists["language"], "speaking_lvl": "Дунд", "reading_lvl": "Сайн"}
    return {"contact_type_id": lists["contact"], "name": "Дулмаа", "relative": "Эх", "value": "99112233"}


def _ext(kind: str) -> dict[str, object]:
    if kind == "gift":
        return {"note": "Шинэ жил"}
    return {}


def _rows_for(kind: str, emp: Employee) -> list[Any]:
    if kind == "talent":
        with connection.cursor() as cur:
            cur.execute(
                "SELECT talent_ident, trained_year, description FROM emp_talents WHERE emp_ident = %s", [emp.pk]
            )
            rows: list[Any] = cur.fetchall()
            return rows
    return list(pw._MODELS[kind].objects.filter(employee=emp))


def _add(kind: str, emp: Employee, lists: dict[str, Any], actor: User, ext: dict[str, object] | None = None) -> Any:
    return pw.add(kind, emp, _values(kind, lists), _ext(kind) if ext is None else ext, actor)


def _changed(kind: str, lists: dict[str, Any]) -> dict[str, object]:
    """Values for an edit that differ from the ones `_values` add."""
    values = dict(_values(kind, lists))
    if kind == "talent":
        values["description"] = "Гитар"
    elif kind == "before_work":
        values["worked_place"] = "Шинэ газар"
    elif kind == "skill":
        values["description"] = "Word"
    elif kind == "material_help":
        values["amount"] = Decimal("500000")
    elif kind == "award":
        values["award_name"] = "Шинэ шагнал"
    elif kind == "discipline":
        values["description"] = "Шинэ тайлбар"
    elif kind == "complaint":
        values["comment"] = "Шинэ тайлбар"
    elif kind == "body":
        values["conclusion"] = "Шинэ дүгнэлт"
    elif kind == "driver":
        values["number_driver"] = "7654321"
    elif kind == "military":
        values["army_rank"] = "Сержант"
    elif kind == "army_rank":
        values["rank"] = "Сержант"
    elif kind == "relative":
        values["given_name"] = "Ганаа"
    elif kind == "family":
        values["given_name"] = "Ганаа"
    elif kind == "education":
        values["start_year"] = 2011
        values["org_name"] = "ШУТИС"
    elif kind == "gift":
        values["price"] = 60000
    elif kind == "address":
        values["street"] = "Шинэ гудамж 3"
    elif kind == "certificate":
        values["org_edu"] = "МУИС"
    elif kind == "training":
        values["days"] = 5
    elif kind == "language":
        values["speaking_lvl"] = "Сайн"
    else:
        values["name"] = "Сарангэрэл"
    return values


def _loaded(kind: str, emp: Employee, key: Any) -> dict[str, object]:
    snap = pw.load(kind, emp, key)
    assert snap is not None
    return snap


@pytest.mark.django_db
@pytest.mark.parametrize("kind", pw.KINDS)
def test_add_each_kind_inserts_and_logs(kind: str, emp: Employee, lists: dict[str, Any], actor: User) -> None:
    key = _add(kind, emp, lists, actor)
    assert len(_rows_for(kind, emp)) == 1
    assert pw.load(kind, emp, key) is not None
    entry = ActivityEntry.objects.filter(employee=emp).latest("id")
    assert entry.kind == ActivityKind.ADDED
    assert entry.personal is True
    assert entry.message.startswith(f"{pw.TITLES[kind]}: нэмсэн — ")


@pytest.mark.django_db
def test_language_log_shows_language_name(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    _add("language", emp, lists, actor)
    entry = ActivityEntry.objects.filter(employee=emp).latest("id")
    assert entry.message == f"{pw.TITLES['language']}: нэмсэн — Англи"


@pytest.mark.django_db
def test_talent_log_shows_talent_name(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    _add("talent", emp, lists, actor)
    entry = ActivityEntry.objects.filter(employee=emp).latest("id")
    assert entry.message == f"{pw.TITLES['talent']}: нэмсэн — Хөгжим"


@pytest.mark.django_db
def test_language_summary_falls_back_to_id_when_unknown() -> None:
    assert pw._summary("language", {"language_id": 987654}) == "987654"


@pytest.mark.django_db
@pytest.mark.parametrize("kind", pw.KINDS)
def test_update_each_kind(kind: str, emp: Employee, lists: dict[str, Any], actor: User) -> None:
    key = _add(kind, emp, lists, actor)
    loaded = _loaded(kind, emp, key)
    changed = _changed(kind, lists)
    ext_by_kind: dict[str, dict[str, object]] = {"gift": {"note": "Төрсөн өдөр"}}
    new_ext = ext_by_kind.get(kind, {})
    pw.update(kind, emp, key, loaded, changed, new_ext, actor)

    if kind == "talent":
        rows = [r for r in _rows_for(kind, emp) if r[0] == key]
        assert len(rows) == 1
        assert rows[0][2] == changed["description"]
    else:
        row = pw._MODELS[kind].objects.get(pk=key)
        for name, value in changed.items():
            assert getattr(row, name) == value, name
    if kind == "gift":
        assert GiftExt.objects.get(present_id=key).note == "Төрсөн өдөр"
    assert ActivityEntry.objects.filter(employee=emp, message__startswith=f"{pw.TITLES[kind]}: засварласан").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", pw.KINDS)
def test_delete_each_kind(kind: str, emp: Employee, lists: dict[str, Any], actor: User) -> None:
    key = _add(kind, emp, lists, actor)
    loaded = _loaded(kind, emp, key)
    pw.delete(kind, emp, key, loaded, actor)
    assert _rows_for(kind, emp) == []
    assert pw.load(kind, emp, key) is None
    entry = ActivityEntry.objects.filter(employee=emp, message__startswith=f"{pw.TITLES[kind]}: устгасан").get()
    assert entry.kind == ActivityKind.DELETED


@pytest.mark.django_db
def test_update_stale_when_changed(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    key = _add("family", emp, lists, actor)
    loaded = _loaded("family", emp, key)
    with connection.cursor() as cur:
        cur.execute("UPDATE family SET job = 'Өөр' WHERE family_id = %s", [key])
    with pytest.raises(PersonalConflict) as err:
        pw.update("family", emp, key, loaded, _changed("family", lists), {}, actor)
    assert str(err.value) == pw.STALE


@pytest.mark.django_db
def test_update_vanished_row_stale(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    key = _add("contact", emp, lists, actor)
    loaded = _loaded("contact", emp, key)
    with connection.cursor() as cur:
        cur.execute("DELETE FROM contacting WHERE contacting_id = %s", [key])
    with pytest.raises(PersonalConflict) as err:
        pw.update("contact", emp, key, loaded, _changed("contact", lists), {}, actor)
    assert str(err.value) == pw.STALE


@pytest.mark.django_db
def test_delete_stale_when_changed(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    key = _add("address", emp, lists, actor)
    loaded = _loaded("address", emp, key)
    with connection.cursor() as cur:
        cur.execute("UPDATE address SET address = 'Өөр' WHERE address_id = %s", [key])
    with pytest.raises(PersonalConflict) as err:
        pw.delete("address", emp, key, loaded, actor)
    assert str(err.value) == pw.STALE
    assert AddressRow.objects.filter(pk=key).exists()


@pytest.mark.django_db
def test_talent_update_clash_message(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    pw.add("talent", emp, {"talent_ident": lists["talent"], "trained_year": 2015, "description": "A"}, {}, actor)
    pw.add("talent", emp, {"talent_ident": lists["talent2"], "trained_year": 2016, "description": "B"}, {}, actor)
    before = sorted(_rows_for("talent", emp))
    loaded = _loaded("talent", emp, lists["talent2"])
    with pytest.raises(PersonalConflict) as err:
        pw.update("talent", emp, lists["talent2"], loaded, {"talent_ident": lists["talent"]}, {}, actor)
    assert str(err.value) == pw.TALENT_DUPLICATE
    assert sorted(_rows_for("talent", emp)) == before


@pytest.mark.django_db
def test_talent_add_clash_message(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    pw.add("talent", emp, {"talent_ident": lists["talent"], "trained_year": 2015, "description": "A"}, {}, actor)
    with pytest.raises(PersonalConflict) as err:
        pw.add("talent", emp, {"talent_ident": lists["talent"], "trained_year": 2020, "description": "C"}, {}, actor)
    assert str(err.value) == pw.TALENT_DUPLICATE
    assert len(_rows_for("talent", emp)) == 1


@pytest.mark.django_db
def test_gift_add_clash_message(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    _add("gift", emp, lists, actor)
    with pytest.raises(PersonalConflict) as err:
        _add("gift", emp, lists, actor)
    assert str(err.value) == pw.GIFT_DUPLICATE


@pytest.mark.django_db
def test_gift_update_clash_message(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    _add("gift", emp, lists, actor)
    other = {**_values("gift", lists), "child_age": 5}
    key = pw.add("gift", emp, other, {}, actor)
    loaded = _loaded("gift", emp, key)
    with pytest.raises(PersonalConflict) as err:
        pw.update("gift", emp, key, loaded, {"child_age": 3}, {}, actor)
    assert str(err.value) == pw.GIFT_DUPLICATE


@pytest.mark.django_db
def test_education_writes_qualification_row(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    key = _add("education", emp, lists, actor)
    row = QualificationRow.objects.get(pk=key)
    assert row.employee_id == emp.pk
    assert row.org_name == "МУИС"
    assert row.country == str(lists["country"])
    assert not EducRow.objects.filter(employee=emp).exists()
    entry = ActivityEntry.objects.filter(employee=emp).latest("id")
    assert entry.message == f"{pw.TITLES['education']}: нэмсэн — МУИС"


@pytest.mark.django_db
def test_gift_ext_stored_and_removed_with_row(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    key = _add("gift", emp, lists, actor)
    assert GiftExt.objects.get(present_id=key).note == "Шинэ жил"
    pw.delete("gift", emp, key, _loaded("gift", emp, key), actor)
    assert not GiftExt.objects.filter(present_id=key).exists()
    assert not PresentRow.objects.filter(pk=key).exists()


@pytest.mark.django_db
def test_constraint_error_not_500(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    values = _values("contact", lists)
    values["name"] = None  # contact_name is NOT NULL in production
    with pytest.raises(PersonalConflict) as err:
        pw.add("contact", emp, values, {}, actor)
    assert str(err.value) == pw.CONSTRAINT
    assert not ContactRow.objects.filter(employee=emp).exists()
    assert not ActivityEntry.objects.filter(employee=emp, personal=True).exists()


@pytest.mark.django_db
def test_snapshot_keys_for_talent_and_model(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    key = _add("family", emp, lists, actor)
    snap = pw.snapshot("family", FamilyRow.objects.get(pk=key))
    assert set(snap) == {"employee_id", "relation_id", "given_name", "surname", "birth_date", "job", "phone"}
    assert pw.snapshot("talent", (1, 2015, "x")) == {"talent_ident": 1, "trained_year": 2015, "description": "x"}


@pytest.mark.django_db
def test_new_kinds_write_to_their_production_columns(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    cert = _add("certificate", emp, lists, actor)
    training = _add("training", emp, lists, actor)
    language = _add("language", emp, lists, actor)
    assert CertificateRow.objects.get(pk=cert).employee_id == emp.pk
    assert TrainingRow.objects.get(pk=training).employee_id == emp.pk
    assert LanguageRow.objects.get(pk=language).language_id == lists["language"]
    with connection.cursor() as cur:
        cur.execute("SELECT emp_ident FROM hr_training WHERE training_id = %s", [training])
        assert cur.fetchone() == (emp.pk,)
    assert pw.snapshot("training", TrainingRow.objects.get(pk=training))["employee_id"] == emp.pk
