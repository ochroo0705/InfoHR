"""Extra demo data for testing the governed SQL views: more leave, orders, salary changes, children, loans, logins.

Run AFTER `seed_demo` and `seed_scale_demo` on the Firebird test copy (DEBUG only). Idempotent per run only in the
sense that it adds more each time; run it once. From the repo root, with DB_ENGINE and FIREBIRD_NAME set:

    python scripts/seed_governed_extra.py

Everything goes through the same services as the screens where one exists (leave, job and salary events, orders,
logins). Children and loans are written directly because the app has no service for them (loans are read-only here).
"""

import os
import random
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_DEBUG", "true")

import django  # noqa: E402

django.setup()

from accounts.models import User  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.utils import timezone  # noqa: E402
from leave.services import ledger as leave_ledger  # noqa: E402
from leave.services import records as leave_records  # noqa: E402
from macs.models import Department, FamilyRelation, FamilyRow, LeaveTypeRow, LoanRefRow, LoanRow, Position  # noqa: E402

from employees.models import Employee, EventType  # noqa: E402
from employees.services import events, logins, macs_writes  # noqa: E402

OUT = lambda *a: print(*a, flush=True)  # noqa: E731
rng = random.Random(2026)
today = timezone.localdate()

LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "i",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "ө": "u", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ү": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya", "-": "",
}


def latin(text: str) -> str:
    return "".join(LATIN.get(ch, ch) for ch in text.lower())


def main() -> None:
    if not settings.DEBUG:
        raise SystemExit("DEBUG only.")
    hr = User.objects.get(username="hr")
    everyone = list(Employee.objects.all())
    OUT("employees:", len(everyone))
    if FamilyRow.objects.count() < 100:  # a first run may already have added them
        leave_children(everyone)
    loans(everyone)
    job_and_salary_events(everyone, hr)
    leave_records_extra(everyone, hr)
    make_logins(everyone, hr)
    OUT("done")
    os._exit(0)


def leave_children(everyone: list[Employee]) -> None:
    def rel(name: str, code: str) -> FamilyRelation:
        found = FamilyRelation.objects.filter(fm_type=code).first()
        return found or macs_writes.save_list_entry(FamilyRelation, {"name": name, "fm_type": code})

    son, daughter, spouse = rel("Хүү", "son"), rel("Охин", "daughter"), rel("Эхнэр/нөхөр", "spouse")
    names_m = ["Төгөлдөр", "Билгүүн", "Анхбаяр", "Тэмүүжин", "Эрхэмбаяр", "Золбоо"]
    names_f = ["Номин", "Сарангэрэл", "Заяа", "Хулан", "Одончимэг", "Мишээл"]
    made = 0
    for emp in rng.sample(everyone, k=int(len(everyone) * 0.6)):
        for _ in range(rng.choice([1, 1, 2, 2, 3, 4])):
            boy = rng.random() < 0.5
            birth = date(rng.randint(2005, 2025), rng.randint(1, 12), rng.randint(1, 28))
            FamilyRow.objects.create(
                employee=emp,
                relation=son if boy else daughter,
                given_name=rng.choice(names_m if boy else names_f),
                surname=emp.given_name[:30],
                birth_date=birth,
            )
            made += 1
        if rng.random() < 0.5:
            FamilyRow.objects.create(
                employee=emp, relation=spouse, given_name=rng.choice(names_f + names_m), surname=emp.family_name[:30]
            )
    OUT("family rows added:", made)


def loans(everyone: list[Employee]) -> None:
    reasons = ["Орон сууцны зээл", "Эмчилгээний зээл", "Боловсролын зээл", "Яаралтай хэрэгцээ", "Тээврийн хэрэгсэл"]
    from django.db import connection

    for r in reasons:  # REF_TYPE is a required column the model does not map, so insert with plain SQL
        if not LoanRefRow.objects.filter(description=r).exists():
            connection.cursor().execute("INSERT INTO LOAN_REFS (DESCRIPTION, REF_TYPE) VALUES (%s, 1)", [r])
    refs = list(LoanRefRow.objects.filter(description__in=reasons))
    made = 0
    for emp in rng.sample(everyone, k=int(len(everyone) * 0.3)):
        for _ in range(rng.choice([1, 1, 2])):
            months = rng.choice([6, 12, 24, 36])
            amount = Decimal(rng.randint(5, 60) * 100000)
            start = today - timedelta(days=rng.randint(20, 600))
            LoanRow.objects.create(
                employee=emp,
                get_date=start,
                end_date=start + timedelta(days=30 * months),
                amount=amount,
                pay_permonth=(amount / months).quantize(Decimal("1")),
                loan_ref=rng.choice(refs),
            )
            made += 1
    OUT("loans added:", made)


def job_and_salary_events(everyone: list[Employee], hr: User) -> None:
    depts = list(Department.objects.all())
    positions = list(Position.objects.all())
    ok = bad = 0
    errors: dict[str, int] = {}
    with_history = [e for e in everyone if e.job_records.exists()]
    OUT("employees with job history:", len(with_history))
    number = 9000
    for emp in with_history:
        day = max(today - timedelta(days=rng.randint(200, 700)), emp.first_hire_date or today)
        steps = rng.choice([[], [EventType.SALARY_CHANGE], [EventType.TRANSFER], [EventType.PROMOTION],
                            [EventType.TRANSFER, EventType.SALARY_CHANGE],
                            [EventType.PROMOTION, EventType.SALARY_CHANGE, EventType.TRANSFER]])
        for step in steps:
            day += timedelta(days=rng.randint(40, 160))
            if day >= today:
                break
            number += 1
            changes, salary = {}, None
            if step == EventType.TRANSFER:
                changes = {"department": rng.choice(depts)}
            elif step == EventType.PROMOTION:
                changes = {"position": rng.choice(positions)}
                salary = Decimal(rng.randint(20, 90) * 100000)
            else:
                salary = Decimal(rng.randint(20, 90) * 100000)
            try:
                events.record(
                    emp, type=step.value, effective=day, changes=changes, salary=salary, reason="Демо өөрчлөлт",
                    note="Демо", by=hr, order_number=f"А/{number}", order_date=day,
                    order_summary="Демо тушаал", order_issued_by="Захирал",
                )
                ok += 1
            except Exception as exc:  # noqa: BLE001 - count and move on; this is a seeder
                bad += 1
                key = f"{type(exc).__name__}: {str(exc)[:90]}"
                errors[key] = errors.get(key, 0) + 1
    OUT("events ok:", ok, "failed:", bad)
    for key, count in sorted(errors.items(), key=lambda kv: -kv[1])[:6]:
        OUT("  ", count, key)


def leave_records_extra(everyone: list[Employee], hr: User) -> None:
    types = {t.name: t for t in LeaveTypeRow.objects.all()}
    OUT("leave types:", list(types))
    for emp in everyone:
        leave_ledger.ensure_grants(emp, today)
    made = cancelled = failed = 0
    plan = [("Ээлжийн амралт", 3), ("Өвчний чөлөө", 2), ("Цалингүй чөлөө", 1), ("Цалинтай хувийн чөлөө", 1), ("Бусад", 1)]
    for emp in everyone:
        for name, weight in plan:
            leave_type = types.get(name)
            if leave_type is None or rng.random() > weight / 4:
                continue
            begin = today + timedelta(days=rng.randint(-420, 60))
            begin += timedelta(days=(7 - begin.weekday()) % 7)
            draft = leave_records.Draft(emp, leave_type, begin, begin + timedelta(days=rng.randint(0, 8)))
            try:
                if leave_records.check(draft, today).errors:
                    failed += 1
                    continue
                row = leave_records.record(draft, hr, today)
                made += 1
            except Exception:  # noqa: BLE001
                failed += 1
                continue
            if rng.random() < 0.12:
                try:
                    from leave.services import writes

                    snap = writes.snapshot(row) if hasattr(writes, "snapshot") else None
                    if snap is not None:
                        leave_records.cancel(row, snap, "Төлөвлөгөө өөрчлөгдсөн", hr, today)
                        cancelled += 1
                except Exception:  # noqa: BLE001
                    pass
    OUT("leave records added:", made, "cancelled:", cancelled, "skipped:", failed)


def make_logins(everyone: list[Employee], hr: User) -> None:
    roles = list(Group.objects.exclude(name="Admin").values_list("name", flat=True))
    OUT("role groups:", roles)
    pool = [e for e in everyone if not hasattr(e, "ext") or getattr(getattr(e, "ext", None), "user_id", None) is None]
    made = 0
    patterns = [
        lambda g, f, i: f"{latin(g)}.{latin(f)}",
        lambda g, f, i: f"{latin(g)[0]}{latin(f)}",
        lambda g, f, i: f"{latin(f)}_{latin(g)}",
        lambda g, f, i: f"{latin(g)}{rng.randint(1, 99)}",
        lambda g, f, i: f"{latin(f)}.{latin(g)[0]}",
        lambda g, f, i: f"{latin(g)}-{latin(f)}"[:20],
        lambda g, f, i: f"{latin(g).upper()}{i}",
        lambda g, f, i: f"{latin(g)}{latin(f)[:3]}{rng.randint(80, 99)}",
    ]
    for i, emp in enumerate(rng.sample(pool, k=min(30, len(pool)))):
        name = patterns[i % len(patterns)](emp.given_name, emp.family_name, i).replace(" ", "")[:30] or f"user{i}"
        if User.objects.filter(username=name).exists():
            name = f"{name}{i}"
        try:
            user, _ = logins.create_login(emp, name, hr)
        except Exception:  # noqa: BLE001
            continue
        user.set_password("demo1234")
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        if roles:
            user.groups.add(Group.objects.get(name=roles[i % len(roles)]))
        made += 1
    OUT("logins added:", made, "total users:", User.objects.count())


if __name__ == "__main__":
    main()
