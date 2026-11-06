"""Demo data for the help assistant: fictional Mongolian staff, departments and positions for the staff-table questions.

Run only through the `seed_assistant_demo` command (and `scripts/demo.py assistant-data`), which checks
`assistant_data_allowed` against the real settings first. `build` does not look at the database name or DEBUG itself,
so the tests can call it on the test database.

Every person it creates has a register number that starts with DEMO_REGISTER_PREFIX; that marks them as demo people.
Departments and positions are found by name and created only when missing, so the seed's rows are reused.
There is no removal: the activity log is append-only. To start over, run `scripts/demo.py reset`, then
`scripts/demo.py assistant-data`.
"""

import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from accounts.models import User
from django.db import transaction
from django.db.models import QuerySet
from employees.models import Employee, JobRecord
from employees.services import history, macs_writes
from macs.models import Department, Position

DEMO_REGISTER_PREFIX = "ДМ99"  # two letters and eight digits, like a real register number; demo people only
DEMO_ACTOR = "assistant_demo"  # the inactive login the demo rows are written by, when the database has none
DEPARTMENTS = [
    "Санхүү",
    "IT",
    "Худалдан авалт (Төв)",
    "Худалдан авалт (Баруун)",
    "Маркетинг",
    "Логистик",
    "Үйлдвэрлэл",
    "Захиргаа",
]
POSITIONS = [
    "Програмист",
    "Төслийн менежер",
    "Борлуулалтын менежер",
    "Борлуулалтын мэргэжилтэн",
    "Маркетингийн мэргэжилтэн",
    "Логистикийн ажилтан",
    "Кассчин",
    "Агуулахын ажилтан",
]
# Patronymics (family names) with several endings, and given names of both genders.
FAMILY = [
    "Батбаярын",
    "Доржийн",
    "Лхагвын",
    "Ганболдын",
    "Сүхээгийн",
    "Цогтын",
    "Мөнх-Оргилын",
    "Баатарын",
    "Гантөмөрийн",
    "Энхжаргалын",
    "Түмэнийн",
    "Чулуунбаатарын",
]
GIVEN_M = ["Саруул", "Түвшин", "Ганболд", "Хишигбаяр", "Занаа", "Ундрах", "Пүрэвдорж", "Мөнх-Оргил", "Азбаяр"]
GIVEN_F = [
    "Мөнхзул",
    "Баярмаа",
    "Доржпалам",
    "Оюун-Эрдэнэ",
    "Нарангэрэл",
    "Азжаргал",
    "Солонго",
    "Цэцэгмаа",
    "Болормаа",
]
# Employee type codes (reports.filters.EMPTYPES) for the 48 people, in order. Type 9 comes from a probation end.
TYPE_PLAN = [1] * 26 + [2] * 3 + [3] * 3 + [4] * 2 + [5] * 8 + [6] * 2 + [9] * 4


def assistant_data_allowed(db_name: str, debug: bool, engine: str) -> bool:
    """True only on PostgreSQL, with DEBUG on, in a database whose name starts with info_hr_demo."""
    return engine == "postgresql" and debug and db_name.startswith("info_hr_demo")


def demo_people() -> QuerySet[Employee]:
    """The demo people: every employee whose register number starts with DEMO_REGISTER_PREFIX."""
    return Employee.objects.filter(register_no__startswith=DEMO_REGISTER_PREFIX)


def _department(name: str) -> tuple[Department, bool]:
    found = Department.objects.filter(name=name).first()
    if found is not None:
        return found, False
    return macs_writes.save_department(name), True


def _position(name: str) -> tuple[Position, bool]:
    found = Position.objects.filter(name=name).first()
    if found is not None:
        return found, False
    return macs_writes.save_position(name), True


def _actor() -> User:
    user, _ = User.objects.get_or_create(username=DEMO_ACTOR, defaults={"first_name": "Демо", "is_active": False})
    return user


def _start(index: int, day: date) -> date:
    """A hire date from 2015 to 2026 (2026 only up to October), spread over the people, never after `day`."""
    year = 2015 + index % 12
    month = min(1 + (index * 5) % 12, 10) if year == 2026 else 1 + (index * 5) % 12
    start = date(year, month, 1 + (index * 11) % 28)
    return min(start, day - timedelta(days=30))


def _contract_end(slot: int, day: date) -> date:
    """Contract end of the type-5 person in `slot`: the first four end this month (not before `day`), the rest next
    month."""
    next_month_first = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    month_end = next_month_first - timedelta(days=1)
    if slot < 4:
        return max(day, month_end - timedelta(days=slot % 3))
    return next_month_first + timedelta(days=slot - 4)


def _person(index: int, code: int, slot: int, day: date, by: User) -> None:
    male = index % 2 == 0
    start = _start(index, day)
    dept, _ = _department(DEPARTMENTS[index % len(DEPARTMENTS)])
    position, _ = _position(POSITIONS[index % len(POSITIONS)])
    job: dict[str, Any] = {
        "position": position,
        "department": dept,
        "employee_type": "full_time",
        "contract_type": "open_ended",
        "status": "active",
        "emptype": code,
    }
    if code == 5:
        job.update(
            employee_type="contract",
            contract_type="fixed_term",
            contract_start=start,
            contract_end=_contract_end(slot, day),
        )
    if code == 3:
        job["status"] = "left"  # the job is over; the type is 3 («Ажиллаж байсан»)
    ext: dict[str, Any] = {"probation_end": start + timedelta(days=90)} if code == 9 else {}
    # Codes HR does not model (2 external reserve, 4 applicant) cannot be hired as such: sync_current has no flags for
    # them. They are hired as type 1 and then set the way the old program left them (see below).
    unmodelled = code in macs_writes.UNMODELLED_NOT_WORKING
    if unmodelled:
        job["emptype"] = 1
    emp = history.hire(
        {
            "family_name": FAMILY[index % len(FAMILY)],
            "given_name": (GIVEN_M if male else GIVEN_F)[index // 2 % 9],
            "clan_name": "",
            "register_no": f"{DEMO_REGISTER_PREFIX}{index + 1:06d}",
            "birth_date": date(1962 + (index * 7) % 38, 1 + index % 12, 1 + (index * 3) % 28),
            "gender": "M" if male else "F",
            "work_phone": f"9911{index:04d}",
            "first_hire_date": start,
            "work_conditions": 1,
        },
        ext,
        start=start,
        job=job,
        salary=None if index % 9 == 4 else Decimal(1_200_000 + (index % 12) * 150_000),
        by=by,
    )
    if unmodelled:
        # The old rows' way: the job and the employee row hold the code; no service copies flags for it.
        JobRecord.objects.filter(employee=emp).update(emptype=code)
        macs_writes.update_employee_columns(emp, {"emptype": code})
        return
    # The Employee row carries the same type and flags as the job (macs_writes.EMPTYPE_FLAGS).
    flags = macs_writes.EMPTYPE_FLAGS[code]
    macs_writes.update_employee_columns(
        emp, {"emptype": code, "status": flags[0], "contract_flag": flags[1], "wagetest": flags[2]}
    )


@transaction.atomic
def build(day: date) -> dict[str, int]:
    """Creates the demo people, departments and positions that are missing. Running it again adds nothing.
    Returns the counts created: {"people", "departments", "positions"}."""
    by = _actor()
    departments = sum(1 for name in DEPARTMENTS if _department(name)[1])
    positions = sum(1 for name in POSITIONS if _position(name)[1])
    people = 0
    for index, code in enumerate(TYPE_PLAN):
        if Employee.objects.filter(register_no=f"{DEMO_REGISTER_PREFIX}{index + 1:06d}").exists():
            continue
        slot = sum(1 for other in TYPE_PLAN[:index] if other == 5)  # the contract people's order, for their end dates
        _person(index, code, slot, day, by)
        people += 1
    return {"people": people, "departments": departments, "positions": positions}


# The larger, uneven roster (`build_large`): department sizes that differ a lot, hiring that grew year by year and a few
# contracts, probations and leavers, so charts of it have a shape. Same register prefix, numbers from LARGE_FROM up.
LARGE_FROM = 100
LARGE_COUNT = 150
LARGE_SEED = 20261106
# department -> (people, [positions], base monthly salary)
LARGE_PLAN: dict[str, tuple[int, list[str], int]] = {
    "Худалдан авалт (Төв)": (30, ["Борлуулалтын менежер", "Борлуулалтын мэргэжилтэн", "Кассчин"], 1_300_000),
    "Үйлдвэрлэл": (28, ["Үйлдвэрийн ажилтан", "Операторч", "Механик"], 1_450_000),
    "Логистик": (20, ["Логистикийн ажилтан", "Жолооч", "Агуулахын ажилтан"], 1_350_000),
    "IT": (18, ["Програмист", "Системийн администратор", "Төслийн менежер"], 3_000_000),
    "Санхүү": (12, ["Нягтлан бодогч", "Санхүүгийн шинжээч"], 2_200_000),
    "Маркетинг": (12, ["Маркетингийн мэргэжилтэн", "Дизайнер"], 1_900_000),
    "Худалдан авалт (Баруун)": (10, ["Борлуулалтын мэргэжилтэн", "Кассчин"], 1_250_000),
    "Захиргаа": (8, ["Захиргааны ажилтан", "Нарийн бичгийн дарга"], 1_500_000),
    "Хүний нөөц": (5, ["Хүний нөөцийн мэргэжилтэн"], 2_000_000),
    "Аюулгүй байдал": (4, ["Хамгаалагч", "Хяналтын ажилтан"], 1_200_000),
    "Хууль зүй": (3, ["Хуульч"], 2_800_000),
}
# Hiring grew: later years get more people (2015 ... 2026).
LARGE_YEAR_WEIGHTS = [1, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9, 6]
# Employee type codes and how often: mostly regular staff, then fixed-term contracts, probation and leavers.
LARGE_TYPES = [(1, 82), (5, 10), (9, 5), (3, 3)]


def _large_roster(day: date) -> list[dict[str, Any]]:
    """The plan for every person of the large roster, the same on every run (a fixed seed), in a shuffled order."""
    rng = random.Random(LARGE_SEED)  # noqa: S311 demo data, a fixed seed on purpose
    slots = [name for name, (count, _, _) in LARGE_PLAN.items() for _ in range(count)]
    rng.shuffle(slots)
    people: list[dict[str, Any]] = []
    for number, dept in enumerate(slots):
        _, positions, base = LARGE_PLAN[dept]
        code = rng.choices([c for c, _ in LARGE_TYPES], weights=[w for _, w in LARGE_TYPES])[0]
        year = rng.choices(range(2015, 2027), weights=LARGE_YEAR_WEIGHTS)[0]
        start = date(year, rng.randint(1, 12), rng.randint(1, 28))
        if code == 9:
            start = day - timedelta(days=rng.randint(10, 80))  # still on probation
        else:
            start = min(start, day - timedelta(days=30))
        male = rng.random() < 0.5
        people.append(
            {
                "index": LARGE_FROM + number,
                "dept": dept,
                "position": rng.choice(positions),
                "code": code,
                "start": start,
                "male": male,
                "family": rng.choice(FAMILY),
                "given": rng.choice(GIVEN_M if male else GIVEN_F),
                "birth": date(rng.randint(1966, 2003), rng.randint(1, 12), rng.randint(1, 28)),
                "salary": None if rng.random() < 0.08 else Decimal(base + rng.randint(-2, 8) * 100_000),
                "contract_end": day + timedelta(days=rng.randint(10, 400)),
            }
        )
    return people


def _large_person(spec: dict[str, Any], by: User) -> None:
    code = spec["code"]
    dept, _ = _department(spec["dept"])
    position, _ = _position(spec["position"])
    start: date = spec["start"]
    job: dict[str, Any] = {
        "position": position,
        "department": dept,
        "employee_type": "full_time",
        "contract_type": "open_ended",
        "status": "active",
        "emptype": code,
    }
    if code == 5:
        job.update(
            employee_type="contract",
            contract_type="fixed_term",
            contract_start=start,
            contract_end=spec["contract_end"],
        )
    if code == 3:
        job["status"] = "left"
    ext: dict[str, Any] = {"probation_end": start + timedelta(days=90)} if code == 9 else {}
    emp = history.hire(
        {
            "family_name": spec["family"],
            "given_name": spec["given"],
            "clan_name": "",
            "register_no": f"{DEMO_REGISTER_PREFIX}{spec['index'] + 1:06d}",
            "birth_date": spec["birth"],
            "gender": "M" if spec["male"] else "F",
            "work_phone": f"9911{spec['index']:04d}",
            "first_hire_date": start,
            "work_conditions": 1,
        },
        ext,
        start=start,
        job=job,
        salary=spec["salary"],
        by=by,
    )
    flags = macs_writes.EMPTYPE_FLAGS[code]
    macs_writes.update_employee_columns(
        emp, {"emptype": code, "status": flags[0], "contract_flag": flags[1], "wagetest": flags[2]}
    )


@transaction.atomic
def build_large(day: date) -> dict[str, int]:
    """Adds the larger, uneven roster (about LARGE_COUNT people) on top of `build`. Running it again adds nothing.
    Returns the counts created: {"people", "departments", "positions"}."""
    by = _actor()
    before_departments = Department.objects.count()
    before_positions = Position.objects.count()
    people = 0
    for spec in _large_roster(day):
        if Employee.objects.filter(register_no=f"{DEMO_REGISTER_PREFIX}{spec['index'] + 1:06d}").exists():
            continue
        _large_person(spec, by)
        people += 1
    return {
        "people": people,
        "departments": Department.objects.count() - before_departments,
        "positions": Position.objects.count() - before_positions,
    }
