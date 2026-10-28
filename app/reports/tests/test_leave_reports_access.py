from collections.abc import Callable
from datetime import date

import pytest
from accounts.models import User
from django.test import Client
from leave.services import writes
from leave.tests.conftest import make_employee, sick  # noqa: F401 (fixtures)
from macs.models import Absence, AbsenceType, LeaveTypeRow

from reports.registry import REPORTS

pytestmark = pytest.mark.django_db

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

LEAVE_REPORTS = ("annual-leave", "leave-balance", "absences", "absence-totals", "away-on-date", "leave-requests")

BAD_FILTERS = {"leave_state": "zzz", "leave_type": "abc", "absence_type": "-1", "as_of": "nope"}


def test_employee_role_is_refused_on_every_leave_report(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee")
    for key in LEAVE_REPORTS:
        assert client.get(f"/reports/{key}/").status_code == 403, key


def test_catalogue_links_all_six_for_hr_and_none_greyed(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get("/reports/").content.decode()
    for key in LEAVE_REPORTS:
        assert f'href="/reports/{key}/"' in page, key
    assert page.count("удахгүй") == 33 - len(REPORTS)


def test_print_and_excel_work_for_each_leave_report(
    client: Client,
    login_as: Callable[..., User],
    actor: User,
    sick: LeaveTypeRow,  # noqa: F811
) -> None:
    # one recorded leave and one old-log row, so the print and Excel value paths run on real data
    emp = make_employee(actor, hired=date(2024, 3, 1))
    writes.record_assign(emp, sick, date(2026, 6, 10), date(2026, 6, 12), 3, "", actor)
    kind = AbsenceType.objects.create(name="Цалинтай чөлөө")
    Absence.objects.create(
        employee_id=emp.pk, absence_type=kind, from_date=date(2026, 6, 20), to_date=date(2026, 6, 21), note=""
    )
    login_as(client, "HR")
    for key in LEAVE_REPORTS:
        assert client.get(f"/reports/{key}/print/").status_code == 200, key
        excel = client.get(f"/reports/{key}/excel/")
        assert excel.status_code == 200 and excel["Content-Type"] == XLSX, key


def test_bad_leave_filter_values_are_ignored(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    for key in LEAVE_REPORTS:
        assert client.get(f"/reports/{key}/", BAD_FILTERS).status_code == 200, key
