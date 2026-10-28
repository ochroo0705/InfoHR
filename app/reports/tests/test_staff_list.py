from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from employees import listing
from employees.models import PERSONAL_FIELDS, Employee, EmployeeExt
from employees.services import history
from employees.tests.conftest import hire_values
from macs.models import AddressRow, BirthPlace, City, District

from reports.filters import Filters
from reports.staff_list import PERSONAL, REPORT, rows
from reports.table import allowed_columns, build_table

from .conftest import legacy, transfer

pytestmark = pytest.mark.django_db


def test_includes_people_without_hr_record_and_skips_never_worked(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    untouched = legacy(actor, job_values)
    EmployeeExt.objects.filter(employee=untouched).delete()
    applicant = legacy(actor, job_values, emptype=4, register_no="УБ00000004")
    ids = {s.row.employee.pk for s in rows(hr_user, Filters(state="all"))}
    assert untouched.pk in ids and applicant.pk not in ids


def test_state_filter_matches_employee_list(hr_user: User, hired: Employee, left_employee: Employee) -> None:
    assert {s.row.employee.pk for s in rows(hr_user, Filters())} == {hired.pk}
    assert {s.row.employee.pk for s in rows(hr_user, Filters(state="left"))} == {left_employee.pk}


def test_as_of_date_uses_history(hr_user: User, hired: Employee, actor: User) -> None:
    transfer(hired, to="Борлуулалт", on=date(2026, 6, 1), by=actor)  # a transfer recorded on 2026-06-01
    before = rows(hr_user, Filters(as_of=date(2026, 3, 1)))[0]
    assert before.row.job is not None and before.row.job.department.name == "Санхүү"


def test_as_of_date_excludes_people_hired_later(hr_user: User, hired: Employee) -> None:  # hired 2026-01-05
    assert rows(hr_user, Filters(as_of=date(2025, 12, 31))) == []


def test_matches_employee_list_today(hr_user: User, hired: Employee, left_employee: Employee) -> None:
    today = timezone.localdate()
    for s in rows(hr_user, Filters(state="all")):
        expected = listing.row_for(s.row.employee, today)
        assert s.row.job is not None and expected.job is not None
        assert (s.row.state, s.row.job.department_id, s.row.job.position_id) == (
            expected.state,
            expected.job.department_id,
            expected.job.position_id,
        )


def test_legacy_without_department_groups_last(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    legacy(actor, job_values, department=None)
    table = build_table(REPORT, hr_user, Filters(columns=("name", "department"), group="department"))
    assert table.groups[-1][0] == "Хэлтэсгүй"


def test_hr_sees_no_bank_or_salary_columns(hr_user: User) -> None:
    keys = {c.key for c in allowed_columns(REPORT, hr_user)}
    assert "salary" not in keys and "account_no" not in keys and "register_no" in keys


def test_accountant_sees_salary_not_personal(accountant_user: User) -> None:
    keys = {c.key for c in allowed_columns(REPORT, accountant_user)}
    assert "salary" in keys and "register_no" not in keys


def test_catalogue_links_staff_list(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    assert 'href="/reports/staff-list/' in client.get("/reports/").content.decode()


def test_salary_cell_renders_as_money(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "Accountant")
    page = client.get("/reports/staff-list/?cols=name&cols=salary").content.decode()
    assert "2,500,000₮" in page


def test_as_of_note_only_for_another_day() -> None:
    assert REPORT.note is not None
    assert REPORT.note(Filters()) == ""
    assert REPORT.note(Filters(as_of=date(2026, 3, 1))) == (
        "2026-03-01 өдрийн байдлаар: төлөв, хэлтэс, албан тушаал, гэрээ тухайн өдрийнх "
        "(Info HR-д ажлын түүхгүй ажилтных өнөөдрийнх); нас, ажилласан жил тухайн өдрөөр; бусад багана өнөөдрийнх."
    )


def test_empty_money_cell_renders_blank(
    client: Client, login_as: Callable[..., User], actor: User, job_values: dict[str, Any]
) -> None:
    legacy(actor, job_values, salary=Decimal("0"))  # no salary: current_salary is None
    login_as(client, "Accountant")
    page = client.get("/reports/staff-list/?cols=name&cols=salary").content.decode()
    assert '<td class="text-right"></td>' in page


def test_employee_list_offers_staff_report_only_when_openable(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    assert 'href="/reports/staff-list/"' in client.get("/employees/").content.decode()
    client.logout()
    reporter = User.objects.create_user("reporter", password="x-long-pass-123")  # noqa: S106
    reporter.user_permissions.add(Permission.objects.get(content_type__app_label="reports", codename="view_reports"))
    client.force_login(reporter)  # may open reports, but may not see the employees
    response = client.get("/employees/")
    assert response.status_code == 200  # so the check below sees the page, not an error
    assert 'href="/reports/staff-list/"' not in response.content.decode()


def _city(name: str) -> City:
    return City.objects.get_or_create(name=name)[0]


def _district(city: City, name: str) -> District:
    return District.objects.get_or_create(name=name, city=city)[0]


def _address_queries(ctx: CaptureQueriesContext) -> list[str]:
    return [q["sql"] for q in ctx.captured_queries if '"address"' in q["sql"] or '"birth_place"' in q["sql"]]


def test_address_and_birthplace_text(hr_user: User, hired: Employee) -> None:
    ulaanbaatar = _city("Улаанбаатар")
    AddressRow.objects.create(
        employee=hired, city=ulaanbaatar, district=_district(ulaanbaatar, "Баянзүрх"), street="1-р хороо"
    )
    arkhangai = _city("Өвөрхангай")
    BirthPlace.objects.create(employee=hired, city=arkhangai, district=_district(arkhangai, "Хархорин"))
    row = rows(hr_user, Filters(columns=("name", "address", "birthplace")))[0]
    assert row.address == "Улаанбаатар, Баянзүрх, 1-р хороо"
    assert row.birthplace == "Өвөрхангай, Хархорин"


def test_address_skips_empty_parts(hr_user: User, hired: Employee) -> None:
    ulaanbaatar = _city("Улаанбаатар")
    AddressRow.objects.create(
        employee=hired, city=ulaanbaatar, district=_district(ulaanbaatar, "Баянзүрх"), street=None
    )
    assert rows(hr_user, Filters(columns=("name", "address")))[0].address == "Улаанбаатар, Баянзүрх"


def test_first_address_by_id_wins(hr_user: User, hired: Employee) -> None:
    ulaanbaatar = _city("Улаанбаатар")
    AddressRow.objects.create(
        employee=hired, city=ulaanbaatar, district=_district(ulaanbaatar, "Баянзүрх"), street="Эхний"
    )
    darkhan = _city("Дархан")
    AddressRow.objects.create(employee=hired, city=darkhan, district=_district(darkhan, "Дархан-Уул"), street="Хоёр")
    assert rows(hr_user, Filters(columns=("name", "address")))[0].address == "Улаанбаатар, Баянзүрх, Эхний"


def test_address_queries_only_when_shown(hr_user: User, hired: Employee) -> None:
    with CaptureQueriesContext(connection) as hidden:
        rows(hr_user, Filters(columns=("name",)))
    with CaptureQueriesContext(connection) as shown:
        rows(hr_user, Filters(columns=("name", "address", "birthplace")))
    assert _address_queries(hidden) == []
    assert _address_queries(shown)  # the control: the same check sees the query when the columns are shown


def test_address_needs_personal_permission(accountant_user: User, hired: Employee) -> None:
    with CaptureQueriesContext(connection) as ctx:
        rows(accountant_user, Filters(columns=("name", "address")))  # the accountant has no view_personal
    assert _address_queries(ctx) == []


# Personal fields need macs.view_personal, as on the employee page (the Хувийн tab).
PERSONAL_COLUMNS = (
    "clan_name",
    "gender",
    "nationality",
    "citizenship",
    "birthplace",
    "social_origin",
    "elected_position",
    "education_level",
    "academic_degree",
    "clothing_size",
    "shoe_size",
)


def test_every_column_named_as_a_personal_field_needs_view_personal() -> None:
    for column in REPORT.columns:
        if column.key in PERSONAL_FIELDS:  # so the two lists cannot drift apart
            assert column.needs == PERSONAL, column.key


def test_accountant_is_offered_no_personal_column(accountant_user: User) -> None:
    offered = {c.key for c in allowed_columns(REPORT, accountant_user)}
    assert not offered & set(PERSONAL_COLUMNS)


def test_hr_is_offered_the_personal_columns(hr_user: User) -> None:  # the positive control
    offered = {c.key for c in allowed_columns(REPORT, hr_user)}
    assert set(PERSONAL_COLUMNS) <= offered


def test_gender_filter_is_ignored_without_view_personal(
    hr_user: User, accountant_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    women = legacy(actor, job_values, gender="F")
    men = legacy(actor, job_values, gender="M")

    def ids(user: User, f: Filters) -> set[int]:
        return {s.row.employee.pk for s in rows(user, f)}

    everyone = ids(accountant_user, Filters())
    assert ids(accountant_user, Filters(gender="F")) == everyone  # not filtered for the accountant
    assert {women.pk, men.pk} <= ids(accountant_user, Filters(gender="F"))
    hr_women = ids(hr_user, Filters(gender="F"))  # the positive control: HR is filtered
    assert women.pk in hr_women and men.pk not in hr_women


def test_gender_select_only_with_view_personal(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "accountant-gender")
    assert 'name="gender"' not in client.get("/reports/staff-list/").content.decode()
    client.logout()
    login_as(client, "HR", "hr-gender")
    assert 'name="gender"' in client.get("/reports/staff-list/").content.decode()


# Legacy people (no Info HR job history) on another day.


def _listed(user: User, f: Filters) -> set[int]:
    return {s.row.employee.pk for s in rows(user, f)}


def test_legacy_person_hired_after_the_day_is_not_listed(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    late = legacy(actor, job_values, first_hire_date=date(2026, 3, 1))
    assert late.pk not in _listed(hr_user, Filters(as_of=date(2026, 2, 28)))
    assert late.pk in _listed(hr_user, Filters(as_of=date(2026, 3, 1)))  # hired that day counts as hired


def test_legacy_person_hired_before_the_day_is_listed(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    early = legacy(actor, job_values, first_hire_date=date(2025, 6, 1))
    assert early.pk in _listed(hr_user, Filters(as_of=date(2026, 2, 28)))


def test_future_as_of_leaves_out_a_job_that_starts_later(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    today = timezone.localdate()
    later = history.hire(
        hire_values(register_no="УБ55500001"),
        {},
        start=today + timedelta(days=60),
        job=job_values,
        salary=Decimal("1000000"),
        by=actor,
    )
    assert later.pk not in _listed(hr_user, Filters(as_of=today + timedelta(days=30)))
    assert later.pk in _listed(hr_user, Filters(as_of=today + timedelta(days=90)))


def test_future_as_of_leaves_out_a_legacy_person_hired_later(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    today = timezone.localdate()
    later = legacy(actor, job_values, first_hire_date=today + timedelta(days=60))
    assert later.pk not in _listed(hr_user, Filters(as_of=today + timedelta(days=30)))


# The as-of date and today.


def test_today_as_of_is_not_a_setting(hr_user: User) -> None:
    today = timezone.localdate()
    assert build_table(REPORT, hr_user, Filters(as_of=today)).filters.as_of is None
    past = date(2026, 3, 1)
    assert build_table(REPORT, hr_user, Filters(as_of=past)).filters.as_of == past
