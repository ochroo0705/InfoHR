from collections.abc import Callable
from datetime import date

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee
from employees.tests.conftest import named
from macs.models import ContactRow, ContactType, FamilyRelation, FamilyRow

from reports.registry import REPORTS

pytestmark = pytest.mark.django_db

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# The nine staff surveys (phase 4) and the status each role gets on the report page.
# Derived from each report's `needs` and app/accounts/roles.py:
#   employee-info    macs.view_employees                        HR yes, Accountant yes
#   statistics       view_employees + view_personal             HR yes, Accountant no (no view_personal)
#   ages, elders, children, sizes, contacts   the same as statistics
#   engineers        macs.view_employees                        HR yes, Accountant yes
#   household-income view_employees + view_salary               HR no (no view_salary), Accountant yes
# Employee has no reports.view_reports and no macs permissions, so it is refused everywhere.
EXPECTED: dict[str, dict[str, int]] = {
    "employee-info": {"HR": 200, "Accountant": 200, "Employee": 403},
    "statistics": {"HR": 200, "Accountant": 403, "Employee": 403},
    "ages": {"HR": 200, "Accountant": 403, "Employee": 403},
    "elders": {"HR": 200, "Accountant": 403, "Employee": 403},
    "children": {"HR": 200, "Accountant": 403, "Employee": 403},
    "sizes": {"HR": 200, "Accountant": 403, "Employee": 403},
    "contacts": {"HR": 200, "Accountant": 403, "Employee": 403},
    "engineers": {"HR": 200, "Accountant": 200, "Employee": 403},
    "household-income": {"HR": 403, "Accountant": 200, "Employee": 403},
}

BAD_FILTERS = {"age_from": "x", "age_to": "999", "attribute": "zzz", "contact_type": "-1", "year": "1", "as_of": "nope"}


def _keys_for(role: str) -> list[str]:
    return [key for key, codes in EXPECTED.items() if codes[role] == 200]


def test_employee_role_is_refused_on_every_survey_report(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee")
    for key in EXPECTED:
        assert client.get(f"/reports/{key}/").status_code == 403, key


@pytest.mark.parametrize("role", ["HR", "Accountant"])
def test_each_survey_report_status_matches_the_table(client: Client, login_as: Callable[..., User], role: str) -> None:
    login_as(client, role)
    for key, codes in EXPECTED.items():
        assert client.get(f"/reports/{key}/").status_code == codes[role], key


def test_catalogue_links_only_the_surveys_hr_may_open_and_greying_count(
    client: Client, login_as: Callable[..., User]
) -> None:
    login_as(client, "HR")
    page = client.get("/reports/").content.decode()
    for key, codes in EXPECTED.items():
        link = f'href="/reports/{key}/"'
        if codes["HR"] == 200:
            assert link in page, key
        else:
            assert link not in page, key  # a built report the user may not open is not listed at all
    assert page.count("удахгүй") == 33 - len(REPORTS)


def test_catalogue_for_accountant_links_its_three_surveys(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant")
    page = client.get("/reports/").content.decode()
    for key, codes in EXPECTED.items():
        assert (f'href="/reports/{key}/"' in page) == (codes["Accountant"] == 200), key


def _family_and_contact(employee: Employee) -> None:
    """One child and one contact row, so the print and Excel value paths run on real data."""
    son = FamilyRelation.objects.create(name="Хүү", fm_type="son")
    FamilyRow.objects.create(employee=employee, relation=son, given_name="Бат", birth_date=date(2015, 1, 1))
    ContactRow.objects.create(
        employee=employee, contact_type=named(ContactType, "Утас"), value="99112233", name="Эх", relative="Ээж"
    )


@pytest.mark.parametrize("role", ["HR", "Accountant"])
def test_print_and_excel_work_for_each_survey_report_the_role_may_open(
    client: Client, login_as: Callable[..., User], hired: Employee, role: str
) -> None:
    _family_and_contact(hired)
    login_as(client, role)
    keys = _keys_for(role)
    assert keys  # every role in this test may open at least one survey
    for key in keys:
        assert client.get(f"/reports/{key}/print/").status_code == 200, key
        excel = client.get(f"/reports/{key}/excel/")
        assert excel.status_code == 200 and excel["Content-Type"] == XLSX, key


@pytest.mark.parametrize("role", ["HR", "Accountant"])
def test_bad_survey_filter_values_are_ignored(client: Client, login_as: Callable[..., User], role: str) -> None:
    login_as(client, role)
    for key in _keys_for(role):
        assert client.get(f"/reports/{key}/", BAD_FILTERS).status_code == 200, key


def test_double_sign_numbers_in_the_address_are_ignored_not_a_500(
    client: Client, login_as: Callable[..., User]
) -> None:
    """A value like --5 once passed the digit check and raised in int(); it must read as no value."""
    login_as(client, "HR")
    assert client.get("/reports/ages/?age_from=--5&year=--2000").status_code == 200
    for key in _keys_for("HR"):
        assert client.get(f"/reports/{key}/?age_to=--1&year=--2000").status_code == 200, key
