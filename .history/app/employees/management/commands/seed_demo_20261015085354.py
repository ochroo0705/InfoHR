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
from django.db import transaction
from django.utils import timezone
from employees.models import Department, Education, Employee, FamilyMember, Position
from employees.services import history, records
from leave.models import Holiday, LeaveType
from leave.services import calendar as leave_calendar
from leave.services import records as leave_records

DEMO_PASSWORD = "Demo-InfoHR-2026"  # noqa: S105 — local demo database only (DEBUG-gated)

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

FAMILY = {
    "Энхбаяр": [("Отгонбаяр", "Эхнэр", 1980), ("Тэмүжин", "Хүү", 2008), ("Анужин", "Охин", 2012)],
    "Оюунчимэг": [("Батзориг", "Нөхөр", 1984), ("Ананд", "Хүү", 2014)],
    "Болд": [("Дорждэрэм", "Эцэг", 1962), ("Цэцэг", "Эх", 1965)],
    "Номин": [("Алтангэрэл", "Эцэг", 1966)],
}
EDUCATION = {
    "Энхбаяр": [("МУИС", "Магистр", "Бизнесийн удирдлага", 2005)],
    "Оюунчимэг": [("СЭЗИС", "Бакалавр", "Хүний нөөцийн менежмент", 2008)],
    "Сарантуяа": [("СЭЗИС", "Бакалавр", "Нягтлан бодох бүртгэл", 2004)],
    "Болд": [("ШУТИС", "Бакалавр", "Програм хангамж", 2014)],
    "Тэмүүлэн": [("МУИС", "Бакалавр", "Мэдээллийн технологи", 2021)],
    "Номин": [("Санхүү эдийн засгийн дээд сургууль", "Бакалавр", "Санхүү", 2016)],
}


class Command(BaseCommand):
    help = "Fill an empty (demo) database with a Mongolian demo company. DEBUG only."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_demo нь зөвхөн DEBUG горимд ажиллана.")
        if Employee.objects.exists():
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

        depts = {name: Department.objects.create(name=name) for name in DEPARTMENTS}
        Department.objects.create(name=DEPARTMENT_INACTIVE, active=False)
        positions = {name: Position.objects.create(name=name) for name in POSITIONS}

        people: dict[str, Employee] = {}
        for p in PEOPLE:
            start = p["start"] or today + timedelta(days=14)  # one upcoming hire
            emp = history.hire(
                Employee(
                    family_name=p["family"],
                    given_name=p["given"],
                    clan_name=p["clan"],
                    register_no=p["reg"],
                    birth_date=p["birth"],
                    gender=p["gender"],
                    work_phone=p["phone"],
                    email=p["email"],
                    address=p["address"],
                    first_hire_date=start,
                    marital_status="married",
                    emergency_name="Гэр бүлийн гишүүн",
                    emergency_phone="99000000",
                    prior_service_years=2,
                    work_schedule="Даваа–Баасан 09:00–18:00",
                ),
                start=start,
                job={
                    "position": positions[p["pos"]],
                    "department": depts[p["dept"]],
                    "employee_type": p["type"],
                    "contract_type": p["contract"],
                    "status": "active",
                    "contract_no": f"ХГ-{start.year}/{len(people) + 1:03d}",
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
                    "bank": "Хаан банк" if len(people) % 2 else "Голомт банк",
                    "account_no": f"50{emp.pk:02d}{p['birth']:%y%m%d}12",
                    "social_insurance_no": f"НД{p['birth']:%Y}{emp.pk:04d}",
                    "health_insurance_no": f"ЭМ{p['birth']:%Y}{emp.pk:04d}",
                    "insured_category": "Хөдөлмөрийн гэрээгээр ажиллагч",
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
                emp.user = user
                emp.save(update_fields=["user"])
            for name, relation, year in FAMILY.get(p["given"], []):
                FamilyMember.objects.create(employee=emp, name=name, relation=relation, birth_year=year)
            for school, degree, field, year in EDUCATION.get(p["given"], []):
                Education.objects.create(employee=emp, school=school, degree=degree, field=field, graduation_year=year)

        director = people["Энхбаяр"].user or system
        hr = people["Оюунчимэг"].user or system
        accountant = people["Сарантуяа"].user or system
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

        self._seed_leave(people, today, hr)

    def _seed_leave(self, people: dict[str, Employee], today: date, by: User) -> None:
        """Holidays and a few leaves, all on weekdays relative to today and inside one leave year."""
        leave_calendar.prefill_year(today.year)
        leave_calendar.prefill_year(today.year + 1)
        # Tsagaan Sar (lunar new year): demo only, dates approximate.
        for day, name in [(17, "Цагаан сар"), (18, "Цагаан сар"), (19, "Цагаан сар")]:
            Holiday.objects.get_or_create(date=date(today.year, 2, day), defaults={"name": name})
        types = {t.code: t for t in LeaveType.objects.all()}
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
