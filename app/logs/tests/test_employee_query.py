from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.db import connection
from django.http import QueryDict
from employees import access
from employees.models import ActivityEntry, ActivityKind, Employee, ensure_ext
from employees.services import history, macs_writes

from logs.employee_query import AREAS, EmployeeLogFilter, filtered, page, parse_filter, visible_entries
from logs.params import parse_date, parse_id, words

pytestmark = pytest.mark.django_db

PASSWORD = "x-long-pass-123"  # noqa: S105
UB = ZoneInfo("Asia/Ulaanbaatar")
SECRET_AMOUNT = "3777777"  # noqa: S105  # appears only in a sensitive (salary) entry's changes


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("hr_actor", password=PASSWORD)  # noqa: S106


@pytest.fixture
def job_values(db: None) -> dict[str, Any]:
    return {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }


def _user(name: str, role: str | None, *, active: bool = True, first: str = "", last: str = "") -> User:
    user = User.objects.create_user(
        name,
        password=PASSWORD,
        first_name=first,
        last_name=last,
        is_active=active,  # noqa: S106
    )
    if role is not None:
        user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)  # fresh permission cache


def _hire(actor: User, job_values: dict[str, Any], register_no: str, family: str, given: str) -> Employee:
    values = {
        "family_name": family,
        "given_name": given,
        "register_no": register_no,
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
    }
    return history.hire(values, {}, start=date(2026, 1, 5), job=dict(job_values), salary=Decimal("2500000"), by=actor)


def _link_login(employee: Employee, user: User) -> None:
    """The login lives on the HR row (EmployeeExt.user); cache the row so later checks see the link."""
    ext = ensure_ext(employee)
    ext.user = user
    ext.save(update_fields=["user"])
    employee.ext = ext


def _entry(employee: Employee, message: str, **fields: Any) -> ActivityEntry:
    fields.setdefault("kind", ActivityKind.CHANGED)
    return ActivityEntry.objects.create(employee=employee, message=message, **fields)


def _set_at(entry: ActivityEntry, when: datetime) -> None:
    # The log is append-only in the ORM (AppendOnlyQuerySet.update raises), so the test moves the timestamp in SQL.
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{ActivityEntry._meta.db_table}" SET "at_time" = %s WHERE id = %s',  # noqa: S608
            [when, entry.pk],
        )


@dataclass
class World:
    admin: User
    hr: User
    acc: User
    staff: User  # Employee role, linked to `own`
    inactive: User  # HR role, but switched off
    own: Employee
    other: Employee
    rich: Employee  # has salary (sensitive), personal and internal-note entries
    hr_actor: User


@pytest.fixture
def world(actor: User, job_values: dict[str, Any]) -> World:
    admin = _user("log_admin", "Admin", first="Болд", last="Админ")
    hr = _user("log_hr", "HR", first="Оюун", last="Хүний")
    acc = _user("log_acc", "Accountant", first="Төмөр", last="Нягтлан")
    staff = _user("log_staff", "Employee", first="Сараа", last="Батын")
    inactive = _user("log_off", "HR", active=False, first="Наран", last="Хуучин")

    own = _hire(actor, job_values, "УБ99110001", "Батын", "Сараа")
    other = _hire(actor, job_values, "УБ99110002", "Доржийн", "Ганзориг")
    rich = _hire(actor, job_values, "УБ99110003", "Жавхлангийн", "Өнөр")
    _link_login(own, staff)

    _entry(own, "Хаяг өөрчлөгдсөн", changes=[{"field": "Хаяг", "old": "Сүхбаатар", "new": "Баянзүрх"}])
    _entry(own, "Хувийн мэдээлэл", personal=True, changes=[{"field": "Регистр", "old": "", "new": "УБ1"}])
    _entry(own, "Тэмдэглэл: ажлын дэвтэр", kind=ActivityKind.NOTE)

    _entry(other, "Ажлын байр шилжсэн")
    _entry(other, "Тэмдэглэл: хүнд", kind=ActivityKind.NOTE)

    _entry(
        rich,
        "Цалин өөрчлөгдсөн",
        sensitive=True,
        changes=[{"field": "Цалин", "old": "2500000", "new": SECRET_AMOUNT}],
    )
    _entry(rich, "Хувийн утас", personal=True, changes=[{"field": "Утас", "old": "", "new": "99112233"}])
    _entry(rich, "Тэмдэглэл: цалингийн тохиролцоо", kind=ActivityKind.NOTE)
    _entry(rich, "Ажил мэргэжил")
    return World(admin, hr, acc, staff, inactive, own, other, rich, actor)


def _ids(qs: Any) -> set[int]:
    return set(qs.values_list("id", flat=True))


def test_parity_with_drawer(world: World) -> None:
    users = [world.admin, world.hr, world.acc, world.staff, world.inactive]
    employees = [world.own, world.other, world.rich]
    for user in users:
        may_see = set(access.visible_employees(user).values_list("pk", flat=True))
        for employee in employees:
            got = _ids(visible_entries(user).filter(employee=employee))
            if employee.pk in may_see:
                expected = _ids(access.visible_activity(user, employee))
            else:
                expected = set()
            assert got == expected, f"{user.username} / {employee.family_name}"
    # Sanity: the comparison is not vacuous for the full-rights user.
    assert _ids(visible_entries(world.admin).filter(employee=world.rich))


def test_inactive_user_sees_nothing(world: World) -> None:
    assert not visible_entries(world.inactive).exists()


def test_staff_sees_own_record_without_notes_or_salary(world: World) -> None:
    kinds = set(visible_entries(world.staff).values_list("kind", flat=True))
    assert ActivityKind.NOTE not in kinds
    assert not visible_entries(world.staff).filter(sensitive=True).exists()
    assert visible_entries(world.staff).filter(employee=world.own, personal=True).exists()


def test_salary_entry_hidden_without_view_salary_even_when_searched(world: World) -> None:
    hr_hits = filtered(world.hr, EmployeeLogFilter(q=SECRET_AMOUNT))
    acc_hits = filtered(world.acc, EmployeeLogFilter(q=SECRET_AMOUNT))
    assert not list(hr_hits)
    assert len(list(acc_hits)) == 1


def test_search_words_all_must_match(world: World) -> None:
    assert [e.message for e in filtered(world.admin, EmployeeLogFilter(q="Цалин өөрчлөгдсөн"))] == ["Цалин өөрчлөгдсөн"]
    assert not list(filtered(world.admin, EmployeeLogFilter(q="Цалин хүүхэд")))


def test_search_in_changes_values(world: World) -> None:
    hits = [e.message for e in filtered(world.admin, EmployeeLogFilter(q="Сүхбаатар"))]
    assert hits == ["Хаяг өөрчлөгдсөн"]
    assert [e.message for e in filtered(world.admin, EmployeeLogFilter(q="Баянзүрх"))] == ["Хаяг өөрчлөгдсөн"]


def test_field_filter_exact(world: World) -> None:
    rows = filtered(world.admin, EmployeeLogFilter(field="Хаяг"))
    assert [e.message for e in rows] == ["Хаяг өөрчлөгдсөн"]
    assert not list(filtered(world.admin, EmployeeLogFilter(field="Хаяг орон")))


def test_date_range_inclusive(world: World) -> None:
    day = date(2026, 3, 10)
    before = _entry(world.other, "өмнөх өдөр")
    first = _entry(world.other, "эхний өдөр")
    last = _entry(world.other, "сүүлийн өдөр")
    after = _entry(world.other, "маргаашийн өдөр")
    _set_at(before, datetime(2026, 3, 9, 23, 59, tzinfo=UB))
    _set_at(first, datetime(2026, 3, 10, 0, 0, tzinfo=UB))
    _set_at(last, datetime(2026, 3, 10, 23, 59, tzinfo=UB))
    _set_at(after, datetime(2026, 3, 11, 0, 0, tzinfo=UB))

    got = _ids(filtered(world.admin, EmployeeLogFilter(date_from=day, date_to=day)))
    assert got == {first.pk, last.pk}


def test_system_only_filter(world: World) -> None:
    _entry(world.other, "системийн бичлэг")  # by stays empty
    _entry(world.other, "хүний бичлэг", by=world.hr_actor)
    rows = list(filtered(world.admin, EmployeeLogFilter(system_only=True)))
    assert rows and all(e.by_id is None for e in rows)


def test_employee_actor_and_area_filters(world: World) -> None:
    by_name = filtered(world.admin, EmployeeLogFilter(by="Актор"))
    assert not list(by_name)
    _entry(world.other, "нэрээр", by=world.hr_actor)
    assert list(filtered(world.admin, EmployeeLogFilter(by="hr_actor")))
    assert {e.employee_id for e in filtered(world.admin, EmployeeLogFilter(emp="Жавхлан"))} == {world.rich.pk}
    assert {e.employee_id for e in filtered(world.admin, EmployeeLogFilter(employee=world.own.pk))} == {world.own.pk}
    notes = list(filtered(world.admin, EmployeeLogFilter(area="notes")))
    assert notes and all(e.kind == ActivityKind.NOTE for e in notes)
    salary = list(filtered(world.acc, EmployeeLogFilter(area="salary")))
    assert salary and all(e.sensitive for e in salary)  # hire itself writes salary entries too
    assert "Цалин өөрчлөгдсөн" in {e.message for e in salary}


def test_garbage_params_are_dropped(world: World) -> None:
    params = QueryDict(
        "offset=abc&from=zzz&kind=%00&employee=1e9&to=2026-02-30&area=drop-table"
        "&kind=created&field=%00&by=" + "9" * 300 + "&q=%00%00"
    )
    f = parse_filter(params)
    assert f.employee is None
    assert f.date_from is None and f.date_to is None
    assert f.kinds == ["created"]
    assert f.area == ""
    assert f.q == ""
    assert "\x00" not in f.field
    assert len(f.by) <= 300
    # The database must accept what is left (a NUL byte would raise there).
    list(filtered(world.admin, f))


def test_helpers_never_raise() -> None:
    assert parse_id("1e9") is None and parse_id("9" * 10) is None and parse_id("42") == 42
    assert parse_date("2026-99-99") is None and parse_date("0000-01-01") is None
    assert parse_date("2026-03-10") == date(2026, 3, 10)
    assert words("a\x00b") == ["ab"]  # NUL bytes are removed (Postgres refuses them)
    assert len(words(" ".join(["w"] * 20))) == 8
    assert all(len(w) <= 100 for w in words("y" * 500))


def test_page_has_more_flag(world: World) -> None:
    rows, more = page(world.admin, EmployeeLogFilter(), 0, 2)
    assert len(rows) == 2 and more is True
    total = filtered(world.admin, EmployeeLogFilter()).count()
    rows, more = page(world.admin, EmployeeLogFilter(), total - 1, 2)
    assert len(rows) == 1 and more is False


def test_query_count_flat_at_20000_rows(world: World, django_assert_max_num_queries: Any) -> None:
    ActivityEntry.objects.bulk_create(
        [ActivityEntry(employee=world.rich, kind=ActivityKind.CHANGED, message=f"жишээ {i}") for i in range(20000)],
        batch_size=5000,
    )
    world.admin.has_perm("macs.view_employees")  # warm the permission cache outside the measured call
    with django_assert_max_num_queries(8):
        rows, more = page(world.admin, EmployeeLogFilter(), 0, 60)
    assert len(rows) == 60 and more is True


def test_search_matches_values_not_json_syntax(world: World) -> None:
    _entry(world.other, "Хотхон солигдсон", changes=[{"field": "Хотхон", "old": "Өнөр", "new": "Зайсан"}])
    for word in ["old", "new", "field", '"']:
        assert not list(filtered(world.admin, EmployeeLogFilter(q=word))), word
    # a field label and an old value (Mongolian) still match
    assert [e.message for e in filtered(world.admin, EmployeeLogFilter(q="Хотхон"))] == ["Хотхон солигдсон"]
    assert [e.message for e in filtered(world.admin, EmployeeLogFilter(q="Өнөр"))] == ["Хотхон солигдсон"]


def test_page_clamps_huge_offset_and_size(world: World) -> None:
    assert page(world.admin, EmployeeLogFilter(), 10**30, 60) == ([], False)
    rows, more = page(world.admin, EmployeeLogFilter(), 0, 10**30)
    assert len(rows) <= 500 and more is False


def test_kind_filter_is_capped(world: World) -> None:
    params = QueryDict("&".join(["kind=x"] * 10 + ["kind=created"]))  # the 11th value is never read
    assert parse_filter(params).kinds == []


@pytest.mark.parametrize("area", AREAS)
def test_area_filters_stay_inside_drawer(world: World, area: str) -> None:
    for user in [world.admin, world.hr, world.acc, world.staff, world.inactive]:
        drawer: set[int] = set()
        for employee in access.visible_employees(user):
            drawer |= _ids(access.visible_activity(user, employee))
        assert _ids(filtered(user, EmployeeLogFilter(area=area))) <= drawer, (user.username, area)
