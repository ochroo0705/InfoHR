from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
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
    District,
    FamilyRelation,
    FamilyRow,
    ForeignLanguage,
    LanguageRow,
    Position,
    PresentRow,
    PresentType,
    QualificationRow,
    RelativeRow,
    SpecEduType,
    TalentKind,
    TrainingRow,
)

from employees.models import Employee, GiftExt
from employees.services import personal_rows as pr
from employees.services import personal_writes as pw


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("pr_actor", password="x-long-pass-123")  # noqa: S106


@pytest.fixture
def emp(hired: Employee) -> Employee:
    return hired


@pytest.fixture
def lists(db: None) -> dict[str, Any]:
    city = City.objects.create(name="Улаанбаатар")
    return {
        "relation": FamilyRelation.objects.create(name="Хүү", fm_type="son").pk,
        "talent": TalentKind.objects.create(name="Хөгжим").pk,
        "talent2": TalentKind.objects.create(name="Спорт").pk,
        "present": PresentType.objects.create(name="Мөнгө").pk,
        "contact": ContactType.objects.create(name="Утас").pk,
        "city": city.pk,
        "district": District.objects.create(name="Баянгол", city=city).pk,
        "spec_edu_type": SpecEduType.objects.create(name="Инженер").pk,
        "language": ForeignLanguage.objects.create(name="Англи").pk,
    }


@pytest.mark.django_db
def test_rows_order_per_kind(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    late = FamilyRow.objects.create(
        employee=emp, relation_id=lists["relation"], given_name="Б", birth_date=date(2015, 1, 1)
    )
    early = FamilyRow.objects.create(
        employee=emp, relation_id=lists["relation"], given_name="А", birth_date=date(2001, 1, 1)
    )
    tie = FamilyRow.objects.create(
        employee=emp, relation_id=lists["relation"], given_name="В", birth_date=date(2015, 1, 1)
    )
    assert [r.key for r in pr.rows("family", emp)] == [early.pk, late.pk, tie.pk]

    for year in (2012, 2008):
        QualificationRow.objects.create(employee=emp, org_name="X", start_year=year, end_year=year + 4)
    assert [r.values["start_year"] for r in pr.rows("education", emp)] == [2008, 2012]

    pw.add("talent", emp, {"talent_ident": lists["talent2"], "trained_year": 2010, "description": "a"}, {}, actor)
    pw.add("talent", emp, {"talent_ident": lists["talent"], "trained_year": 2011, "description": "b"}, {}, actor)
    assert [r.key for r in pr.rows("talent", emp)] == [lists["talent2"], lists["talent"]]

    old = PresentRow.objects.create(
        employee=emp,
        present_type_id=lists["present"],
        pdate=date(2020, 3, 8),
        given_year=2020,
        childqty=1,
        price=1,
        child_age=1,
        given=1,
    )
    new = PresentRow.objects.create(
        employee=emp,
        present_type_id=lists["present"],
        pdate=date(2025, 3, 8),
        given_year=2025,
        childqty=1,
        price=1,
        child_age=1,
        given=1,
    )
    assert [r.key for r in pr.rows("gift", emp)] == [new.pk, old.pk]

    a1 = AddressRow.objects.create(employee=emp, city_id=lists["city"], district_id=lists["district"], street="A")
    a2 = AddressRow.objects.create(employee=emp, city_id=lists["city"], district_id=lists["district"], street="B")
    assert [r.key for r in pr.rows("address", emp)] == [a1.pk, a2.pk]

    c1 = ContactRow.objects.create(employee=emp, contact_type_id=lists["contact"], name="X", relative="Эх")
    c2 = ContactRow.objects.create(employee=emp, contact_type_id=lists["contact"], name="Y", relative="Аав")
    assert [r.key for r in pr.rows("contact", emp)] == [c1.pk, c2.pk]


@pytest.mark.django_db
def test_old_gift_row_has_no_ext(emp: Employee, lists: dict[str, Any]) -> None:
    gift = PresentRow.objects.create(
        employee=emp,
        present_type_id=lists["present"],
        pdate=date(2024, 1, 1),
        given_year=2024,
        childqty=1,
        price=1,
        child_age=1,
        given=1,
    )
    [gift_row] = pr.rows("gift", emp)
    assert gift_row.key == gift.pk
    assert gift_row.from_old_system is True


@pytest.mark.django_db
def test_education_reads_old_program_row(emp: Employee, lists: dict[str, Any]) -> None:
    country = Country.objects.create(name="Япон")
    grade = AcademicDegree.objects.create(name="Баклавр")
    qual = QualificationRow.objects.create(
        employee=emp,
        org_name="МУИС",
        start_year=2005,
        end_year=2009,
        country=str(country.pk),
        grade_id=grade.pk,
        start_date=None,
    )
    [row] = pr.rows("education", emp)
    assert row.key == qual.pk
    assert row.values["country_name"] == "Япон"
    assert row.values["grade"] == "Баклавр"
    assert row.values["org_name"] == "МУИС"
    assert row.values["start_year"] == 2005
    assert row.values["end_year"] == 2009


@pytest.mark.django_db
@pytest.mark.parametrize(("raw", "shown"), [("Монгол", "Монгол"), (None, "—"), ("99999", "99999")])
def test_education_country_raw_text_shown(emp: Employee, raw: str | None, shown: str) -> None:
    QualificationRow.objects.create(employee=emp, org_name="X", start_year=2005, end_year=2009, country=raw)
    [row] = pr.rows("education", emp)
    assert row.values["country_name"] == shown


@pytest.mark.django_db
def test_training_labels(emp: Employee) -> None:
    TrainingRow.objects.create(
        employee=emp,
        tr_type=2,
        description="Курс",
        amount=Decimal("1000"),
        pay_type=5,
        start_year=2024,
    )
    TrainingRow.objects.create(
        employee=emp,
        tr_type=1,
        description="Курс 2",
        amount=Decimal("1000"),
        pay_type=9,
        start_year=2023,
    )
    by_desc = {r.values["description"]: r.values for r in pr.rows("training", emp)}
    assert by_desc["Курс"]["tr_type_label"] == "Гадаад"
    assert by_desc["Курс"]["pay_type_label"] == "Байгууллага"
    assert by_desc["Курс 2"]["pay_type_label"] == "9"


@pytest.mark.django_db
def test_language_and_certificate_rows_read(emp: Employee, lists: dict[str, Any]) -> None:
    LanguageRow.objects.create(employee=emp, language_id=lists["language"], speaking_lvl="Дунд")
    CertificateRow.objects.create(employee=emp, cert_type_id=lists["spec_edu_type"], org_edu="ШУТИС", certify_year=2020)
    [lang] = pr.rows("language", emp)
    assert lang.values["language"] == "Англи"
    assert lang.values["speaking_lvl"] == "Дунд"
    [cert] = pr.rows("certificate", emp)
    assert cert.values["cert_type"] == "Инженер"
    assert cert.values["org_edu"] == "ШУТИС"


@pytest.mark.django_db
def test_orphan_ext_ignored(emp: Employee, lists: dict[str, Any]) -> None:
    GiftExt.objects.create(present_id=987655, note="orphan")
    assert pr.rows("gift", emp) == []


@pytest.mark.django_db
def test_talent_key_is_talent_ident(emp: Employee, lists: dict[str, Any], actor: User) -> None:
    pw.add("talent", emp, {"talent_ident": lists["talent"], "trained_year": 2015, "description": "Хийл"}, {}, actor)
    [row] = pr.rows("talent", emp)
    assert row.key == lists["talent"]
    assert row.values == {"talent": "Хөгжим", "trained_year": 2015, "description": "Хийл"}
    assert row.snapshot == pw.snapshot("talent", (lists["talent"], 2015, "Хийл"))
    found = pr.row("talent", emp, lists["talent"])
    assert found is not None
    assert found.snapshot == row.snapshot
    assert pr.row("talent", emp, lists["talent2"]) is None


@pytest.mark.django_db
def test_dangling_list_id_shows_dash(
    emp: Employee, lists: dict[str, Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Production FKs stop a real dangling id from being stored, so the list miss is simulated:
    # the name lookup finds nothing for a row whose list id is set.
    row = FamilyRow.objects.create(employee=emp, relation_id=lists["relation"], given_name="Б")
    monkeypatch.setattr(pr, "_list_names", lambda model, ids: {})
    found = pr.row("family", emp, row.pk)
    assert found is not None
    assert found.values["relation"] == "—"
    assert "FamilyRelation" in caplog.text


@pytest.mark.django_db
def test_relative_row_resolves_branch_department_position(emp: Employee) -> None:
    RelativeRow.objects.create(
        employee=emp,
        given_name="Дорж",
        description="Эхнэр",
        branch=Branch.objects.create(name="Төв салбар"),
        department=Department.objects.create(name="Санхүү"),
        position=Position.objects.create(name="Нярав"),
    )
    [row] = pr.rows("relative", emp)
    assert row.values["given_name"] == "Дорж"
    assert row.values["branch"] == "Төв салбар"
    assert row.values["department"] == "Санхүү"
    assert row.values["position"] == "Нярав"


@pytest.mark.django_db
def test_relative_row_missing_branch_shows_dash(emp: Employee, monkeypatch: pytest.MonkeyPatch) -> None:
    branch = Branch.objects.create(name="Төв салбар")
    RelativeRow.objects.create(employee=emp, given_name="Дорж", description="Эхнэр", branch=branch)
    monkeypatch.setattr(pr, "_list_names", lambda model, ids: {})  # the branch id no longer names a branch
    [row] = pr.rows("relative", emp)
    assert row.values["branch"] == "—"
