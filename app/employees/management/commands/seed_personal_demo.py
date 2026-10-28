"""Fill one demo employee's whole personal tab: every field section, and several rows in every personal list.

    python app/manage.py seed_personal_demo E0002

DEBUG only. Rows go through the same row forms and services as the screens (validation, production tables,
activity log), so the result is what HR would have typed. Each run adds the rows again; run it once per demo DB.
"""

from typing import Any

from accounts.models import User
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.http import QueryDict
from macs.models import City, District, Employee, LanguageLevel

from employees import sections
from employees.forms import FORMS, EmployeeForm
from employees.management.commands.seed_demo import _list_entry
from employees.services import macs_writes, personal_writes, records

# Section values in form terms. "@Name" = the list entry with that name (created when missing); ("@Name", {...}) also
# gives the columns a new entry needs (e.g. a size's type).
SECTIONS: dict[str, dict[str, Any]] = {
    "identity": {
        "clan_name": "Хиад",
        "citizenship": "@Монгол",
        "birth_place_text": "Төв аймгийн төв",
    },
    "contact": {"private_phone": "99118822", "phone2": "88114455"},
    "education": {"education_level": "@Бакалавр", "academic_degree": "@Бакалавр"},
    "other": {
        "prior_service_years": "3",
        "prior_service_months": "6",
        "blood_type": "A",
        "blood_rh": "+",
        "military_service": "no",
        "social_origin": "@Ажилчин",
        "housing_condition": "@Орон сууц",
        "living_standard": "Дундаж",
        "car_ownership": "@Хувийн машинтай",
        "clothing_size": ("@M", {"size_type": "clothes"}),
        "shoe_size": ("@38", {"size_type": "shoes"}),
        "elected_position": "@Үйлдвэрчний эвлэлийн гишүүн",
    },
}

LANGUAGE_LEVELS = ("Анхан", "Дунд", "Сайн")

# Rows per personal list, in form terms (as the add pop-up posts them).
ROWS: dict[str, list[dict[str, Any]]] = {
    "family": [
        {
            "relation": "@Эцэг",
            "surname": "Бат",
            "given_name": "Цэрэндорж",
            "birth_date": "1958-04-12",
            "job": "Тэтгэвэрт",
            "phone": "99001122",
        },
        {
            "relation": "@Эх",
            "surname": "Дорж",
            "given_name": "Сарантуяа",
            "birth_date": "1961-09-03",
            "job": "Тэтгэвэрт",
            "phone": "99003344",
        },
        {
            "relation": "@Нөхөр",
            "surname": "Ганбат",
            "given_name": "Мөнхбат",
            "birth_date": "1984-02-20",
            "job": "Инженер",
            "phone": "88005566",
        },
        {
            "relation": "@Хүү",
            "surname": "Мөнхбат",
            "given_name": "Тэмүүлэн",
            "birth_date": "2012-06-01",
            "job": "Сурагч",
            "phone": "",
        },
    ],
    "relative": [
        {"given_name": "Оюунаа", "father_name": "Цэрэндорж", "description": "Эгч", "phone": "99007788"},
        {"given_name": "Батболд", "father_name": "Цэрэндорж", "description": "Дүү", "phone": "88009900"},
    ],
    "education": [
        {
            "org_name": "Улаанбаатарын 23-р сургууль",
            "start_year": "1993",
            "end_year": "2003",
            "edu_level": "@Бүрэн дунд",
            "country": "@Монгол",
        },
        {
            "org_name": "МУИС",
            "start_year": "2003",
            "end_year": "2007",
            "edu_level": "@Бакалавр",
            "grade": "@Бакалавр",
            "country": "@Монгол",
            "diplom_number": "Д-0071234",
        },
        {
            "org_name": "Сөүлийн үндэсний их сургууль",
            "start_year": "2012",
            "end_year": "2014",
            "edu_level": "@Магистр",
            "grade": "@Магистр",
            "country": "@Солонгос",
            "credit_score": "3.6",
        },
    ],
    "before_work": [
        {
            "worked_place": "Монгол Алт ХХК",
            "start_text": "2007 оны 9-р сар",
            "end_text": "2011 оны 12-р сар",
            "profession": "Хүний нөөцийн ажилтан",
            "shaltgaan": "Сургуульд суралцсан",
            "start_year": "2007",
            "end_year": "2011",
        },
        {
            "worked_place": "Хаан банк",
            "start_text": "2014 оны 9-р сар",
            "end_text": "2018 оны 8-р сар",
            "profession": "Хүний нөөцийн мэргэжилтэн",
            "shaltgaan": "Өөрийн хүсэлтээр",
            "start_year": "2014",
            "end_year": "2018",
        },
    ],
    "certificate": [
        {
            "cert_type": "@Хүний нөөц",
            "org_edu": "ХНМХ",
            "profession": "Хүний нөөц",
            "certify_number": "HR-2019-41",
            "certify_date": "2019-05-10",
            "certify_year": "2019",
        },
        {
            "cert_type": "@Хөдөлмөр хамгаалал",
            "org_edu": "ХХМТ",
            "profession": "ХАБЭА",
            "certify_number": "ХАБ-2022-07",
            "certify_date": "2022-03-15",
            "end_date": "2025-03-15",
            "certify_year": "2022",
        },
    ],
    "training": [
        {
            "start_year": "2023",
            "start_date": "2023-04-10",
            "training_center": "ХНМХ",
            "description": "Хөдөлмөрийн хуулийн шинэчлэл",
            "tr_type": "1",
            "days": "2",
            "amount": "180,000",
            "pay_type": "1",
        },
        {
            "start_year": "2024",
            "start_date": "2024-10-01",
            "training_center": "Мэдээллийн технологийн төв",
            "description": "Excel дунд шат",
            "tr_type": "1",
            "days": "5",
            "amount": "250,000",
            "pay_type": "3",
        },
        {
            "start_year": "2025",
            "start_date": "2025-06-16",
            "training_center": "Дотоод",
            "description": "Ажилтны сэтгэл ханамжийн судалгаа",
            "tr_type": "1",
            "days": "1",
            "amount": "0",
            "pay_type": "1",
        },
    ],
    "language": [
        {
            "language": "@Англи",
            "understand_lvl": "Сайн",
            "speaking_lvl": "Дунд",
            "reading_lvl": "Сайн",
            "writing_lvl": "Дунд",
            "description": "IELTS 6.5",
        },
        {
            "language": "@Солонгос",
            "understand_lvl": "Дунд",
            "speaking_lvl": "Дунд",
            "reading_lvl": "Анхан",
            "writing_lvl": "Анхан",
            "description": "Магистрт суралцахдаа",
        },
        {
            "language": "@Орос",
            "understand_lvl": "Анхан",
            "speaking_lvl": "Анхан",
            "reading_lvl": "Анхан",
            "writing_lvl": "",
            "description": "",
        },
    ],
    "talent": [
        {"talent": "@Дуу", "trained_year": "2001", "description": "Найрал дуу"},
        {"talent": "@Спорт", "trained_year": "2010", "description": "Волейбол"},
    ],
    "skill": [
        {
            "description": "Ажилтан сонгон шалгаруулах",
            "norm": "4",
            "department": "@Хүний нөөц",
            "sdate": "2026-01-05",
            "comment": "Улирал бүр",
        },
        {
            "description": "Ажлын байрны тодорхойлолт шинэчлэх",
            "norm": "12",
            "department": "@Хүний нөөц",
            "sdate": "2026-02-01",
            "comment": "Жилд",
        },
    ],
    "award": [
        {
            "give_org": "Компанийн удирдлага",
            "award_name": "Шилдэг ажилтан",
            "award_date": "2022-12-28",
            "description": "Жилийн шагнал",
        },
        {
            "give_org": "ХНМХ",
            "award_name": "Хүний нөөцийн шилдэг төсөл",
            "award_date": "2024-11-15",
            "description": "Дасан зохицох хөтөлбөр",
        },
    ],
    "discipline": [
        {
            "from_discipline": "Захирал",
            "discipline_type": "@Сануулга",
            "discipline_date": "2021-03-02",
            "description": "Тайлан хоцорсон",
            "discipline_sal_percent": "",
            "discipline_enddate": "2021-09-02",
        },
        {
            "from_discipline": "Захирал",
            "discipline_type": "@Цалин бууруулах",
            "discipline_date": "2023-07-10",
            "description": "Ажлын байрны журам зөрчсөн",
            "discipline_sal_percent": "10.00",
            "discipline_enddate": "2023-10-10",
        },
    ],
    "complaint": [
        {"cdate": "2025-02-14", "ctype": "1", "complaint_name": "1", "comment": "Хариу удаан өгсөн"},
        {"cdate": "2025-09-03", "ctype": "1", "complaint_name": "2", "comment": "Мэдээлэл дутуу"},
    ],
    "gift": [
        {
            "present_type": "@Шинэ жил",
            "pdate": "2024-12-27",
            "given_year": "2024",
            "childqty": "1",
            "child_age": "12",
            "price": "80,000",
            "given": "on",
            "note": "Хүүхдийн бэлэг",
        },
        {
            "present_type": "@Шинэ жил",
            "pdate": "2025-12-26",
            "given_year": "2025",
            "childqty": "1",
            "child_age": "13",
            "price": "90,000",
            "given": "on",
            "note": "Хүүхдийн бэлэг",
        },
    ],
    "material_help": [
        {
            "material_type": "@Эмчилгээний зардал",
            "amount": "500,000",
            "help_date": "2023-05-20",
            "description": "Мэс заслын зардал",
        },
        {
            "material_type": "@Гэр бүлийн гачигдал",
            "amount": "1,000,000",
            "help_date": "2025-01-11",
            "description": "Аавын оршуулга",
        },
    ],
    "body": [
        {
            "inserted_ognoo": "2025-02-10",
            "term_type": "Жил бүр",
            "end_date": "2026-02-10",
            "own_letter": "Эрүүл",
            "ear": "Хэвийн",
            "dotor": "Хэвийн",
            "medrel": "Хэвийн",
            "setgel_medrel": "Хэвийн",
            "mes_zasal": "Хэвийн",
            "nud": "Шил зүүдэг",
            "female": "Хэвийн",
            "rentgen": "Хэвийн",
            "skin": "Хэвийн",
            "conclusion": "Ажилд тохиромжтой",
            "sign": "Эмч Д.Сарантуяа",
        },
        {
            "inserted_ognoo": "2026-02-12",
            "term_type": "Жил бүр",
            "end_date": "2027-02-12",
            "own_letter": "Эрүүл",
            "ear": "Хэвийн",
            "dotor": "Хэвийн",
            "medrel": "Хэвийн",
            "setgel_medrel": "Хэвийн",
            "mes_zasal": "Хэвийн",
            "nud": "Шил зүүдэг",
            "female": "Хэвийн",
            "rentgen": "Хэвийн",
            "skin": "Хэвийн",
            "conclusion": "Ажилд тохиромжтой",
            "sign": "Эмч Б.Энхжаргал",
        },
    ],
    "driver": [
        {"driver_type": "@B ангилал", "number_driver": "ЖҮ-0045123", "inserted_ognoo": "2008-07-15"},
        {"driver_type": "@C ангилал", "number_driver": "ЖҮ-0045124", "inserted_ognoo": "2016-04-02"},
    ],
    "military": [
        {
            "army_rank": "Байхгүй",
            "mil_rank": "Бэлтгэл-2",
            "study_type": "Оюутны цэрэг",
            "sacking_date": "2006-06-01",
            "sacking_reason": "Сургалт дууссан",
        },
        {
            "army_rank": "Дэд ахлагч",
            "mil_rank": "Бэлтгэл-1",
            "study_type": "Сургалтын цуглаан",
            "sacking_date": "2015-09-01",
            "sacking_reason": "Цуглаан дууссан",
        },
    ],
    "army_rank": [
        {"rank": "Байлдагч", "rank_date": "2006-06-01", "addition_r": ""},
        {"rank": "Дэд ахлагч", "rank_date": "2015-09-01", "addition_r": "5.00"},
    ],
    "address": [
        {"district_name": "Хан-Уул", "street": "11-р хороо, Зайсан 42-12"},
        {"district_name": "Баянзүрх", "street": "3-р хороо, Энхтайваны өргөн чөлөө 15-28"},
    ],
    "contact": [
        {"contact_type": "@Гар утас", "name": "Мөнхбат", "relative": "Нөхөр", "value": "88005566"},
        {"contact_type": "@Гар утас", "name": "Оюунаа", "relative": "Эгч", "value": "99007788"},
        {"contact_type": "@Имэйл", "name": "Сарантуяа", "relative": "Эх", "value": "saraa61@mail.mn"},
    ],
}


class Command(BaseCommand):
    help = "Fill one demo employee's personal tab (every section, several rows per list). DEBUG only."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("code", help="Ажилтны код, жишээ нь E0002")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_personal_demo нь зөвхөн DEBUG горимд ажиллана.")
        employee = Employee.objects.filter(code=options["code"]).first()
        if employee is None:
            raise CommandError(f"{options['code']} кодтой ажилтан олдсонгүй.")
        by = User.objects.filter(username="seed").first() or User.objects.create_user("seed", first_name="Систем")
        with transaction.atomic():
            for level in LANGUAGE_LEVELS:  # the language rows' level boxes choose from this list
                _list_entry(LanguageLevel, level)
            for section, values in SECTIONS.items():
                self._save_section(employee, section, values, by)
            for kind, rows in ROWS.items():
                for values in rows:
                    self._add_row(employee, kind, values, by)
        total = sum(len(rows) for rows in ROWS.values())
        self.stdout.write(self.style.SUCCESS(f"{employee.code}: {len(SECTIONS)} хэсэг, {total} мөр нэмэгдлээ."))

    def _save_section(self, employee: Employee, section: str, values: dict[str, Any], by: User) -> None:
        """The same path as the section's «Хадгалах» (views.personal_section), without the stale check."""
        names = sections.SECTIONS[section]
        stored = Employee.objects.get(pk=employee.pk)
        posted = _resolved(EmployeeForm(employee=stored), values)
        if section == "identity":
            city, district = _place("Төв", "Зуунмод")
            posted |= {"birth_city": str(city.pk), "birth_district": str(district.pk)}
        post = QueryDict(mutable=True)
        post.update(posted)
        form = EmployeeForm(sections.section_data(EmployeeForm(employee=stored), post, names), employee=stored)
        sections.only_section_required(form, names)
        if not form.is_valid():
            raise CommandError(f"{section}: {form.errors.as_text()}")
        columns, ext = form.values()
        records.update_employee(stored, {**columns, **ext}, by)
        place = form.birth_place()
        if place is not None:
            records.set_birth_place(stored, *place, by)

    def _add_row(self, employee: Employee, kind: str, values: dict[str, Any], by: User) -> None:
        """The same path as the add pop-up (views.personal_add)."""
        form_cls = FORMS[kind]
        data = _resolved(form_cls(adding=True), values)
        if kind == "address":
            city, district = _place("Улаанбаатар", data.pop("district_name"))
            data |= {"city": str(city.pk), "district": str(district.pk)}
        form = form_cls(data, adding=True)
        if not form.is_valid():
            raise CommandError(f"{kind}: {form.errors.as_text()}")
        columns, ext = form.values()
        personal_writes.add(kind, employee, columns, ext, by)


def _place(city_name: str, district_name: str) -> tuple[City, District]:
    """A city and one of its districts by name, created when missing (the district under that city)."""
    city = _list_entry(City, city_name)
    district = District.objects.filter(name=district_name, city=city).first()
    return city, district or macs_writes.save_list_entry(District, {"name": district_name, "city": city})


def _resolved(form: Any, values: dict[str, Any]) -> dict[str, Any]:
    """`values` with each "@Name" replaced by the pk of that entry in the field's list (created when missing)."""
    out = dict(values)
    for name, value in values.items():
        entry, extra = value if isinstance(value, tuple) else (value, {})
        if isinstance(entry, str) and entry.startswith("@"):
            out[name] = str(_list_entry(form.fields[name].queryset.model, entry[1:], **extra).pk)
    return out
