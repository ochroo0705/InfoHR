import re
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
from employees import access, listing
from employees import today as today_facts
from employees.listing import employee_rows
from employees.models import PERSONAL_FIELDS, Employee, EmployeeExt
from employees.services import history, macs_writes
from employees.tests.conftest import hire_values, named
from macs.models import AddressRow, BirthPlace, City, District, MaritalStatus, Nationality

from reports.filters import Filters, describe
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


def test_staff_list_and_today_agree_on_working_count(
    hr_user: User, hired: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    today = timezone.localdate()
    history.hire(  # hired, but starts in five days: not working now, so neither count may include them
        hire_values(register_no="УБ55500002"),
        {},
        start=today + timedelta(days=5),
        job=job_values,
        salary=Decimal("1000000"),
        by=actor,
    )
    dashboard_rows = employee_rows(access.visible_employees(hr_user).filter(ext__isnull=False), today)
    assert today_facts.headcount(dashboard_rows) == len(rows(hr_user, Filters())) == 1
    upcoming = rows(hr_user, Filters(state="upcoming"))  # the future start has its own filter
    assert [s.row.state for s in upcoming] == ["upcoming"]


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


# Column filters (Filters.extra and the age range), applied to the staff table only.


def test_age_range_filter(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    young = legacy(actor, job_values, birth_date=date(1995, 6, 1))  # 31 on 2026-11-05
    old = legacy(actor, job_values, birth_date=date(1965, 6, 1))  # 61
    unknown = legacy(actor, job_values, birth_date=None)
    assert _listed(hr_user, Filters(age_from=60)) == {old.pk}
    assert _listed(hr_user, Filters(age_to=40)) == {young.pk}
    assert _listed(hr_user, Filters(age_from=0)) == {young.pk, old.pk}  # no birth date: never in a range
    assert unknown.pk not in _listed(hr_user, Filters(age_from=0, age_to=120))


def test_hired_range_inclusive_and_blank_excluded(
    hr_user: User, hired: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    march = legacy(actor, job_values, first_hire_date=date(2026, 3, 1))
    blank = legacy(actor, job_values, first_hire_date=None)
    f = Filters(extra=(("hired_from", "2026-01-05"), ("hired_to", "2026-03-01")))
    assert _listed(hr_user, f) == {hired.pk, march.pk}
    assert blank.pk not in _listed(hr_user, f)


def test_contract_end_range_excludes_open_ended(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    fixed = legacy(actor, job_values, contract_end=date(2027, 3, 1))
    open_ended = legacy(actor, job_values)  # no contract end
    f = Filters(extra=(("contract_end_from", "2027-01-01"), ("contract_end_to", "2027-12-31")))
    assert _listed(hr_user, f) == {fixed.pk}
    assert open_ended.pk not in _listed(hr_user, f)


def test_reversed_range_is_swapped(hr_user: User, hired: Employee) -> None:
    f = Filters(extra=(("hired_from", "2026-03-01"), ("hired_to", "2026-01-01")))
    assert _listed(hr_user, f) == {hired.pk}


def test_code_list_filter_nationality(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    mongol = named(Nationality, "Монгол")
    kazakh = named(Nationality, "Казах")
    mn = legacy(actor, job_values, nationality=mongol)
    kz = legacy(actor, job_values, nationality=kazakh)
    assert _listed(hr_user, Filters(extra=(("nationality", str(mongol.pk)),))) == {mn.pk}
    assert kz.pk not in _listed(hr_user, Filters(extra=(("nationality", str(mongol.pk)),)))


def test_work_conditions_filter(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    normal = legacy(actor, job_values, work_conditions=1)
    heavy = legacy(actor, job_values, work_conditions=2)
    assert _listed(hr_user, Filters(extra=(("work_conditions", "2"),))) == {heavy.pk}
    assert normal.pk not in _listed(hr_user, Filters(extra=(("work_conditions", "2"),)))


def test_salary_range_matches_column(
    accountant_user: User, hired: Employee, actor: User, job_values: dict[str, Any]
) -> None:
    poor = history.hire(
        hire_values(register_no="УБ00000010"),
        {},
        start=date(2026, 1, 5),
        job=job_values,
        salary=Decimal("1000000"),
        by=actor,
    )
    legacy_pay = legacy(actor, job_values)  # no HR salary history: the MACS salary (1,800,000) is shown
    f = Filters(extra=(("salary_from", "1500000"),))
    assert _listed(accountant_user, f) == {hired.pk, legacy_pay.pk}
    assert poor.pk not in _listed(accountant_user, f)


def test_filters_combine_with_and(hr_user: User, hired: Employee, actor: User, job_values: dict[str, Any]) -> None:
    other_dept = macs_writes.save_department("Худалдаа")
    in_both = legacy(actor, job_values, first_hire_date=date(2026, 3, 1))  # department Санхүү, as job_values
    other = legacy(actor, job_values, first_hire_date=date(2026, 3, 1), department=other_dept)
    f = Filters(department=job_values["department"].pk, extra=(("hired_from", "2026-02-01"),))
    assert _listed(hr_user, f) == {in_both.pk}
    assert other.pk not in _listed(hr_user, f)


def test_personal_filters_need_view_personal(accountant_user: User, actor: User, job_values: dict[str, Any]) -> None:
    young = legacy(actor, job_values, birth_date=date(1995, 6, 1), nationality=named(Nationality, "Монгол"))
    old = legacy(actor, job_values, birth_date=date(1965, 6, 1))
    # The accountant lacks view_personal: the age range and the nationality filter have no effect.
    assert _listed(accountant_user, Filters(age_from=60)) == {young.pk, old.pk}
    nationality = Filters(extra=(("nationality", str(named(Nationality, "Монгол").pk)),))
    assert _listed(accountant_user, nationality) == {young.pk, old.pk}


def test_salary_filter_is_direct_permission_gated(hr_user: User, accountant_user: User, hired: Employee) -> None:
    # HR has no view_salary: the salary filter is dropped, so HR gets the same people as with no filter.
    # The accountant has view_salary, and nobody earns 9,999,999,999: the filter keeps nobody.
    nobody = Filters(extra=(("salary_from", "9999999999"),))
    assert _listed(hr_user, nobody) == _listed(hr_user, Filters()) == {hired.pk}
    assert _listed(accountant_user, nobody) == set()


def test_unpermitted_filter_has_no_effect_via_page(client: Client, login_hr: User, hired: Employee) -> None:
    plain = client.get("/reports/staff-list/").context["table"]
    filtered = client.get("/reports/staff-list/?salary_from=9999999999").context["table"]
    assert filtered.count == plain.count >= 1
    assert filtered.filters.extra == ()
    assert not any("Үндсэн цалин" in line for line in describe(filtered.filters, REPORT.filters))


def test_type_select_on_staff_page(login_hr: User, client: Client) -> None:
    page = client.get("/reports/staff-list/").content.decode()
    assert 'name="emptype"' in page
    for label in (
        "Ажилчид",
        "Гадаад нөөц",
        "Ажиллаж байсан",
        "Орохоор бүртгүүлсэн",
        "Гэрээт ажилтан",
        "Өндөр настан",
        "Хөлсөөр ажиллах гэрээтэй",
        "Туршилтын хугацааны ажилтан",
    ):
        assert label in page


def test_state_disabled_for_type_2(login_hr: User, client: Client) -> None:
    state = re.search(r'<select name="state"[^>]*>', client.get("/reports/staff-list/?emptype=2").content.decode())
    assert state is not None
    assert " disabled" in state.group(0)
    working = re.search(r'<select name="state"[^>]*>', client.get("/reports/staff-list/?emptype=1").content.decode())
    assert working is not None
    assert " disabled" not in working.group(0)


# The «Шүүлтүүр нэмэх» picker and the removable filter chips (UI_RULES §4b «Column filter chips»).


def test_picker_lists_only_offered_filters(login_hr: User, client: Client, login_as: Callable[..., User]) -> None:
    hr_page = client.get("/reports/staff-list/").content.decode()
    assert "Шүүлтүүр нэмэх" in hr_page
    assert "add=education_level" in hr_page  # HR has view_personal
    assert "add=salary" not in hr_page  # HR has no view_salary
    assert "Column filters of a report" not in hr_page  # a template comment never reaches the page
    client.logout()
    login_as(client, "Accountant", "accountant-picker")
    accountant_page = client.get("/reports/staff-list/").content.decode()
    assert "add=salary" in accountant_page  # the accountant has view_salary
    assert "add=education_level" not in accountant_page  # and no view_personal


def test_active_filter_shows_as_chip_and_keeps_value(client: Client, login_hr: User) -> None:
    page = client.get("/reports/staff-list/?hired_from=2020-01-01").content.decode()
    assert re.search(r'name="hired_from"[^>]*value="2020-01-01"', page) is not None
    remove = re.search(r'href="([^"]+)"[^>]*aria-label="Шүүлтүүрийг арилгах"', page)
    assert remove is not None
    assert "hired_from" not in remove.group(1)


def test_add_param_draws_empty_chip(client: Client, login_hr: User) -> None:
    page = client.get("/reports/staff-list/?add=nationality").content.decode()
    assert '<select name="nationality"' in page
    assert 'name="add" value="nationality"' in page  # the round trip keeps the chip
    printed = re.search(r'href="(/reports/staff-list/print/[^"]*)"', page)
    assert printed is not None and "add=" not in printed.group(1)
    excel = re.search(r'href="(/reports/staff-list/excel/[^"]*)"', page)
    assert excel is not None and "add=" not in excel.group(1)


def test_sort_links_keep_valueless_chip(client: Client, login_hr: User) -> None:
    page = client.get("/reports/staff-list/?add=nationality").content.decode()
    sort_hrefs = re.findall(r'href="([^"]*sort=[^"]*)"', page)
    assert sort_hrefs  # the control: the table has sortable headers
    assert all("add=nationality" in href for href in sort_hrefs)
    # the Багана pop-up gets the chip too, and keeps it as a hidden field
    columns = client.get("/reports/staff-list/columns/?add=nationality").content.decode()
    assert 'name="add" value="nationality"' in columns


def test_chip_option_without_name_reads_dash(client: Client, login_hr: User) -> None:
    # the database keeps NULL names only in some code lists (Nationality's column is NOT NULL): use MaritalStatus
    nameless = MaritalStatus.objects.create(name=None)
    page = client.get("/reports/staff-list/?add=marital_status").content.decode()
    assert f'<option value="{nameless.pk}">—</option>' in page
    assert ">None<" not in page


def test_unoffered_add_is_ignored(client: Client, login_hr: User) -> None:
    page = client.get("/reports/staff-list/?add=salary").content.decode()
    assert 'data-column-chip="salary"' not in page
    assert 'name="salary_from"' not in page
    assert 'name="add" value="salary"' not in page


def test_other_reports_show_no_picker(client: Client, login_hr: User) -> None:
    response = client.get("/reports/ages/")
    assert response.status_code == 200  # so the check below sees the page, not an error
    assert "Шүүлтүүр нэмэх" not in response.content.decode()
