from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from macs.models import (
    AcademicDegree,
    CertificateRow,
    Country,
    EducationLevel,
    Employee,
    ForeignLanguage,
    LanguageLevel,
    LanguageRow,
    ProfessionType,
    QualificationRow,
    QualificationType,
    SpecEduType,
    TrainingRow,
)


@pytest.fixture
def employee(db: None) -> Employee:
    return Employee.objects.create(given_name="Т", family_name="Б")


@pytest.mark.django_db
def test_qualification_row_roundtrip(employee: Employee) -> None:
    qtype = QualificationType.objects.create(name="Мэргэшил")
    ptype = ProfessionType.objects.create(name="Инженер")
    edu = EducationLevel.objects.create(name="Бакалавр")
    degree = AcademicDegree.objects.create(name="Магистр")
    country = Country.objects.create(name="Монгол", code="MN")
    row = QualificationRow.objects.create(
        employee=employee,
        qualification_type=qtype,
        profession_type=ptype,
        org_name="Монгол Их Сургууль",
        diplom_number="D-123",
        start_date=date(2010, 9, 1),
        ending_date=date(2014, 6, 30),
        credit_score=Decimal("3.75"),
        country="25",
        edu_level=edu,
        grade=degree,
        start_year=2010,
        end_year=2014,
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.qualification_type_id == qtype.pk
    assert row.profession_type_id == ptype.pk
    assert row.org_name == "Монгол Их Сургууль"
    assert row.diplom_number == "D-123"
    assert row.start_date == date(2010, 9, 1)
    assert row.ending_date == date(2014, 6, 30)
    assert row.credit_score == Decimal("3.75")
    assert row.country == "25"
    assert row.edu_level_id == edu.pk
    assert row.grade_id == degree.pk
    assert row.start_year == 2010
    assert row.end_year == 2014
    assert country.pk is not None


@pytest.mark.django_db
def test_certificate_row_roundtrip(employee: Employee) -> None:
    cert_type = SpecEduType.objects.create(name="Сертификат")
    row = CertificateRow.objects.create(
        employee=employee,
        cert_type=cert_type,
        org_edu="Аюушийн дээд сургууль",
        certify_number="C-0001",
        certify_date=date(2015, 5, 10),
        profession="Нягтлан",
        end_date=date(2015, 12, 1),
        spec_profession="Аудитор",
        certify_year=2015,
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.cert_type_id == cert_type.pk
    assert row.org_edu == "Аюушийн дээд сургууль"
    assert row.certify_number == "C-0001"
    assert row.certify_date == date(2015, 5, 10)
    assert row.profession == "Нягтлан"
    assert row.end_date == date(2015, 12, 1)
    assert row.spec_profession == "Аудитор"
    assert row.certify_year == 2015


@pytest.mark.django_db
def test_training_row_roundtrip(employee: Employee) -> None:
    row = TrainingRow.objects.create(
        employee=employee,
        tr_type=2,
        description="Аюулгүй ажиллагаа",
        start_date=date(2020, 3, 2),
        days=5,
        amount=Decimal("1500000.50"),
        pay_type=5,
        training_center="Гадаад сургалтын төв",
        start_year=2020,
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.tr_type == 2
    assert row.description == "Аюулгүй ажиллагаа"
    assert row.start_date == date(2020, 3, 2)
    assert row.days == 5
    assert row.amount == Decimal("1500000.50")
    assert row.pay_type == 5
    assert row.training_center == "Гадаад сургалтын төв"
    assert row.start_year == 2020


@pytest.mark.django_db
def test_language_row_roundtrip(employee: Employee) -> None:
    language = ForeignLanguage.objects.create(name="Англи")
    row = LanguageRow.objects.create(
        employee=employee,
        language=language,
        understand_lvl="Дунд",
        speaking_lvl="Сайн",
        reading_lvl="Маш сайн",
        writing_lvl="Дунд",
        description="Бичгийн шалгалт",
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.language_id == language.pk
    assert row.understand_lvl == "Дунд"
    assert row.speaking_lvl == "Сайн"
    assert row.reading_lvl == "Маш сайн"
    assert row.writing_lvl == "Дунд"
    assert row.description == "Бичгийн шалгалт"


@pytest.mark.django_db
def test_lookup_lists_have_names() -> None:
    lists: list[tuple[Any, str]] = [
        (QualificationType, "Мэргэшил"),
        (ProfessionType, "Инженер"),
        (SpecEduType, "Сертификат"),
        (ForeignLanguage, "Англи"),
        (LanguageLevel, "Сайн"),
    ]
    for model, name in lists:
        obj = model.objects.create(name=name)
        assert str(obj) == name
