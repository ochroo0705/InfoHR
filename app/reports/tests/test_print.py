import re
from collections.abc import Callable

import pytest
from accounts.models import User
from django.test import Client
from employees.models import CompanySettings, Employee
from macs.models import Department

pytestmark = pytest.mark.django_db

PRINT = "/reports/staff-list/print/"
TWO_COLUMNS = "cols=code&cols=name"
EIGHT_COLUMNS = (
    "cols=code&cols=name&cols=clan_name&cols=gender&cols=department&cols=position&cols=first_hire_date&cols=work_phone"
)


def _headers(page: str) -> list[str]:
    """The printed table's header texts, in order."""
    return [text.strip() for text in re.findall(r"<th[^>]*>([^<]*)</th>", page)]


@pytest.fixture
def company_name() -> str:
    company = CompanySettings.get()
    company.name = "Тестийн компани ХХК"
    company.save()
    return company.name


def test_print_has_company_title_filters_and_two_columns(
    client: Client, login_as: Callable[..., User], hired: Employee, company_name: str
) -> None:
    login_as(client, "HR")
    dept = Department.objects.get(name="Санхүү")
    page = client.get(f"{PRINT}?{TWO_COLUMNS}&department={dept.pk}").content.decode()
    assert company_name in page
    assert "Ажилчдын жагсаалт" in page
    assert "Хэлтэс: Санхүү" in page
    assert _headers(page) == ["Код", "Ажилтан"]
    assert "size: A4 portrait" in page


def test_more_than_seven_columns_print_landscape(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    page = client.get(f"{PRINT}?{EIGHT_COLUMNS}").content.decode()
    assert "size: A4 landscape" in page
    assert "size: A4 portrait" not in page


def test_hr_cannot_print_salary(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")  # no view_salary
    page = client.get(f"{PRINT}?cols=salary").content.decode()
    assert "Үндсэн цалин" not in page


def test_print_cells_render_like_the_screen(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "Accountant")
    page = client.get(f"{PRINT}?cols=name&cols=first_hire_date&cols=salary").content.decode()
    assert "2026-01-05" in page  # dates as Y-m-d
    assert "2,500,000₮" in page  # money as the mnt filter


def test_print_shows_the_as_of_note(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "HR")
    page = client.get(f"{PRINT}?as_of=2026-03-01&{TWO_COLUMNS}").content.decode()
    assert "2026-03-01 өдрийн байдлаар" in page


def test_employee_role_is_forbidden(client: Client, login_as: Callable[..., User], hired: Employee) -> None:
    login_as(client, "Employee")
    assert client.get(PRINT).status_code == 403


def test_unknown_report_print_is_404(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR")
    assert client.get("/reports/nope/print/").status_code == 404


def test_report_page_links_print_with_the_same_filters(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "HR")
    dept = Department.objects.get(name="Санхүү")
    page = client.get(f"/reports/staff-list/?department={dept.pk}&cols=name").content.decode()
    assert f'href="{PRINT}?department={dept.pk}&amp;cols=name" target="_blank" rel="noopener"' in page
    bare = client.get("/reports/staff-list/").content.decode()
    assert f'href="{PRINT}?cols=code&amp;cols=name' in bare  # the default columns the screen shows go too


def test_print_drops_personal_columns_and_gender_line_for_accountant(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:
    login_as(client, "Accountant")
    page = client.get(f"{PRINT}?gender=F&cols=code&cols=clan_name&cols=gender&cols=birthplace").content.decode()
    assert _headers(page) == ["Код"]
    assert "Хүйс" not in page and "Ургийн овог" not in page and "Төрсөн газар" not in page


def test_print_shows_personal_columns_and_gender_line_for_hr(
    client: Client, login_as: Callable[..., User], hired: Employee
) -> None:  # the positive control
    login_as(client, "HR")
    page = client.get(f"{PRINT}?gender=F&cols=code&cols=clan_name&cols=gender").content.decode()
    assert "Ургийн овог" in page and "Хүйс: Эмэгтэй" in page
