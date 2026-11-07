"""The team calendar's department filter, and the leave pages that load in batches (config/batching.py)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs

import pytest
from accounts.models import User
from config import batching
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from employees import listing
from employees.models import Department, Employee, JobRecord, JobStatus
from employees.services import history, macs_writes
from macs.models import LeaveAssign, LeaveTypeRow

from leave.models import LeaveExt, LeaveTypeExt
from leave.services import calendar, records, rows
from leave.services.records import Draft

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("grants_on")]

PEOPLE = 8
BATCH = 3
HTMX = {"HX-Request": "true"}


@pytest.fixture(autouse=True)
def small_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batching, "LIST_BATCH", BATCH)


def _hire(by: User, i: int, position: Any, department: Any) -> Employee:
    start = date(2024, 3, 1)
    job: dict[str, Any] = {
        "position": position,
        "department": department,
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {
        "family_name": "Батын",
        "given_name": f"Ажилтан{i}",
        "register_no": f"УБ{90000000 + i}",
        "birth_date": date(1990, 1, 1 + i),
        "gender": "M",
        "first_hire_date": start,
        "work_conditions": 1,
    }
    return history.hire(values, {}, start=start, job=job, salary=Decimal("2500000"), by=by)


@pytest.fixture
def staff(actor: User) -> list[Employee]:
    position = macs_writes.save_position("Мэргэжилтэн")
    finance, trade = macs_writes.save_department("Санхүү"), macs_writes.save_department("Худалдаа")
    return [_hire(actor, i, position, finance if i < 5 else trade) for i in range(PEOPLE)]


@pytest.fixture
def client(actor: User) -> Client:
    c = Client()
    c.force_login(actor)
    return c


def _names(body: str) -> list[str]:
    return [f"Ажилтан{i}" for i in range(PEOPLE) if f"Ажилтан{i}" in body]


def _next_query(body: str, url: str) -> dict[str, list[str]]:
    marker = f'hx-get="{url}?'
    if marker not in body:
        return {}
    return parse_qs(body.split(marker)[1].split('"')[0].replace("&amp;", "&"))


def _department_id(name: str) -> int:
    return Department.objects.get(name=name).pk


def test_calendar_filters_by_department(client: Client, staff: list[Employee]) -> None:
    everyone = client.get("/leave/calendar/", {"month": "2026-11"}).content.decode()
    assert len(_names(everyone)) == PEOPLE
    only = client.get(
        "/leave/calendar/", {"month": "2026-11", "department": str(_department_id("Худалдаа"))}
    ).content.decode()
    assert _names(only) == ["Ажилтан5", "Ажилтан6", "Ажилтан7"]


def test_calendar_keeps_the_department_in_the_month_links(client: Client, staff: list[Employee]) -> None:
    body = client.get(
        "/leave/calendar/", {"month": "2026-11", "department": str(_department_id("Санхүү"))}
    ).content.decode()
    assert f"?month=2026-10&department={_department_id('Санхүү')}" in body
    assert f"?month=2026-12&department={_department_id('Санхүү')}" in body


@pytest.mark.parametrize("bad", ["abc", "-1", "99999999999999", "0"])
def test_calendar_ignores_a_bad_department(client: Client, staff: list[Employee], bad: str) -> None:
    response = client.get("/leave/calendar/", {"department": bad})
    assert response.status_code == 200


def test_balances_load_in_batches_without_a_gap(client: Client, staff: list[Employee]) -> None:
    first = client.get("/leave/balances/").content.decode()
    assert first.count('class="hover:bg-violet-50 cursor-pointer"') == BATCH and "<html" in first
    seen, query = first.count('class="hover:bg-violet-50 cursor-pointer"'), _next_query(first, "/leave/balances/")
    while query:
        body = client.get(f"/leave/balances/?offset={query['offset'][0]}", headers=HTMX).content.decode()
        assert "<html" not in body
        seen += body.count('class="hover:bg-violet-50 cursor-pointer"')
        query = _next_query(body, "/leave/balances/")
    assert seen == PEOPLE


def test_balances_ignore_offset_without_htmx(client: Client, staff: list[Employee]) -> None:
    body = client.get("/leave/balances/?offset=3").content.decode()
    assert "<html" in body and body.count('class="hover:bg-violet-50 cursor-pointer"') == BATCH


@pytest.fixture
def many_leaves(actor: User, staff: list[Employee]) -> None:
    row = LeaveTypeRow.objects.create(name="Чөлөө")
    LeaveTypeExt.objects.create(leave_type=row, uses_annual_balance=False, is_paid=False)
    start = timezone.localdate() + timedelta(days=14)
    start += timedelta(days=(7 - start.weekday()) % 7)  # a Monday: one working day per leave, no overlap
    for i in range(PEOPLE):
        day = start + timedelta(days=7 * i)
        draft = Draft(staff[0], row, day, day)
        assert not records.check(draft, timezone.localdate()).errors
        records.record(draft, actor, timezone.localdate())


def test_leave_list_loads_in_batches(client: Client, many_leaves: None) -> None:
    first = client.get("/leave/").content.decode()
    assert first.count('/edit/"') == BATCH
    seen, query = BATCH, _next_query(first, "/leave/")
    assert query["offset"] == [str(BATCH)]
    while query:
        body = client.get(f"/leave/?offset={query['offset'][0]}", headers=HTMX).content.decode()
        assert "<html" not in body
        seen += body.count('/edit/"')
        query = _next_query(body, "/leave/")
    assert seen == PEOPLE


def test_leave_list_next_batch_keeps_the_filters(client: Client, many_leaves: None) -> None:
    body = client.get("/leave/", {"status": "recorded", "q": "Ажилтан0"}, headers=HTMX).content.decode()
    query = _next_query(body, "/leave/")
    assert query["q"] == ["Ажилтан0"] and query["status"] == ["recorded"]


def test_leave_list_empty_text_only_on_the_first_batch(client: Client, staff: list[Employee]) -> None:
    assert "Чөлөө бүртгэгдээгүй" in client.get("/leave/").content.decode()
    assert "Чөлөө бүртгэгдээгүй" not in client.get("/leave/?offset=999", headers=HTMX).content.decode()


def test_still_working_matches_the_row_by_row_rule(staff: list[Employee]) -> None:
    """The database test for «not left today» gives the people the old Python rule over `employee_rows` gave."""
    today = timezone.localdate()
    JobRecord.objects.filter(employee=staff[0]).update(status=JobStatus.LEFT)  # left: the job valid today says so
    JobRecord.objects.filter(employee=staff[1]).delete()  # no HR history: MACS decides
    Employee.objects.filter(pk=staff[1].pk).update(emptype=3)  # MACS: dismissed, but no HR history: still listed
    JobRecord.objects.filter(employee=staff[2]).delete()
    Employee.objects.filter(pk=staff[2].pk).update(emptype=1)  # no history, still working in MACS
    everyone = Employee.objects.all()
    old = {
        r.employee.pk
        for r in listing.employee_rows(everyone, today)
        if r.legacy or r.job is None or today not in r.job.period or r.job.status != JobStatus.LEFT
    }
    new = set(listing.still_working(everyone, today).values_list("pk", flat=True))
    assert new == old
    assert staff[0].pk not in new and staff[1].pk in new and staff[2].pk in new and staff[3].pk in new


def test_leave_page_states_and_type_agree_with_the_row_by_row_filter(staff: list[Employee]) -> None:
    kind = LeaveTypeRow.objects.create(name="Чөлөө А")
    other = LeaveTypeRow.objects.create(name="Чөлөө Б")
    day = date(2026, 5, 4)
    statuses = [None, LeaveAssign.APPROVED, LeaveAssign.CANCELLED, LeaveAssign.CANCELLED, LeaveAssign.REJECTED, 9]
    for i, status in enumerate(statuses):
        a = LeaveAssign.objects.create(
            employee=staff[0],
            leave_type=kind if i % 2 else other,
            date1=day + timedelta(days=i),
            date2=day + timedelta(days=i),
            status=status,
        )
        if i == 3:
            LeaveExt.objects.create(assign=a, mistake=True)  # a cancelled row marked as wrongly recorded
    people = Employee.objects.all()
    for name in ("RECORDED", "CANCELLED", "MISTAKE", "REJECTED", "NOPE", None):
        for type_id in (None, kind.pk):
            old = [
                lv.id
                for lv in rows.leaves(employee_ids=list(people.values_list("pk", flat=True)))
                if (name is None or lv.state.name == name) and (type_id is None or lv.leave_type.pk == type_id)
            ]
            new_rows, more = rows.leaves_page(people, offset=0, size=50, type_id=type_id, state=name)
            assert [lv.id for lv in new_rows] == old and not more, (name, type_id)
    page, more = rows.leaves_page(people, offset=2, size=2)
    assert len(page) == 2 and more  # newest first, cut by the database


def test_leaves_without_a_day_count_read_the_holidays_once(staff: list[Employee]) -> None:
    """Old-program rows have no `adays`: their working days are counted with one holiday lookup, not one per row."""
    kind = LeaveTypeRow.objects.create(name="Чөлөө В")
    first = date(2026, 6, 1)
    for i in range(6):
        LeaveAssign.objects.create(
            employee=staff[i],
            leave_type=kind,
            date1=first + timedelta(days=7 * i),
            date2=first + timedelta(days=7 * i + 8),
        )
    with CaptureQueriesContext(connection) as queries:
        found, _ = rows.leaves_page(Employee.objects.all(), offset=0, size=50)
    assert len(found) == 6
    assert [lv.days for lv in found] == [calendar.working_days(lv.start, lv.end) for lv in found]
    holiday_read = "FROM " + connection.ops.quote_name("hr_legalholidays")  # the backend's spelling of the name
    assert sum(holiday_read in q["sql"] for q in queries.captured_queries) == 1
