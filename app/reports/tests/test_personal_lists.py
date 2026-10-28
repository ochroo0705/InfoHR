from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee
from employees.tests.conftest import named
from macs.models import AwardRow, DisciplineRow, DisciplineType

from reports.filters import Filters
from reports.personal_lists import AWARDS, DISCIPLINE
from reports.table import build_table

pytestmark = pytest.mark.django_db


def _discipline(employee: Employee, kind: DisciplineType, on: date) -> DisciplineRow:
    """A discipline row as the personal tab writes one (personal_writes.add with kind «discipline»)."""
    return DisciplineRow.objects.create(
        employee=employee,
        from_discipline="Санхүүгийн алба",
        discipline_type=kind,
        discipline_date=on,
        description="Хоцорсон",
        discipline_sal_percent=Decimal("12.50"),
        discipline_enddate=date(2026, 5, 1),
    )


def _award(employee: Employee, name: str, on: date | None) -> AwardRow:
    """An award row as the personal tab writes one (personal_writes.add with kind «award»)."""
    return AwardRow.objects.create(
        employee=employee,
        give_org="Засгийн газар",
        award_name=name,
        award_date=on,
        description="Жилийн үр дүн",
    )


def test_discipline_in_period_and_type_filter(hr_user: User, hired: Employee) -> None:
    warn = named(DisciplineType, "Сануулга")
    other = named(DisciplineType, "Ноцтой сануулга")
    _discipline(hired, warn, date(2026, 2, 10))
    _discipline(hired, other, date(2026, 5, 1))
    _discipline(hired, warn, date(2025, 12, 31))
    f = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
    assert [r.item.discipline_date for r in DISCIPLINE.rows(hr_user, f)] == [date(2026, 2, 10), date(2026, 5, 1)]
    f = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), discipline=warn.pk)
    assert len(DISCIPLINE.rows(hr_user, f)) == 1


def test_award_last_day_of_period_counts(hr_user: User, hired: Employee) -> None:
    _award(hired, "Жуух бичиг", date(2026, 12, 31))
    _award(hired, "Огноогүй", None)
    f = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
    assert [r.item.award_name for r in AWARDS.rows(hr_user, f)] == ["Жуух бичиг"]


def test_department_column_from_listing(hr_user: User, hired: Employee) -> None:
    _award(hired, "Жуух бичиг", date(2026, 3, 1))
    table = build_table(AWARDS, hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31)))
    by_key = dict(zip([c.key for c in table.columns], table.groups[0][1][0], strict=True))
    assert by_key["department"].value == "Санхүү"


def test_accountant_cannot_open_or_see_in_catalogue(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc")
    assert client.get("/reports/discipline/").status_code == 403
    assert client.get("/reports/awards/").status_code == 403
    html = client.get("/reports/").content.decode()
    assert "/reports/discipline/" not in html and "/reports/awards/" not in html


def test_pages_print_and_excel_open(client: Client, login_hr: User) -> None:
    for key in ("discipline", "awards"):
        for suffix in ("", "print/", "excel/"):
            assert client.get(f"/reports/{key}/{suffix}").status_code == 200


def test_grey_notes_on_the_page(client: Client, login_hr: User) -> None:
    discipline = client.get("/reports/discipline/").content.decode()
    assert "Хэлтэс, албан тушаал нь ажилтны өнөөдрийн ажил." in discipline
    awards = client.get("/reports/awards/").content.decode()
    assert "Хэлтэс, албан тушаал нь ажилтны өнөөдрийн ажил. Огноогүй шагнал орохгүй." in awards
