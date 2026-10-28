from collections.abc import Callable
from datetime import date, timedelta

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone
from employees.models import Employee
from macs.models import Department

from reports.filters import Filters
from reports.movements import HISTORY, LEAVERS, MOVEMENTS
from reports.registry import REPORTS
from reports.table import build_table
from reports.types import Report

from .conftest import transfer

pytestmark = pytest.mark.django_db


def test_movements_lists_hire_and_transfer(hr_user: User, hired: Employee, actor: User) -> None:
    transfer(hired, to="Борлуулалт", on=date(2026, 6, 1), by=actor)
    got = MOVEMENTS.rows(hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31)))
    assert [c.kind for c in got] == ["hire", "transfer"]


def test_future_change_is_not_a_movement(hr_user: User, hired: Employee, actor: User) -> None:
    today = timezone.localdate()
    transfer(hired, to="Борлуулалт", on=today, by=actor)
    transfer(hired, to="Маркетинг", on=today + timedelta(days=1), by=actor)
    got = MOVEMENTS.rows(hr_user, Filters(date_from=today, date_to=today + timedelta(days=30)))
    assert [(c.kind, c.day) for c in got] == [("transfer", today)]


def test_change_filter_and_department_filter(hr_user: User, hired: Employee, actor: User) -> None:
    transfer(hired, to="Борлуулалт", on=date(2026, 6, 1), by=actor)
    f = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), change="hire")
    assert [c.kind for c in MOVEMENTS.rows(hr_user, f)] == ["hire"]
    sales = Department.objects.get(name="Борлуулалт")
    f = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), department=sales.pk)
    assert [c.kind for c in MOVEMENTS.rows(hr_user, f)] == ["transfer"]


def test_history_employee_filter_limits_rows(hr_user: User, hired: Employee, left_employee: Employee) -> None:
    f = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), employee=left_employee.pk)
    assert {c.employee.pk for c in HISTORY.rows(hr_user, f)} == {left_employee.pk}


def test_leavers_reason_and_years(hr_user: User, hired: Employee, left_employee: Employee) -> None:
    got = LEAVERS.rows(hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31)))
    assert [c.employee.pk for c in got] == [left_employee.pk]
    table = build_table(LEAVERS, hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31)))
    by_key = dict(zip([c.key for c in table.columns], table.groups[0][1][0], strict=True))
    assert by_key["reason"].value == "Өөрийн хүсэлтээр" and by_key["years"].value == 0


def test_employee_role_cannot_open(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee", "own")
    assert client.get("/reports/movements/").status_code == 403


def test_pages_print_and_excel_open(client: Client, login_hr: User, hired: Employee) -> None:
    for key in ("movements", "history", "leavers"):
        assert client.get(f"/reports/{key}/").status_code == 200
        assert client.get(f"/reports/{key}/print/").status_code == 200
        assert client.get(f"/reports/{key}/excel/").status_code == 200


def test_built_reports_are_registered() -> None:
    registered: dict[str, Report] = {key: REPORTS[key] for key in ("movements", "history", "leavers")}
    assert registered == {"movements": MOVEMENTS, "history": HISTORY, "leavers": LEAVERS}


NOTE = (
    "Info HR-д бүртгэсэн өөрчлөлтүүд, өнөөдрийг хүртэл. Хуучин програмаас ирсэн ажилтны ажилд орсон огноо нь анх "
    "ажилд орсон огноогоор гарна; хуучин програмд бүртгэсэн шилжилт, ажлаас гарсан нь энд гарахгүй."
)


def test_grey_note_says_how_old_program_hires_show() -> None:
    assert MOVEMENTS.note is not None
    assert MOVEMENTS.note(Filters()) == NOTE
    assert HISTORY.note is not None and HISTORY.note(Filters()) == NOTE


def test_note_is_on_the_page(client: Client, login_hr: User) -> None:
    assert NOTE in client.get("/reports/movements/").content.decode()
