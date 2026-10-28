from collections.abc import Callable
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from django.utils import timezone
from employees.services import macs_writes
from macs.models import Branch, NazgRow, Position

from reports.engineers import REPORT
from reports.filters import Filters

from .conftest import legacy

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_budget_rows() -> None:
    """The test database may hold production budget rows; each test starts with none."""
    NazgRow.objects.all().delete()


def _budget(position: Position, kind: str, qty: int, branch: Branch, year: int | None = None) -> NazgRow:
    return NazgRow.objects.create(
        kind=kind,
        qty=qty,
        year=year or timezone.localdate().year,
        position=position,
        branch=branch,
    )


def _lines(user: User, f: Filters) -> dict[tuple[str, str], tuple[int, int]]:
    return {(x.kind, x.position.name): (x.budget, x.executed) for x in REPORT.rows(user, f)}


def test_budget_is_summed_over_branches_per_kind_and_position(hr_user: User) -> None:
    """The table allows one row per kind, year, branch and position, so the sum runs across the branches."""
    engineer = macs_writes.save_position("Инженер")
    _budget(engineer, "Main", 2, Branch.objects.create(name="Хойд"))
    _budget(engineer, "Main", 3, Branch.objects.create(name="Өмнө"))
    assert _lines(hr_user, Filters()) == {("Main", "Инженер"): (5, 0)}


def test_year_filter_and_default_year(hr_user: User) -> None:
    branch = Branch.objects.create(name="Төв")
    engineer = macs_writes.save_position("Инженер")
    _budget(engineer, "Main", 1, branch)
    _budget(engineer, "Main", 7, branch, year=timezone.localdate().year - 1)
    assert _lines(hr_user, Filters()) == {("Main", "Инженер"): (1, 0)}
    assert _lines(hr_user, Filters(year=timezone.localdate().year - 1)) == {("Main", "Инженер"): (7, 0)}


def test_executed_counts_non_contract_people_for_main_and_contract_for_temporary(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    branch = Branch.objects.create(name="Төв")
    accountant = job_values["position"]
    _budget(accountant, "Main", 2, branch)
    _budget(accountant, "Temporary", 1, branch)
    legacy(actor, job_values)  # not contract staff: Main
    legacy(actor, job_values, contract_flag="yes")  # contract staff: Temporary
    assert _lines(hr_user, Filters()) == {
        ("Main", "Нягтлан"): (2, 1),
        ("Temporary", "Нягтлан"): (1, 1),
    }


def test_branch_filter_limits_budget_and_executed(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    north = Branch.objects.create(name="Хойд")
    south = Branch.objects.create(name="Өмнө")
    accountant = job_values["position"]
    _budget(accountant, "Main", 2, north)
    _budget(accountant, "Main", 3, south)
    legacy(actor, job_values, branch=north)
    legacy(actor, job_values, branch=south)
    assert _lines(hr_user, Filters(branch=north.pk)) == {("Main", "Нягтлан"): (2, 1)}


def test_person_in_a_position_without_budget_has_no_line(
    hr_user: User, actor: User, job_values: dict[str, Any]
) -> None:
    """Lines come only from budget rows: a person in a position with no budget row adds no line."""
    _budget(macs_writes.save_position("Инженер"), "Main", 2, Branch.objects.create(name="Төв"))
    legacy(actor, job_values)  # in «Нягтлан», which has no budget row
    assert _lines(hr_user, Filters()) == {("Main", "Инженер"): (2, 0)}


def test_employee_role_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Employee", "emp")
    assert client.get("/reports/engineers/").status_code == 403


def test_accountant_may_open(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc")
    assert client.get("/reports/engineers/").status_code == 200


def test_page_shows_title(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "hr")
    response = client.get("/reports/engineers/")
    assert response.status_code == 200
    assert "Инженер, техникийн ажилтны судалгаа" in response.content.decode()


def _engineers_card(page: str) -> str:
    """The catalogue card of the engineers report: the text from its marker up to the next card."""
    cards = page.split("data-report-card")[1:]
    return next(c for c in cards if 'href="/reports/engineers/"' in c)


def test_catalogue_marks_empty_budget(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "HR", "hr")
    card = _engineers_card(client.get("/reports/").content.decode())
    assert "бүртгэл алга" in card


def test_catalogue_card_loses_the_marker_once_a_budget_row_exists(
    client: Client, login_as: Callable[..., User]
) -> None:
    _budget(macs_writes.save_position("Инженер"), "Main", 1, Branch.objects.create(name="Төв"))
    login_as(client, "HR", "hr")
    card = _engineers_card(client.get("/reports/").content.decode())
    assert "бүртгэл алга" not in card


def test_note_says_the_people_counted_are_within_the_users_rights() -> None:
    assert REPORT.note is not None
    note = REPORT.note(Filters())
    assert "Орон тооны бүртгэл хуучин програмаас" in note
    assert "Харагдах ажилтны тоо нь таны эрхийн хүрээнд." in note
