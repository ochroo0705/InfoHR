from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection

from macs.models import (
    AcademicDegree,
    ArmyRankRow,
    AwardRow,
    BeforeWorkRow,
    BodyRow,
    Branch,
    CertificateRow,
    ComplaintRow,
    Country,
    Department,
    DisciplineRow,
    DisciplineType,
    DriverRow,
    DriverType,
    EducationLevel,
    Employee,
    ForeignLanguage,
    LanguageLevel,
    LanguageRow,
    MaterialHelpRow,
    MaterialHelpType,
    MilitaryRow,
    Position,
    ProfessionType,
    QualificationRow,
    QualificationType,
    RelativeRow,
    SkillWorkRow,
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
def test_relative_row_roundtrip(employee: Employee) -> None:
    branch = Branch.objects.create(name="Төв салбар")
    department = Department.objects.create(name="Санхүү")
    position = Position.objects.create(name="Нярав")
    row = RelativeRow.objects.create(
        employee=employee,
        given_name="Дорж",
        father_name="Бат",
        job="Багш",
        phone="99112233",
        description="Эхнэр",
        branch=branch,
        department=department,
        position=position,
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.given_name == "Дорж"
    assert row.father_name == "Бат"
    assert row.job == "Багш"
    assert row.phone == "99112233"
    assert row.description == "Эхнэр"
    assert row.branch_id == branch.pk
    assert row.department_id == department.pk
    assert row.position_id == position.pk


@pytest.mark.django_db
def test_before_work_row_roundtrip(employee: Employee) -> None:
    row = BeforeWorkRow.objects.create(
        employee=employee,
        worked_place="Анод ХХК",
        start_text="2019 оны 3-р сар",
        end_text="2021 оны 6-р сар",
        profession="Нягтлан",
        shaltgaan="Өөрийн хүсэлт",
        start_year=2019,
        end_year=2021,
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.worked_place == "Анод ХХК"
    assert row.start_text == "2019 оны 3-р сар"
    assert row.end_text == "2021 оны 6-р сар"
    assert row.profession == "Нягтлан"
    assert row.shaltgaan == "Өөрийн хүсэлт"
    assert (row.start_year, row.end_year) == (2019, 2021)


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


@pytest.mark.django_db
def test_skill_row_roundtrip(employee: Employee) -> None:
    department = Department.objects.create(name="Санхүү")
    row = SkillWorkRow.objects.create(
        employee=employee,
        description="Excel ашиглах",
        norm=Decimal("1.50"),
        department=department,
        sdate=date(2026, 1, 15),
        comment="Туршилт",
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.description == "Excel ашиглах"
    assert row.norm == Decimal("1.50")
    assert row.department_id == department.pk
    assert row.sdate == date(2026, 1, 15)
    assert row.comment == "Туршилт"


@pytest.mark.django_db
def test_material_help_row_roundtrip(employee: Employee) -> None:
    material_type = MaterialHelpType.objects.create(name="Эмчилгээ")
    row = MaterialHelpRow.objects.create(
        employee=employee,
        amount=Decimal("1250000.00"),
        help_date=date(2026, 1, 15),
        material_type=material_type,
        description="Эмнэлгийн зардал",
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.amount == Decimal("1250000.00")
    assert row.help_date == date(2026, 1, 15)
    assert row.material_type_id == material_type.pk
    assert row.description == "Эмнэлгийн зардал"


@pytest.mark.django_db
def test_award_row_roundtrip(employee: Employee) -> None:
    row = AwardRow.objects.create(
        employee=employee,
        give_org="Засгийн газар",
        award_name="Гавьяа медаль",
        award_date=date(2026, 3, 8),
        description="Жилийн үр дүн",
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.give_org == "Засгийн газар"
    assert row.award_name == "Гавьяа медаль"
    assert row.award_date == date(2026, 3, 8)
    assert row.description == "Жилийн үр дүн"


@pytest.mark.django_db
def test_award_empty_description_saves_empty_string(employee: Employee) -> None:
    row = AwardRow.objects.create(employee=employee, award_name="Гавьяа медаль", description="")
    row.refresh_from_db()
    assert row.description == ""


@pytest.mark.django_db
def test_discipline_row_roundtrip(employee: Employee) -> None:
    discipline_type = DisciplineType.objects.create(name="Анхааруулга")
    row = DisciplineRow.objects.create(
        employee=employee,
        from_discipline="Санхүүгийн алба",
        discipline_type=discipline_type,
        discipline_date=date(2026, 2, 1),
        description="Хоцорсон",
        discipline_sal_percent=Decimal("12.50"),
        discipline_enddate=date(2026, 5, 1),
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.from_discipline == "Санхүүгийн алба"
    assert row.discipline_type_id == discipline_type.pk
    assert row.discipline_date == date(2026, 2, 1)
    assert row.description == "Хоцорсон"
    assert row.discipline_sal_percent == Decimal("12.50")
    assert row.discipline_enddate == date(2026, 5, 1)


def test_complaint_row_roundtrip(employee: Employee) -> None:
    row = ComplaintRow.objects.create(
        employee=employee,
        cdate=date(2026, 2, 1),
        ctype=2,
        complaint_name=1,
        comment="Хүлээн авалт",
    )
    row.refresh_from_db()
    assert row.pk is not None
    assert row.employee_id == employee.pk
    assert row.cdate == date(2026, 2, 1)
    assert row.ctype == 2
    assert row.complaint_name == 1
    assert row.comment == "Хүлээн авалт"


def test_body_row_roundtrip(employee: Employee) -> None:
    row = BodyRow.objects.create(
        employee=employee,
        inserted_ognoo=date(2026, 2, 1),
        term_type="Жилийн",
        end_date=date(2027, 2, 1),
        own_letter="Тийм",
        ear="Хэвийн",
        dotor="Хэвийн",
        medrel="Хэвийн",
        setgel_medrel="Хэвийн",
        mes_zasal="Хэвийн",
        nud="Хэвийн",
        female="Хэвийн",
        rentgen="Хэвийн",
        skin="Хэвийн",
        conclusion="Ажилд тохиромжтой",
        sign="Б.Болд",
    )
    row.refresh_from_db()
    assert row.employee_id == employee.pk
    assert row.inserted_ognoo == date(2026, 2, 1)
    assert row.term_type == "Жилийн"
    assert row.end_date == date(2027, 2, 1)
    assert row.own_letter == "Тийм"
    assert row.skin == "Хэвийн"
    assert row.conclusion == "Ажилд тохиромжтой"
    assert row.sign == "Б.Болд"
    with connection.cursor() as cur:
        cur.execute('select "finally" from body where body_id = %s', [row.pk])
        assert cur.fetchone() == ("Ажилд тохиромжтой",)


def test_military_row_roundtrip(employee: Employee) -> None:
    row = MilitaryRow.objects.create(
        employee=employee,
        army_rank="Ахлагч",
        mil_rank="Бэлтгэл-1",
        study_type="2 жил",
        sacking_date=date(2026, 3, 1),
        sacking_reason="Хугацаа дууссан",
    )
    row.refresh_from_db()
    assert row.employee_id == employee.pk
    assert row.army_rank == "Ахлагч"
    assert row.mil_rank == "Бэлтгэл-1"
    assert row.study_type == "2 жил"
    assert row.sacking_date == date(2026, 3, 1)
    assert row.sacking_reason == "Хугацаа дууссан"


def test_army_rank_row_roundtrip(employee: Employee) -> None:
    row = ArmyRankRow.objects.create(
        employee=employee,
        rank_date=date(2025, 6, 1),
        rank="Ахлагч",
        addition_r=Decimal("15.00"),
    )
    row.refresh_from_db()
    assert row.employee_id == employee.pk
    assert row.rank_date == date(2025, 6, 1)
    assert row.rank == "Ахлагч"
    assert row.addition_r == Decimal("15.00")


def test_driver_row_roundtrip(employee: Employee) -> None:
    driver_type = DriverType.objects.create(name="B ангилал")
    row = DriverRow.objects.create(
        employee=employee,
        driver_type=driver_type,
        number_driver="1234567",
        inserted_ognoo=date(2026, 3, 1),
    )
    row.refresh_from_db()
    assert row.employee_id == employee.pk
    assert row.driver_type_id == driver_type.pk
    assert row.number_driver == "1234567"
    assert row.inserted_ognoo == date(2026, 3, 1)
