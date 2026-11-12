"""Follow-up to seed_governed_gaps.py on the Firebird test copy (DEBUG only; run once):
people who left (the offboarding checklist is started first, as the screens require), and a retry of the legacy
employees whose first event hit a same-day clash.

    python scripts/seed_governed_leavers.py      (with DB_ENGINE=firebird and FIREBIRD_NAME set)
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
from checklists.models import ChecklistKind  # noqa: E402
from checklists.services import lifecycle  # noqa: E402
from django.conf import settings  # noqa: E402
from django.utils import timezone  # noqa: E402
from macs.models import Department, FiredReason, Position  # noqa: E402

from employees.models import Employee, EventType, JobStatus  # noqa: E402
from employees.services import events  # noqa: E402

OUT = lambda *a: print(*a, flush=True)  # noqa: E731
rng = random.Random(99)
today = timezone.localdate()
admin = User.objects.get(username="admin")
n = [9800]


def record(emp: Employee, **kw) -> Exception | None:
    n[0] += 1
    try:
        events.record(emp, by=admin, note="Демо", order_number=f"В/{n[0]}", order_date=kw["effective"],
                      order_summary="Демо тушаал", order_issued_by="Захирал", **kw)
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


def main() -> None:
    if not settings.DEBUG:
        raise SystemExit("DEBUG only.")
    depts, positions = list(Department.objects.all()), list(Position.objects.all())
    reasons = list(FiredReason.objects.all())
    OUT("fired reasons:", [r.name for r in reasons])

    retry = [e for e in Employee.objects.all() if not e.job_records.exists()]
    ok = 0
    for emp in retry:
        for _ in range(4):  # a different day each time: the clash is with the contract start
            day = today - timedelta(days=rng.randint(30, 700))
            err = record(emp, type=EventType.SALARY_CHANGE.value, effective=day, changes={},
                         salary=Decimal(rng.randint(20, 80) * 100000), reason="Цалингийн тохиргоо",
                         start_department=rng.choice(depts), start_position=rng.choice(positions))
            if err is None:
                ok += 1
                break
    OUT("legacy retried:", len(retry), "started:", ok)

    people = [e for e in Employee.objects.all() if e.job_records.exists()
              and (getattr(e.job_records.order_by("-id").first(), "status", None) == JobStatus.ACTIVE)]
    rng.shuffle(people)
    left = 0
    errors: dict[str, int] = {}
    for emp in people:
        if left >= 10:
            break
        reason = rng.choice(reasons)
        day = today - timedelta(days=rng.randint(2, 20))
        try:
            lifecycle.start(emp, ChecklistKind.OFFBOARDING, reason=str(reason.pk), anchor_day=day, by=admin)
        except Exception as exc:  # noqa: BLE001
            errors[f"checklist: {str(exc)[:80]}"] = errors.get(f"checklist: {str(exc)[:80]}", 0) + 1
            continue
        err = record(emp, type=EventType.TERMINATION.value, effective=day, changes={}, salary=None,
                     reason="Өөрийн хүсэлтээр", fired_reason=reason, offboarding_override="Демо өгөгдөл")
        if err is None:
            left += 1
        else:
            key = f"termination: {str(err)[:80]}"
            errors[key] = errors.get(key, 0) + 1
    OUT("left:", left, "errors:", errors)
    os._exit(0)


if __name__ == "__main__":
    main()
