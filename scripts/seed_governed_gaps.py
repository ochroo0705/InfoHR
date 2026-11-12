"""Fills the gaps left by seed_governed_extra.py on the Firebird test copy (DEBUG only; run once):

 - branches for every employee (a few branch rows are created),
 - a job and salary history for the employees that came with the MACS copy and had none (their first event
   starts the history from the MACS row), followed by transfers, promotions and salary changes with orders,
 - some people on long leave (some returned) and some who left, with a leaving reason and order.

    python scripts/seed_governed_gaps.py      (with DB_ENGINE=firebird and FIREBIRD_NAME set)
"""

import os
import random
import sys
from datetime import timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_DEBUG", "true")

import django  # noqa: E402

django.setup()

from accounts.models import User  # noqa: E402
from django.conf import settings  # noqa: E402
from django.utils import timezone  # noqa: E402
from macs.models import Branch, Department, FiredReason, Position  # noqa: E402

from employees.models import Employee, EventType, LeaveKind  # noqa: E402
from employees.services import events, macs_writes  # noqa: E402

OUT = lambda *a: print(*a, flush=True)  # noqa: E731
rng = random.Random(77)
today = timezone.localdate()
admin = User.objects.get(username="admin")
number = [9500]


def attempt(label: str, tally: dict[str, int], errors: dict[str, int], emp: Employee, **kw) -> bool:
    number[0] += 1
    try:
        events.record(
            emp, by=admin, note="Демо", order_number=f"Б/{number[0]}", order_date=kw["effective"],
            order_summary="Демо тушаал", order_issued_by="Захирал", **kw,
        )
    except Exception as exc:  # noqa: BLE001 - a seeder: count and go on
        key = f"{label}: {type(exc).__name__} {str(exc)[:80]}"
        errors[key] = errors.get(key, 0) + 1
        tally["bad"] += 1
        return False
    tally[label] = tally.get(label, 0) + 1
    return True


def main() -> None:
    if not settings.DEBUG:
        raise SystemExit("DEBUG only.")
    branches()
    depts, positions = list(Department.objects.all()), list(Position.objects.all())
    tally: dict[str, int] = {"bad": 0}
    errors: dict[str, int] = {}

    # 1. legacy employees: first event starts the HR history from the MACS row
    legacy = [e for e in Employee.objects.all() if not e.job_records.exists()]
    OUT("employees without HR history:", len(legacy))
    for emp in legacy:
        day = today - timedelta(days=rng.randint(60, 400))
        ok = attempt(
            "start", tally, errors, emp, type=EventType.SALARY_CHANGE.value, effective=day, changes={},
            salary=Decimal(rng.randint(20, 80) * 100000), reason="Цалингийн тохиргоо",
            start_department=rng.choice(depts), start_position=rng.choice(positions),
        )
        if not ok:
            continue
        for step in rng.choice([[], [EventType.TRANSFER], [EventType.PROMOTION], [EventType.PROMOTION, EventType.SALARY_CHANGE]]):
            day += timedelta(days=rng.randint(30, 120))
            if day >= today:
                break
            changes: dict = {}
            salary = None
            if step == EventType.TRANSFER:
                changes = {"department": rng.choice(depts)}
            elif step == EventType.PROMOTION:
                changes, salary = {"position": rng.choice(positions)}, Decimal(rng.randint(25, 95) * 100000)
            else:
                salary = Decimal(rng.randint(25, 95) * 100000)
            attempt(step.value, tally, errors, emp, type=step.value, effective=day, changes=changes,
                    salary=salary, reason="Демо өөрчлөлт")

    # 2. long leave, some returned, and leavers
    active = [e for e in Employee.objects.all() if e.job_records.exists()]
    rng.shuffle(active)
    reasons = list(FiredReason.objects.all()) or [macs_writes.save_list_entry(FiredReason, {"name": "Өөрийн хүсэлтээр"})]
    for emp in active[:7]:
        day = today - timedelta(days=rng.randint(3, 25))
        kind = rng.choice(list(LeaveKind)).value
        if attempt("leave_start", tally, errors, emp, type=EventType.LEAVE_START.value, effective=day, changes={},
                   salary=None, reason=kind, expected_return=today + timedelta(days=rng.randint(30, 300))):
            if rng.random() < 0.4:
                attempt("leave_return", tally, errors, emp, type=EventType.LEAVE_RETURN.value,
                        effective=day + timedelta(days=1), changes={}, salary=None, reason="Буцаж ирсэн")
    for emp in active[7:17]:
        day = today - timedelta(days=rng.randint(3, 40))
        attempt("terminated", tally, errors, emp, type=EventType.TERMINATION.value, effective=day, changes={},
                salary=None, reason="Өөрийн хүсэлтээр", fired_reason=rng.choice(reasons),
                offboarding_override="Демо өгөгдөл")
    OUT("tally:", tally)
    for key, count in sorted(errors.items(), key=lambda kv: -kv[1])[:8]:
        OUT("  ", count, key)
    os._exit(0)


def branches() -> None:
    names = ["Төв салбар", "Дархан салбар", "Эрдэнэт салбар", "Хөвсгөл салбар", "Говийн салбар", "Орхон салбар"]
    rows = [Branch.objects.filter(name=n).first() or Branch.objects.create(name=n, status=1) for n in names]
    made = 0
    for emp in Employee.objects.all():
        if emp.branch_id is None:
            macs_writes.update_employee_columns(emp, {"branch": rng.choice(rows)})
            made += 1
    OUT("branches assigned:", made)


if __name__ == "__main__":
    main()
