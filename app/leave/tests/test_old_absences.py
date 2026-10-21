from datetime import date

import pytest
from accounts.models import User
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from employees.models import Employee
from macs.models import Absence, AbsenceType

from .conftest import make_employee

pytestmark = pytest.mark.django_db


def _hr() -> Client:
    u = User.objects.create_user("u_hr", password="x-long-pass-123")  # noqa: S106
    u.groups.add(Group.objects.get(name="HR"))
    c = Client()
    c.force_login(u)
    return c


def test_old_absence_rows_are_listed_read_only(employee: Employee) -> None:
    kind = AbsenceType.objects.create(name="Цалинтай чөлөө")
    Absence.objects.create(
        employee_id=employee.pk, absence_type=kind, from_date=date(2025, 3, 3), to_date=date(2025, 3, 5), note="Хурим"
    )
    Absence.objects.create(employee_id=employee.pk, absence_type=kind, from_date=date(2026, 1, 12))
    html = _hr().get(reverse("employees:detail", args=[employee.pk])).content.decode()
    assert "data-old-absences" in html
    assert "2025-03-03 – 2025-03-05" in html and "Хурим" in html and "Цалинтай чөлөө" in html
    assert html.index("2026-01-12") < html.index("2025-03-03")  # newest first
    assert "Зөвхөн харах" in html


def test_no_old_absence_rows_hides_the_block(employee: Employee) -> None:
    html = _hr().get(reverse("employees:detail", args=[employee.pk])).content.decode()
    assert "data-old-absences" not in html


def test_old_absences_of_another_employee_are_not_shown(actor: User, employee: Employee) -> None:
    other_employee = make_employee(actor, hired=date(2024, 5, 1), register_no="УБ88112233")
    kind = AbsenceType.objects.create(name="Өвчний")
    Absence.objects.create(employee_id=other_employee.pk, absence_type=kind, from_date=date(2025, 5, 5))
    html = _hr().get(reverse("employees:detail", args=[employee.pk])).content.decode()
    assert "data-old-absences" not in html
