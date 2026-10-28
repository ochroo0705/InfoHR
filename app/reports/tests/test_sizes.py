from collections.abc import Callable
from typing import Any

import pytest
from accounts.models import User
from django.test import Client
from employees.models import Employee
from employees.tests.conftest import named
from macs.models import ClothesSize

from reports.filters import Filters
from reports.sizes import REPORT

from .conftest import legacy

pytestmark = pytest.mark.django_db


def _counts(user: User) -> dict[tuple[str, str, str], int]:
    return {(line.kind, line.gender, line.size): line.qty for line in REPORT.rows(user, Filters())}


def test_counts_per_kind_gender_and_size(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    large = named(ClothesSize, "L")
    medium = named(ClothesSize, "M")
    legacy(actor, job_values, gender="M", clothing_size=large)
    legacy(actor, job_values, gender="M", clothing_size=large)
    legacy(actor, job_values, gender="F", clothing_size=medium)
    counts = _counts(hr_user)
    assert counts[("Хувцас", "Эрэгтэй", "L")] == 2
    assert counts[("Хувцас", "Эмэгтэй", "M")] == 1
    assert counts[("Гутал", "Эрэгтэй", "Заагаагүй")] == 2
    assert counts[("Гутал", "Эмэгтэй", "Заагаагүй")] == 1


def test_left_person_is_not_counted(
    hr_user: User, actor: User, job_values: dict[str, Any], left_employee: Employee
) -> None:
    large = named(ClothesSize, "L")
    legacy(actor, job_values, gender="M", clothing_size=large)  # the working person
    assert _counts(hr_user) == {("Хувцас", "Эрэгтэй", "L"): 1, ("Гутал", "Эрэгтэй", "Заагаагүй"): 1}


def test_gender_unknown_label(hr_user: User, actor: User, job_values: dict[str, Any]) -> None:
    legacy(actor, job_values, gender=None)
    assert _counts(hr_user) == {("Хувцас", "Тодорхойгүй", "Заагаагүй"): 1, ("Гутал", "Тодорхойгүй", "Заагаагүй"): 1}


def test_accountant_refused(client: Client, login_as: Callable[..., User]) -> None:
    login_as(client, "Accountant", "acc")
    assert client.get("/reports/sizes/").status_code == 403


def test_page_shows_title(client: Client, login_hr: User, hired: Employee) -> None:
    response = client.get("/reports/sizes/")
    assert response.status_code == 200
    assert "Гутал, хувцасны хэмжээний судалгаа" in response.content.decode()
