"""Query-count guard for the busy pages with many employees (scoping log RK-008, D-043).

A page that asks the database once per person is fine with 10 staff and slow with 300. Each page below is
loaded with 100 employees and must stay under a fixed ceiling that does not depend on the headcount: one
query per person would be 100 and fail. The real cost at 300 people is measured with `scripts/scale_check.py`.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from leave.models import LeaveSettings, LeaveTypeExt
from leave.services import ledger, records
from macs.models import LeaveTypeRow

from employees.models import Department, Employee, Position
from employees.services import history, macs_writes

pytestmark = pytest.mark.django_db

PEOPLE = 100
CEILING = 70  # a page needs a few dozen queries whatever the headcount; one per person would be 100+

PAGES = [
    "/employees/today/",
    "/employees/",
    "/employees/?view=table",
    "/leave/",
    "/leave/balances/",
    "/leave/calendar/",
    "/leave/requests/",
    "/me/",
    "/reports/staff-list/?columns=code,name,salary",
    "/reports/annual-leave/",
    "/reports/leave-balance/",
    "/reports/absences/",
    "/reports/away-on-date/",
    "/reports/household-income/",
]


def _staff(by: User) -> None:
    departments = [macs_writes.save_department(f"Хэлтэс {n}") for n in range(5)]
    position = macs_writes.save_position("Мэргэжилтэн")
    start = timezone.localdate() - timedelta(days=500)
    for i in range(PEOPLE):
        job: dict[str, Any] = {
            "position": position,
            "department": departments[i % len(departments)],
            "employee_type": "full_time",
            "status": "active",
            "contract_type": "open_ended",
        }
        values = {
            "family_name": "Батын",
            "given_name": f"Ажилтан{i}",
            "register_no": f"УБ{90000000 + i}",
            "birth_date": date(1980 + i % 20, 1 + i % 12, 1 + i % 27),
            "gender": "F" if i % 2 else "M",
            "work_phone": "99112233",
            "first_hire_date": start,
            "work_conditions": 1,
        }
        history.hire(values, {}, start=start, job=job, salary=Decimal("2500000"), by=by)


def test_busy_pages_use_a_fixed_number_of_queries() -> None:
    admin = User.objects.create_superuser("scale_admin", password="x-long-pass-123")  # noqa: S106
    row = LeaveTypeRow.objects.create(name="Ээлжийн амралт")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=True, is_paid=True)
    LeaveSettings.objects.update_or_create(pk=1, defaults={"auto_annual_grant": True})
    _staff(admin)
    today = timezone.localdate()
    for employee in Employee.objects.all()[:30]:  # grants for everyone, a leave around today for some
        ledger.ensure_grants(employee, today)
    for employee in Employee.objects.all()[:10]:
        begin = today + timedelta(days=(7 - today.weekday()) % 7)
        draft = records.Draft(employee, row, begin, begin + timedelta(days=2))
        if not records.check(draft, today).errors:
            records.record(draft, admin, today)
    assert Department.objects.count() >= 5 and Position.objects.exists()

    from employees.models import ensure_ext

    own = Employee.objects.order_by("pk")[0]  # /me/ needs a login linked to an employee
    ext = ensure_ext(own)
    ext.user = admin
    ext.save(update_fields=["user"])

    client = Client()
    client.force_login(admin)
    client.get("/employees/today/")  # the first request of the day runs the daily sync: not what is measured
    too_many = {}
    for url in PAGES:
        with CaptureQueriesContext(connection) as queries:
            response = client.get(url, follow=True)
        assert response.status_code == 200, url
        if len(queries) > CEILING:
            too_many[url] = len(queries)
    assert not too_many, f"pages that ask the database per person (ceiling {CEILING}): {too_many}"
