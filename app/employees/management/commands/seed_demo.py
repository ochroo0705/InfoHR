"""Fill an EMPTY database with a Mongolian demo company (InfoSystems, ~10 people).

Demo only: refuses to run when DEBUG is off or when employees already exist, because
history and the activity log can never be deleted through the app. Use it on the
separate demo database: `python scripts/demo.py reset` (see that script).

Demo logins (one per role) all use DEMO_PASSWORD below.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from leave.models import LeaveSettings
from leave.services import calendar as leave_calendar
from leave.services import ledger as leave_ledger
from leave.services import records as leave_records
from leave.services import writes as leave_writes
from lists.models import DEATH, MONGOLIA, MeaningfulEntry
from macs.models import (
    AddressRow,
    Bank,
    City,
    ContactType,
    Country,
    District,
    EducRow,
    EduType,
    FamilyRelation,
    FamilyRow,
    FiredReason,
    InsuredCategory,
    LeaveAssign,
    LeaveTypeRow,
    MaritalStatus,
    PresentRow,
    PresentType,
    Shift,
    TalentKind,
)

from employees.models import Employee, EmployeeExt, ensure_ext
from employees.services import history, macs_writes, records

DEMO_PASSWORD = "Demo-InfoHR-2026"  # noqa: S105 — local demo database only (DEBUG-gated)

FIRED_REASONS = [
    "Өөрийн хүсэлтээр",
    "Харилцан тохиролцсон",
    "Гэрээний хугацаа дууссан",
    "Ажлаас халсан",
    "Тэтгэвэрт гарсан",
    "Нас барсан",
]
DEPARTMENTS = ["Удирдлага", "Санхүү", "Хүний нөөц", "Програм хангамж", "Борлуулалт", "Техникийн дэмжлэг"]
POSITIONS = [
    "Гүйцэтгэх захирал",
    "Ерөнхий нягтлан бодогч",
    "Нягтлан бодогч",
    "Хүний нөөцийн менежер",
    "Ахлах програм хөгжүүлэгч",
    "Програм хөгжүүлэгч",
    "Борлуулалтын менежер",
    "Техникийн дэмжлэгийн инженер",
    "Оффисын менежер",
    "Жолооч",
]
DEPARTMENT_INACTIVE = "Түр төсөл"  # shows how inactive list items behave
# Same five leave types as the leave app's 0002_seed migration: code, name, is_paid, uses_annual_balance, order.
LEAVE_TYPES = [
    ("annual", "Ээлжийн амралт", True, True, 1),
    ("sick", "Өвчний чөлөө", True, False, 2),
    ("unpaid", "Цалингүй чөлөө", False, False, 3),
    ("personal", "Цалинтай хувийн чөлөө", True, False, 4),
    ("other", "Бусад", False, False, 5),
]
TSAGAAN_SAR = [(17, "Цагаан сар"), (18, "Цагаан сар"), (19, "Цагаан сар")]  # demo only, dates approximate

# (login, role group, family name, given name, clan, register no, birth, gender, phone, email,
#  start, position, department, type, contract, salary, address)
PEOPLE: list[dict[str, Any]] = [
    dict(
        login="director",
        role="Admin",
        family="Батбаярын",
        given="Энхбаяр",
        clan="Боржигон",
        reg="УБ78052314",
        birth=date(1978, 5, 23),
        gender="male",
        phone="99112233",
        email="enkhbayar@infosystems.mn",
        start=date(2015, 3, 2),
        pos="Гүйцэтгэх захирал",
        dept="Удирдлага",
        type="full_time",
        contract="open_ended",
        salary="6500000",
        address="СБД, 1-р хороо, Энхтайваны өргөн чөлөө 15",
    ),
    dict(
        login="hr",
        role="HR",
        family="Цэрэндоржийн",
        given="Оюунчимэг",
        clan="Хиад",
        reg="УК86110725",
        birth=date(1986, 11, 7),
        gender="female",
        phone="88103344",
        email="oyunchimeg@infosystems.mn",
        start=date(2018, 9, 1),
        pos="Хүний нөөцийн менежер",
        dept="Хүний нөөц",
        type="full_time",
        contract="open_ended",
        salary="3200000",
        address="ХУД, 11-р хороо, Зайсан 42-12",
    ),
    dict(
        login="accountant",
        role="Accountant",
        family="Ганбатын",
        given="Сарантуяа",
        clan="",
        reg="ЧД82030218",
        birth=date(1982, 3, 2),
        gender="female",
        phone="95116677",
        email="sarantuya@infosystems.mn",
        start=date(2016, 1, 11),
        pos="Ерөнхий нягтлан бодогч",
        dept="Санхүү",
        type="full_time",
        contract="open_ended",
        salary="4200000",
        address="БЗД, 26-р хороо, 13-р хороолол 5-34",
    ),
    dict(
        login="bold",
        role=None,
        family="Дорждэрэмийн",
        given="Болд",
        clan="Тайчууд",
        reg="УЕ92041509",
        birth=date(1992, 4, 15),
        gender="male",
        phone="99887766",
        email="bold@infosystems.mn",
        start=date(2019, 6, 3),
        pos="Ахлах програм хөгжүүлэгч",
        dept="Програм хангамж",
        type="full_time",
        contract="open_ended",
        salary="4800000",
        address="БГД, 4-р хороо, 3-р хороолол 22-8",
    ),
    dict(
        login=None,
        role=None,
        family="Мөнхбатын",
        given="Тэмүүлэн",
        clan="",
        reg="УП98120333",
        birth=date(1998, 12, 3),
        gender="male",
        phone="80201122",
        email="temuulen@infosystems.mn",
        start=date(2023, 2, 1),
        pos="Програм хөгжүүлэгч",
        dept="Програм хангамж",
        type="full_time",
        contract="fixed_term",
        salary="2800000",
        address="СХД, 20-р хороо, 1-р хороолол 7-45",
    ),
    dict(
        login=None,
        role=None,
        family="Нямдоржийн",
        given="Ариунаа",
        clan="Олхонуд",
        reg="ЧА90081716",
        birth=date(1990, 8, 17),
        gender="female",
        phone="99045588",
        email="ariunaa@infosystems.mn",
        start=date(2017, 4, 17),
        pos="Борлуулалтын менежер",
        dept="Борлуулалт",
        type="full_time",
        contract="open_ended",
        salary="3500000",
        address="ЧД, 5-р хороо, Их тойруу 33",
    ),
    dict(
        login=None,
        role=None,
        family="Пүрэвсүрэнгийн",
        given="Ганзориг",
        clan="",
        reg="УЗ95060201",
        birth=date(1995, 6, 2),
        gender="male",
        phone="86117799",
        email="ganzorig@infosystems.mn",
        start=date(2021, 10, 4),
        pos="Техникийн дэмжлэгийн инженер",
        dept="Техникийн дэмжлэг",
        type="full_time",
        contract="open_ended",
        salary="2600000",
        address="БЗД, 8-р хороо, Нарны зам 61",
    ),
    dict(
        login=None,
        role=None,
        family="Алтангэрэлийн",
        given="Номин",
        clan="",
        reg="ЧЕ94022729",
        birth=date(1994, 2, 27),
        gender="female",
        phone="99551234",
        email="nomin@infosystems.mn",
        start=date(2020, 3, 16),
        pos="Нягтлан бодогч",
        dept="Санхүү",
        type="full_time",
        contract="open_ended",
        salary="2400000",
        address="ХУД, 3-р хороо, Яармаг 12-90",
    ),
    dict(
        login=None,
        role=None,
        family="Баасанжавын",
        given="Мөнх-Эрдэнэ",
        clan="",
        reg="УН88092004",
        birth=date(1988, 9, 20),
        gender="male",
        phone="91234455",
        email="",
        start=date(2022, 5, 9),
        pos="Жолооч",
        dept="Удирдлага",
        type="part_time",
        contract="fixed_term",
        salary="1100000",
        address="СХД, 32-р хороо, Толгойт 118",
    ),
    dict(
        login=None,
        role=None,
        family="Энхтайваны",
        given="Хулан",
        clan="",
        reg="УБ01231108",
        birth=date(2001, 3, 11),
        gender="female",
        phone="85006677",
        email="khulan@infosystems.mn",
        start=None,
        pos="Оффисын менежер",
        dept="Удирдлага",
        type="full_time",
        contract="fixed_term",
        salary=None,
        address="БГД, 16-р хороо, 120 мянгат 3-14",
    ),
]

# Personal lists: the street-prefix code in each address (the old program's "СБД, ...") -> district of Ulaanbaatar.
ADDRESS_DISTRICT = {
    "СБД": "Сүхбаатар",
    "БЗД": "Баянзүрх",
    "БГД": "Баянгол",
    "ХУД": "Хан-Уул",
    "ЧД": "Чингэлтэй",
    "СХД": "Сонгинохайрхан",
}
# Emergency contact per employee (given name): name, relative, phone.
EMERGENCY = {
    "Энхбаяр": ("Отгонбаяр", "Эхнэр", "99001122"),
    "Оюунчимэг": ("Батзориг", "Нөхөр", "88001133"),
    "Сарантуяа": ("Ганбат", "Нөхөр", "95002244"),
    "Болд": ("Цэцэг", "Эх", "99003355"),
    "Тэмүүлэн": ("Мөнхбат", "Эцэг", "80004466"),
    "Ариунаа": ("Нямдорж", "Эцэг", "99005577"),
    "Ганзориг": ("Пүрэвсүрэн", "Эцэг", "86006688"),
    "Номин": ("Алтангэрэл", "Эцэг", "99007799"),
    "Мөнх-Эрдэнэ": ("Баасанжав", "Ах", "91008800"),
    "Хулан": ("Энхтайван", "Эцэг", "85009911"),
}
FAMILY_RELATIONS = {"Эцэг": "dad", "Эх": "mother", "Эхнэр": "spouse", "Нөхөр": "spouse", "Ах": "other"}  # fm_type codes
EDUCATION_TYPES = ["Бакалавр", "Магистр"]
TALENT_KINDS = ["Хөгжим", "Спорт"]
PRESENT_TYPES = ["Мөнгөн бэлэг", "Ном"]
CONTACT_TYPE = "Гар утас"


def _list_entry(model: Any, name: str, **extra: Any) -> Any:
    """Return the list row with this name, creating it through macs_writes when missing."""
    found = model.objects.filter(name=name).first()
    return found or macs_writes.save_list_entry(model, {"name": name, **extra})


class Command(BaseCommand):
    help = "Fill an empty (demo) database with a Mongolian demo company. DEBUG only."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_demo нь зөвхөн DEBUG горимд ажиллана.")
        if EmployeeExt.objects.exists():
            raise CommandError("Ажилтан аль хэдийн байна. seed_demo-г зөвхөн хоосон (demo) өгөгдлийн санд ажиллуулна.")
        with transaction.atomic():
            self._seed()
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo өгөгдөл үүслээ: {Employee.objects.count()} ажилтан. "
                "Нэвтрэх: admin / director / hr / accountant / bold (нууц үг: seed_demo.py дахь DEMO_PASSWORD)."
            )
        )

    def _seed(self) -> None:
        today = timezone.localdate()
        system = User.objects.create_user("seed", first_name="Систем")
        system.set_unusable_password()
        system.is_active = False
        system.save()
        # Superuser for the Django admin and every switch; same demo password as the role logins.
        User.objects.create_superuser("admin", password=DEMO_PASSWORD, first_name="Админ")

        # List entries go through the production writer (macs_writes), never straight into the ORM.
        marital = _list_entry(MaritalStatus, "Гэрлэсэн")
        shift = _list_entry(Shift, "09:00-18:00")
        mongolia = _list_entry(Country, "Монгол")
        _list_entry(Country, "Япон")
        _list_entry(Country, "Солонгос")
        MeaningfulEntry.objects.update_or_create(key=MONGOLIA, defaults={"value": mongolia.pk})
        reasons = {name: _list_entry(FiredReason, name) for name in FIRED_REASONS}
        MeaningfulEntry.objects.update_or_create(key=DEATH, defaults={"value": reasons["Нас барсан"].pk})
        ulaanbaatar = _list_entry(City, "Улаанбаатар")
        districts = {name: _list_entry(District, name, city=ulaanbaatar) for name in ADDRESS_DISTRICT.values()}
        darkhan = _list_entry(City, "Дархан")
        darkhan_district = _list_entry(District, "Дархан-Уул", city=darkhan)
        relations = {name: _list_entry(FamilyRelation, name, fm_type=code) for name, code in FAMILY_RELATIONS.items()}
        edu_types = {name: _list_entry(EduType, name) for name in EDUCATION_TYPES}
        talent_kinds = {name: _list_entry(TalentKind, name) for name in TALENT_KINDS}
        present_types = {name: _list_entry(PresentType, name) for name in PRESENT_TYPES}
        contact_type = _list_entry(ContactType, CONTACT_TYPE)

        depts = {name: macs_writes.save_department(name) for name in DEPARTMENTS}
        inactive = macs_writes.save_department(DEPARTMENT_INACTIVE)
        inactive.ext.active = False
        inactive.ext.save(update_fields=["active"])
        positions = {name: macs_writes.save_position(name) for name in POSITIONS}

        people: dict[str, Employee] = {}
        for p in PEOPLE:
            start = p["start"] or today + timedelta(days=14)  # one upcoming hire
            emp = history.hire(
                {
                    "family_name": p["family"],
                    "given_name": p["given"],
                    "clan_name": p["clan"],
                    "register_no": p["reg"],
                    "birth_date": p["birth"],
                    "gender": "M" if p["gender"] == "male" else "F",
                    "work_phone": p["phone"],
                    "email": p["email"],
                    "first_hire_date": start,
                    "marital_status": marital,
                    "prior_service_years": 2,
                    "work_schedule": shift,
                    "work_conditions": 1,
                },
                {},
                start=start,
                address={
                    "city_id": ulaanbaatar.pk,
                    "district_id": districts[ADDRESS_DISTRICT[p["address"].split(",", 1)[0]]].pk,
                    "street": p["address"].split(", ", 1)[1],
                },
                contact={
                    "contact_type_id": contact_type.pk,
                    "name": EMERGENCY[p["given"]][0],
                    "relative": EMERGENCY[p["given"]][1],
                    "value": EMERGENCY[p["given"]][2],
                },
                job={
                    "position": positions[p["pos"]],
                    "department": depts[p["dept"]],
                    "employee_type": p["type"],
                    "contract_type": p["contract"],
                    "status": "active",
                    "contract_no": f"ХГ{start.year % 100:02d}-{len(people) + 1:03d}",  # max 10 characters
                    "contract_start": start,
                    "contract_end": start + timedelta(days=365) if p["contract"] == "fixed_term" else None,
                },
                salary=Decimal(p["salary"]) if p["salary"] else None,
                by=system,
            )
            people[p["given"]] = emp
            records.update_salary_insurance(
                emp,
                {
                    "bank": _list_entry(Bank, "Хаан банк" if len(people) % 2 else "Голомт банк"),
                    "account_no": f"50{emp.pk:02d}{p['birth']:%y%m%d}12",
                    "social_insurance_no": f"НД{p['birth']:%Y}{emp.pk:04d}",
                    "health_insurance_no": f"ЭМ{p['birth']:%Y}{emp.pk:04d}",
                    "insured_category": _list_entry(InsuredCategory, "Хөдөлмөрийн гэрээгээр ажиллагч"),
                    "taxpayer_no": p["reg"],
                },
                system,
            )
            if p["login"]:
                user = User.objects.create_user(
                    p["login"], password=DEMO_PASSWORD, first_name=p["given"], last_name=p["family"]
                )
                if p["role"]:
                    user.groups.add(Group.objects.get(name=p["role"]))
                ext = ensure_ext(emp)
                ext.user = user
                ext.save(update_fields=["user"])

        director = ensure_ext(people["Энхбаяр"]).user or system
        hr = ensure_ext(people["Оюунчимэг"]).user or system
        accountant = ensure_ext(people["Сарантуяа"]).user or system
        boss = people["Энхбаяр"]
        for name in people:
            if name != "Энхбаяр":
                job = people[name].job_records.get()
                history.correct_job(job, changes={"manager": boss}, reason="Шууд удирдлагыг тохируулсан", by=hr)

        # History for the screens. Events (transfer, raise, termination) arrive in sub-project B;
        # until then they are recorded as dated changes with a note.
        history.change_job(
            people["Тэмүүлэн"],
            effective=date(2025, 1, 1),
            changes={"department": depts["Техникийн дэмжлэг"]},
            change_type="correction",
            note="Түр хугацаагаар техникийн дэмжлэг рүү шилжүүлсэн",
            by=hr,
        )
        history.change_job(
            people["Тэмүүлэн"],
            effective=date(2025, 7, 1),
            changes={"department": depts["Програм хангамж"]},
            change_type="correction",
            note="Програм хангамжийн баг руу буцаасан",
            by=hr,
        )
        history.change_salary(
            people["Болд"],
            effective=date(2026, 1, 1),
            amount=Decimal("5300000"),
            change_type="correction",
            note="Жилийн цалингийн нэмэгдэл",
            by=accountant,
        )
        history.change_salary(
            people["Номин"],
            effective=date(2025, 7, 1),
            amount=Decimal("2650000"),
            change_type="correction",
            note="Туршилтын үр дүнгээр нэмсэн",
            by=accountant,
        )
        history.change_job(
            people["Ариунаа"],
            effective=date(2026, 8, 15),
            changes={"status": "long_leave"},
            change_type="correction",
            note="Жирэмсний болон амаржсаны амралт",
            by=hr,
        )
        history.change_job(
            people["Мөнх-Эрдэнэ"],
            effective=date(2026, 5, 1),
            changes={"status": "left"},
            change_type="correction",
            note="Өөрийн хүсэлтээр ажлаас чөлөөлөгдсөн",
            by=hr,
        )

        records.add_note(people["Тэмүүлэн"], text="Дипломын нотариатаар баталгаажуулсан хуулбар дутуу.", by=hr)
        records.add_note(people["Болд"], text="AWS гэрчилгээний сургалтад хамрагдах хүсэлт гаргасан.", by=hr)
        records.add_note(people["Хулан"], text="Ажилд орохоос өмнө эрүүл мэндийн үзлэгийн хуудас авчрах.", by=hr)
        records.update_employee(people["Ганзориг"], {"private_phone": "95443322"}, hr)
        records.update_employee(people["Энхбаяр"], {"work_phone": "99112200"}, director)

        # Old-style personal rows: written straight into the tables, the way the old program left them
        # (no HR ext row, no personal_writes). Written through macs_writes; the talent has no ORM model, so raw SQL.
        macs_writes.save_list_entry(
            FamilyRow,
            {
                "employee": people["Болд"],
                "relation": relations["Эцэг"],
                "given_name": "Дорждэрэм",
                "birth_date": date(1962, 1, 1),
            },
        )
        macs_writes.save_list_entry(
            EducRow,
            {
                "employee": people["Номин"],
                "edu_type": edu_types["Бакалавр"],
                "start_year": 2016,
                "startdate": date(2016, 9, 1),
            },
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO emp_talents (emp_ident, talent_ident, trained_year, description) VALUES (%s, %s, %s, %s)",
                [people["Болд"].pk, talent_kinds["Хөгжим"].pk, 2015, "Гитар"],
            )
        macs_writes.save_list_entry(
            PresentRow,
            {
                "employee": people["Тэмүүлэн"],
                "childqty": 1,
                "price": 50000,
                "given_year": 2025,
                "pdate": date(2025, 3, 8),
                "present_type": present_types["Ном"],
                "child_age": 3,
                "given": 1,
            },
        )
        # An address whose district belongs to another city (Darkhan), as the old program could leave it.
        macs_writes.save_list_entry(
            AddressRow,
            {
                "employee": people["Номин"],
                "street": "Дархан хот, 3-р хороо",
                "city": ulaanbaatar,
                "district": darkhan_district,
            },
        )

        self._seed_leave(people, today, hr)

    def _seed_leave(self, people: dict[str, Employee], today: date, by: User) -> None:
        """Leave types, holidays and leaves: production rows, plus a few old-style rows written without an ext row."""
        types: dict[str, LeaveTypeRow] = {}
        for code, name, paid, annual, order in LEAVE_TYPES:
            ext = {"is_paid": paid, "uses_annual_balance": annual, "is_active": True, "order": order}
            types[code] = leave_writes.save_leave_type(name, ext)
        leave_calendar.prefill_year(today.year)
        leave_calendar.prefill_year(today.year + 1)
        holidays = leave_calendar.holiday_names(today.year)
        holidays.update({date(today.year, 2, day): name for day, name in TSAGAAN_SAR})
        leave_writes.set_holiday_dates(today.year, holidays)

        # Old-style rows: no ext row, the way the old program wrote them (status NULL / adays NULL, rejected).
        year_start, year_end = date(today.year, 1, 1), date(today.year, 12, 31)
        leave_writes.write_old_style_grant(
            people["Болд"], types["annual"], year_start, year_end, 15, "Хуучин системээс"
        )
        leave_writes.write_old_style_assign(
            people["Болд"],
            types["annual"],
            today - timedelta(days=60),
            today - timedelta(days=60),
            status=None,
            adays=None,
            comment="Хуучин системд бүртгэсэн",
        )
        leave_writes.write_old_style_assign(
            people["Номин"],
            types["sick"],
            today - timedelta(days=20),
            today - timedelta(days=18),
            status=LeaveAssign.REJECTED,
            adays=3,
            comment="Хуучин системд татгалзсан",
        )

        # Demo only: the auto annual grant is on, so every employee gets the law's grant for the current year.
        leave_settings = LeaveSettings.get()
        leave_settings.auto_annual_grant = True
        leave_settings.save(update_fields=["auto_annual_grant"])
        for person in people.values():
            leave_ledger.ensure_grants(person, today)

        monday_back = today - timedelta(days=30)
        monday_back -= timedelta(days=monday_back.weekday())
        monday_next = today + timedelta(days=30)
        monday_next += timedelta(days=(7 - monday_next.weekday()) % 7)
        plan = [
            ("Болд", "annual", monday_back, 4),  # past, 5 working days
            ("Номин", "sick", monday_back + timedelta(days=7), 1),
            ("Ганзориг", "annual", monday_next, 4),  # upcoming
        ]
        for name, code, start, length in plan:
            draft = leave_records.Draft(people[name], types[code], start, start + timedelta(days=length))
            if leave_records.check(draft, today).errors:  # e.g. a holiday week or a leave-year boundary
                continue
            leave_records.record(draft, by, today)
