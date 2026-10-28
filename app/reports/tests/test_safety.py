import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from accounts.models import User
from django.db import connection
from django.test import Client
from employees.models import Employee
from macs.models import Branch, FactoryAccidentRow, InfoRow

from reports.filters import Filters
from reports.registry import REPORTS
from reports.safety import ACCIDENTS, POISONING

from .conftest import count_queries, legacy

pytestmark = pytest.mark.django_db

YEAR = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
PROCEDURES = Path(__file__).resolve().parents[3] / "docs" / "migration" / "legacy-logic" / "procedures"
LINE = re.compile(r"rownum=(\d+|null);\s*description='([^']*)';")


@pytest.fixture(autouse=True)
def no_production_rows() -> None:
    """The test database may hold production accident and organisation rows; each test starts with none."""
    FactoryAccidentRow.objects.all().delete()
    InfoRow.objects.all().delete()


def _type_code() -> int:
    """The factory_accident_type row every accident row points to (no model for it): created once, then reused."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT faccident_type_id FROM factory_accident_type LIMIT 1")
        found = cursor.fetchone()
        if found is not None:
            return int(found[0])
        cursor.execute(
            "INSERT INTO factory_accident_type (description) VALUES (%s) RETURNING faccident_type_id", ["Тест"]
        )
        return int(cursor.fetchone()[0])


def _accident(
    person: Employee,
    on: date = date(2026, 6, 15),
    kind: str = "accident",
    branch: Branch | None = None,
    result: int = 3,
    type_: int = 3,
    reason: int = 14,
    group: int | None = None,
) -> FactoryAccidentRow:
    return FactoryAccidentRow.objects.create(
        kind=kind,
        type_code=_type_code(),
        employee=person,
        accident_date=on,
        group_accident=group,
        facc_type=type_,
        facc_reason=reason,
        facc_result=result,
        name="Осол",
        branch=branch,
    )


def _numbers(report: Any, user: User, f: Filters = YEAR) -> dict[int, int | None]:
    """The value of every numbered line, by its number."""
    return {x.number: x.value for x in report.rows(user, f) if x.number is not None}


def _old_lines(name: str) -> list[tuple[int | None, str]]:
    """The (number, label) pairs of a legacy procedure, in the order the procedure emits them."""
    text = (PROCEDURES / name).read_text(encoding="utf-8")
    return [(None if n == "null" else int(n), label) for n, label in LINE.findall(text)]


@pytest.mark.parametrize(
    ("report", "procedure", "last"),
    [(ACCIDENTS, "CALC_FACTORYACC.sql", 36), (POISONING, "CALC_FACTORYTOX.sql", 40)],
)
def test_all_lines_in_the_old_order(hr_user: User, report: Any, procedure: str, last: int) -> None:
    old = _old_lines(procedure)
    assert [n for n, _ in old if n is not None][-1] == last  # the parse read the whole procedure
    assert [(x.number, x.label) for x in report.rows(hr_user, Filters())] == old


def test_line_ids_follow_the_order(hr_user: User) -> None:
    lines = ACCIDENTS.rows(hr_user, YEAR)
    assert [x.id for x in lines] == list(range(1, len(lines) + 1))


def test_counts_by_result_type_and_reason(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    person = legacy(actor, job_values)
    for result in (1, 2, 3, 4):
        _accident(person, result=result)
    _accident(person, result=3, type_=1, reason=1)
    _accident(person, result=3, type_=2, reason=1)
    _accident(person, result=3, type_=3, reason=8)
    values = _numbers(ACCIDENTS, hr_user)
    assert values[3] == 7
    assert values[5] == 7
    assert [values[n] for n in (7, 8, 9, 10)] == [1, 1, 4, 1]
    assert [values[n] for n in (11, 12, 13)] == [1, 1, 5]
    assert values[14] == 2  # reason 1
    assert values[26] == 4  # reason 14, the default
    # reason 8 has no line number in the old procedure, but is still counted
    slippery = next(x for x in ACCIDENTS.rows(hr_user, YEAR) if x.label == "Халтиргаанаас")
    assert slippery.number is None
    assert slippery.value == 1


def test_poisoning_counts_use_its_own_codes(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    person = legacy(actor, job_values)
    _accident(person, kind="toxic", result=1, type_=3, reason=1)
    _accident(person, kind="toxic", result=2, type_=4, reason=15)
    _accident(person, kind="toxic", result=4, type_=2, reason=16)
    _accident(person, kind="toxic", result=3, type_=1, reason=9)
    _accident(person, kind="accident", result=1)  # another kind
    values = _numbers(POISONING, hr_user)
    assert values[3] == 4
    assert values[5] == 4
    assert [values[n] for n in (7, 8, 9, 10)] == [1, 1, 1, 1]
    assert [values[n] for n in (11, 12, 13, 14)] == [1, 1, 1, 1]  # light, middle, heavy, died
    assert values[15] == 1
    assert values[23] == 1
    assert values[29] == 1
    assert values[30] == 1


def test_group_accident_line(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    person = legacy(actor, job_values)
    _accident(person, group=1)
    _accident(person, group=0)
    _accident(person, group=None)
    _accident(person, kind="toxic", group=1)
    assert _numbers(ACCIDENTS, hr_user)[4] == 1
    assert _numbers(POISONING, hr_user)[4] == 1
    assert _numbers(POISONING, hr_user, Filters(date_from=date(2020, 1, 1), date_to=date(2020, 12, 31)))[4] == 0


def test_woman_line_uses_employee_gender_and_employee_branch(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнө")
    woman = legacy(actor, job_values, gender="F", branch=north)
    man = legacy(actor, job_values, gender="M", branch=north)
    _accident(woman, branch=south)  # the accident's branch is not the woman's branch
    _accident(man, branch=north)
    in_north = _numbers(
        ACCIDENTS, hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), branch=north.pk)
    )
    assert in_north[3] == 1  # the accident of the man
    assert in_north[6] == 1  # the woman, by her own branch
    in_south = _numbers(
        ACCIDENTS, hr_user, Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), branch=south.pk)
    )
    assert in_south[3] == 1
    assert in_south[6] == 0
    everyone = _numbers(ACCIDENTS, hr_user)
    assert everyone[6] == 1


def test_age_bands_use_age_on_the_accident_date(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    on = date(2026, 6, 15)
    births = [date(2008, 6, 16), date(2008, 6, 15), date(1992, 6, 16), date(1991, 6, 15), None]  # 17, 18, 33, 35, none
    for birth in births:
        _accident(legacy(actor, job_values, birth_date=birth), on=on)
    values = _numbers(ACCIDENTS, hr_user)
    assert values[3] == 5
    assert (values[27], values[28], values[29]) == (1, 2, 1)  # the one without a birth date is in no band


def test_worked_year_bands_add_prior_service(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    on = date(2024, 6, 15)
    f = Filters(date_from=date(2024, 1, 1), date_to=date(2024, 12, 31))
    cases = [
        (date(2020, 1, 1), 2),  # 4 + 2 = 6 -> 5-15
        (date(2023, 1, 1), 0),  # 1 -> up to 5
        (date(2019, 6, 15), 0),  # exactly 5 -> 5-15
        (date(2009, 6, 15), 0),  # exactly 15 -> over 15
        (date(2000, 1, 1), 0),  # 24 -> over 15
        (date(2025, 1, 1), 1),  # hired after the accident: 0 + 1 -> up to 5
        (None, 9),  # no hire date: not counted
    ]
    for hire, prior in cases:
        _accident(legacy(actor, job_values, first_hire_date=hire, prior_service_years=prior), on=on)
    values = _numbers(ACCIDENTS, hr_user, f)
    assert (values[30], values[31], values[32]) == (2, 2, 2)


def test_period_is_end_inclusive_and_other_kind_ignored(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    person = legacy(actor, job_values)
    for on in (date(2025, 12, 31), date(2026, 1, 1), date(2026, 12, 31), date(2027, 1, 1)):
        _accident(person, on=on)
    _accident(person, on=date(2026, 5, 5), kind="toxic")
    assert _numbers(ACCIDENTS, hr_user)[3] == 2
    assert _numbers(POISONING, hr_user)[3] == 1


def test_last_day_counts_whole_day_and_next_midnight_does_not(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    """The column is a timestamp: an accident at 14:00 on the last day counts, one at 00:00 the next day does not."""
    person = legacy(actor, job_values)
    afternoon = _accident(person, on=date(2026, 12, 31))
    midnight = _accident(person, on=date(2027, 1, 1))
    with connection.cursor() as cursor:
        for row, stamp in ((afternoon, "2026-12-31 14:00:00"), (midnight, "2027-01-01 00:00:00")):
            cursor.execute("UPDATE factory_accident SET accident_date = %s WHERE faccident_id = %s", [stamp, row.pk])
    assert _numbers(ACCIDENTS, hr_user)[3] == 1


def test_branch_filter_uses_accident_branch(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнө")
    person = legacy(actor, job_values, branch=south)  # the person's own branch is not used for these lines
    _accident(person, branch=north, result=1)
    _accident(person, branch=south)
    _accident(person, branch=None)
    f = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), branch=north.pk)
    values = _numbers(ACCIDENTS, hr_user, f)
    assert values[3] == 1
    assert values[7] == 1
    assert _numbers(ACCIDENTS, hr_user)[3] == 3


def test_ownership_line_shows_total_only_for_matching_org_type(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    person = legacy(actor, job_values)
    _accident(person)
    _accident(person)
    assert [_numbers(ACCIDENTS, hr_user)[n] for n in (33, 34, 35, 36)] == [None] * 4  # no organisation row
    InfoRow.objects.create(register_no="1234567", orgtype_code="02")
    assert [_numbers(ACCIDENTS, hr_user)[n] for n in (33, 34, 35, 36)] == [None, 2, None, None]
    assert [_numbers(POISONING, hr_user)[n] for n in (37, 38, 39, 40)] == [None, 0, None, None]  # its own total: 0
    InfoRow.objects.all().delete()
    InfoRow.objects.create(register_no="1234567", orgtype_code="04")
    assert [_numbers(ACCIDENTS, hr_user)[n] for n in (33, 34, 35, 36)] == [None, None, None, 2]


def test_headings_have_no_value(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    _accident(legacy(actor, job_values))
    headings = {
        "Ослын хэлбэр",
        "Ослын шалтгаан",
        "Нас",
        "Ажилласан хугацаа",
        "Аж ахуйн нэгж, байгууллагын өмчийн хэлбэр",
    }
    found = {x.label: x for x in ACCIDENTS.rows(hr_user, YEAR) if x.label in headings}
    assert set(found) == headings
    assert all(x.number is None and x.value is None for x in found.values())
    cells = {c.key: c.value(found["Нас"]) for c in ACCIDENTS.columns}
    assert cells == {"label": "Нас", "number": None, "value": None}


def test_average_and_women_counts_are_working_people_of_the_branch(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнө")
    legacy(actor, job_values, gender="F", branch=north)
    legacy(actor, job_values, gender="M", branch=north)
    legacy(actor, job_values, gender="F", branch=south)
    f = Filters(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31), branch=north.pk)
    values = _numbers(ACCIDENTS, hr_user, f)
    assert (values[1], values[2]) == (2, 1)
    assert (_numbers(POISONING, hr_user, f)[1], _numbers(POISONING, hr_user, f)[2]) == (2, 1)
    assert _numbers(ACCIDENTS, hr_user, Filters(branch=south.pk))[1] == 1


@pytest.mark.parametrize("key", ["accidents", "poisoning"])
def test_registered_with_the_agreed_shape(key: str) -> None:
    report = REPORTS[key]
    assert report.filters == ("period", "branch")
    assert [c.key for c in report.columns] == ["label", "number", "value"]
    assert [c.label for c in report.columns] == ["Үзүүлэлт", "Мөр", "Утга"]
    assert report.needs == ("macs.view_employees", "macs.view_personal")
    assert report.source is FactoryAccidentRow
    assert report.note is not None
    assert "Осол, хордлогын бүртгэлийг хуучин програмаас харуулна" in report.note(Filters())


@pytest.mark.parametrize("key", ["accidents", "poisoning"])
def test_pages_open_for_hr_and_refuse_accountant_and_employee(
    client: Client, login_as: Callable[..., User], key: str
) -> None:
    login_as(client, "Employee", "emp")
    assert client.get(f"/reports/{key}/").status_code == 403
    login_as(client, "Accountant", "acc")
    assert client.get(f"/reports/{key}/").status_code == 403
    login_as(client, "HR", "hr")
    for suffix in ("", "print/", "excel/"):
        assert client.get(f"/reports/{key}/{suffix}").status_code == 200


def test_page_shows_title_and_lines(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "hr")
    page = client.get("/reports/accidents/").content.decode()
    assert "Үйлдвэрийн ослын тайлан" in page
    assert "Ажилтны дундаж тоо" in page
    page = client.get("/reports/poisoning/").content.decode()
    assert "Хурц хордлогын тайлан" in page
    assert "Хурц хордлого гарсан тоо" in page


@pytest.mark.parametrize("report", [ACCIDENTS, POISONING])
def test_query_count_does_not_grow_with_rows(
    hr_user: User, actor: User, job_values: dict[str, Any], hired: Employee, report: Any
) -> None:
    kind = "accident" if report is ACCIDENTS else "toxic"
    first, *others = [legacy(actor, job_values), hired, legacy(actor, job_values)]
    _accident(first, kind=kind)
    one = count_queries(report, hr_user, YEAR)
    for person in others:
        _accident(person, kind=kind)
    assert report.rows(hr_user, YEAR)[2].value == 3
    three = count_queries(report, hr_user, YEAR)
    assert three[1] - three[0] == one[1] - one[0]
    assert three[0] == one[0]  # the accident rows are read in one query however many there are


def test_birth_date_after_the_accident_is_in_no_age_band(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    _accident(legacy(actor, job_values, birth_date=date(2027, 1, 1)), on=date(2026, 6, 15))
    values = _numbers(ACCIDENTS, hr_user)
    assert values[3] == 1
    assert (values[27], values[28], values[29]) == (0, 0, 0)


def test_statistic_reports_show_no_total_line(client: Client, login_as: Callable[..., User]) -> None:
    """The rows are numbered statistic lines, so «Нийт: N» (the line count) means nothing: screen, print, Excel."""
    login_as(client, "HR", "hr")
    for key in ("accidents", "poisoning"):
        assert "Нийт:" not in client.get(f"/reports/{key}/").content.decode()
        assert "Нийт:" not in client.get(f"/reports/{key}/print/").content.decode()
    assert not ACCIDENTS.shows_count and not POISONING.shows_count
