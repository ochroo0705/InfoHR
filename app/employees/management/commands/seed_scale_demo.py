"""Add many generated employees to a demo database that `seed_demo` already filled.

For measuring how the screens behave at 300 people (scoping log RK-008, D-043). DEBUG only.
Everything goes through the same services as the screens (hire, leave record), so the
numbers include the real per-person cost. Usage:

    DEMO_DB=info_hr_demo_scale python scripts/demo.py reset
    DJANGO_DB_NAME=info_hr_demo_scale DJANGO_DEBUG=true python app/manage.py seed_scale_demo 300
"""

import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from leave.services import ledger as leave_ledger
from leave.services import records as leave_records
from macs.models import City, ContactType, District, LeaveTypeRow, MaritalStatus, Shift

from employees.models import Employee, EmployeeExt
from employees.services import history, macs_writes

FAMILY = ["Батын", "Доржийн", "Лхагвын", "Нямын", "Пүрэвийн", "Ганбатын", "Сүхийн", "Цэрэнгийн", "Эрдэнийн", "Баярын"]
GIVEN_M = ["Бат-Эрдэнэ", "Ганбаатар", "Энхтүвшин", "Түвшинбаяр", "Доржсүрэн", "Мөнхбат", "Чинбат", "Наранбат"]
GIVEN_F = ["Уянга", "Сарнай", "Оюунаа", "Цэцэгмаа", "Анужин", "Билгүүн", "Насанцэцэг", "Урнаа"]
LETTERS = "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЭЮЯ"
EXTRA_DEPARTMENTS = [f"Хэлтэс {n}" for n in range(1, 13)]
EXTRA_POSITIONS = [f"Мэргэжилтэн {n}" for n in range(1, 31)]


class Command(BaseCommand):
    help = "Add N generated employees to a seeded demo database. DEBUG only."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("count", type=int, help="total employees wanted (including the demo ones)")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("DEBUG горимд л ажиллана.")
        if not EmployeeExt.objects.exists():
            raise CommandError("Эхлээд seed_demo ажиллуулна (scripts/demo.py reset).")
        with transaction.atomic():
            made = self._seed(options["count"])
        self.stdout.write(self.style.SUCCESS(f"{made} ажилтан нэмлээ, нийт {Employee.objects.count()}."))

    def _seed(self, total: int) -> int:
        rng = random.Random(42)  # noqa: S311 - demo data, not security
        today = timezone.localdate()
        hr = User.objects.get(username="hr")
        depts = [macs_writes.save_department(n) for n in EXTRA_DEPARTMENTS]
        positions = [macs_writes.save_position(n) for n in EXTRA_POSITIONS]
        marital = MaritalStatus.objects.first()
        shift = Shift.objects.first()
        city = City.objects.first()
        district = District.objects.first()
        contact_type = ContactType.objects.first()
        heads: dict[int, Employee] = {}
        made = 0
        have = Employee.objects.count()
        for i in range(max(0, total - have)):
            dept = depts[i % len(depts)]
            male = rng.random() < 0.5
            birth = date(rng.randint(1965, 2003), rng.randint(1, 12), rng.randint(1, 28))
            start = date(rng.randint(2008, 2026), rng.randint(1, 12), rng.randint(1, 28))
            if start > today:
                start = today - timedelta(days=rng.randint(1, 300))
            reg = (
                f"{rng.choice(LETTERS)}{rng.choice(LETTERS)}{birth:%y}"
                f"{rng.randint(1, 12):02d}{rng.randint(10, 28)}{rng.randint(0, 99):02d}"
            )
            fixed = rng.random() < 0.2
            emp = history.hire(
                {
                    "family_name": rng.choice(FAMILY),
                    "given_name": rng.choice(GIVEN_M if male else GIVEN_F),
                    "clan_name": "",
                    "register_no": reg,
                    "birth_date": birth,
                    "gender": "M" if male else "F",
                    "work_phone": f"9{rng.randint(1000000, 9999999)}",
                    "email": f"staff{i}@example.mn",
                    "first_hire_date": start,
                    "marital_status": marital,
                    "prior_service_years": rng.randint(0, 8),
                    "work_schedule": shift,
                    "work_conditions": 1,
                },
                {},
                start=start,
                address={"city_id": city.pk, "district_id": district.pk, "street": f"{rng.randint(1, 99)}-р хороо"}
                if city and district
                else None,
                contact={"contact_type_id": contact_type.pk, "name": "Ах", "relative": "Ах", "value": "99000000"}
                if contact_type
                else None,
                job={
                    "position": rng.choice(positions),
                    "department": dept,
                    "employee_type": "full_time",
                    "contract_type": "fixed_term" if fixed else "open_ended",
                    "status": "active",
                    "contract_no": f"ХГ{i:05d}"[:10],
                    "contract_start": start,
                    "contract_end": start + timedelta(days=rng.randint(30, 700)) if fixed else None,
                },
                salary=Decimal(rng.randint(15, 60) * 100000),
                by=hr,
            )
            head = heads.setdefault(dept.pk, emp)
            if head.pk != emp.pk:
                job = emp.job_records.get()
                history.correct_job(job, changes={"manager": head}, reason="Шууд удирдлага", by=hr)
            made += 1

        # Leave: grants for everyone, then about a third of people take some leave around today.
        annual = LeaveTypeRow.objects.filter(name="Ээлжийн амралт").first()
        if annual:
            for emp in Employee.objects.all():
                leave_ledger.ensure_grants(emp, today)
            for emp in rng.sample(list(Employee.objects.all()), k=Employee.objects.count() // 3):
                begin = today + timedelta(days=rng.randint(-40, 40))
                begin += timedelta(days=(7 - begin.weekday()) % 7)
                draft = leave_records.Draft(emp, annual, begin, begin + timedelta(days=rng.randint(2, 9)))
                if leave_records.check(draft, today).errors:
                    continue
                try:
                    leave_records.record(draft, hr, today)
                except leave_records.LeaveError:  # e.g. balance too low: needs a reason, skip it
                    continue
        return made
