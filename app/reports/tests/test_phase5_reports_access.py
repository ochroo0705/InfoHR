from collections.abc import Callable

import pytest
from accounts.models import User
from django.test import Client

from reports.catalogue import CATALOGUE
from reports.registry import REPORTS

pytestmark = pytest.mark.django_db

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# The eleven phase-5 reports (training, skill tasks, health checks, performance and its summary, accidents,
# poisoning, loans, gifts given, gifts due, complaints).
PHASE5_REPORTS = (
    "training",
    "skill-tasks",
    "health-checks",
    "performance",
    "performance-summary",
    "accidents",
    "poisoning",
    "loans",
    "gifts-given",
    "gifts-due",
    "complaints",
)

# The status each role gets on the page, its print page and its Excel file.
# Admin opens everything. HR is refused the loans report (F1 needs view_salary, which HR lacks).
# Accountant opens only loans (F1 needs view_employees + view_salary; the other reports need view_personal,
# which the Accountant lacks). Employee has no reports.view_reports, so it is refused everywhere.
ALLOWED: dict[str, set[str]] = {
    "Admin": set(PHASE5_REPORTS),
    "HR": set(PHASE5_REPORTS) - {"loans"},
    "Accountant": {"loans"},
    "Employee": set(),
}


def _expected(role: str, key: str) -> int:
    return 200 if key in ALLOWED[role] else 403


@pytest.mark.parametrize("role", ["Admin", "HR", "Accountant", "Employee"])
@pytest.mark.parametrize("key", PHASE5_REPORTS)
def test_phase5_report_page_print_and_excel_follow_the_role_table(
    client: Client, login_as: Callable[..., User], role: str, key: str
) -> None:
    login_as(client, role)
    want = _expected(role, key)
    assert client.get(f"/reports/{key}/").status_code == want, "page"
    assert client.get(f"/reports/{key}/print/").status_code == want, "print"
    excel = client.get(f"/reports/{key}/excel/")
    assert excel.status_code == want, "excel"
    if want == 200:
        assert excel["Content-Type"] == XLSX


def test_admin_catalogue_links_all_eleven_and_greys_none(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Admin")
    page = client.get("/reports/").content.decode()
    for key in PHASE5_REPORTS:
        assert f'href="/reports/{key}/"' in page, key  # a greyed card has no link
    assert page.count("удахгүй") == 33 - len(REPORTS)


def test_hr_catalogue_does_not_offer_loans(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    page = client.get("/reports/").content.decode()
    for key in PHASE5_REPORTS:
        if key == "loans":
            assert f'href="/reports/{key}/"' not in page
        else:
            assert f'href="/reports/{key}/"' in page, key
    loans_title = next(entry.title for entry in CATALOGUE if entry.key == "loans")
    assert loans_title not in page  # a built report the user may not open is not listed at all


def test_accountant_catalogue_offers_only_loans_of_the_eleven(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant")
    page = client.get("/reports/").content.decode()
    for key in PHASE5_REPORTS:
        assert (f'href="/reports/{key}/"' in page) == (key == "loans"), key
