"""Shared fixtures for the recruitment tests (the model tests build their own rows)."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from accounts.models import User
from django.contrib.auth.models import Permission
from employees.services import history, macs_writes
from macs.models import Department, Employee, Position
from pytest_django.fixtures import SettingsWrapper

from recruitment.models import Candidate, Vacancy


@pytest.fixture(autouse=True)
def _recruitment_files_tmp(settings: SettingsWrapper, tmp_path: Path) -> None:
    """Every test writes candidate files to a temporary folder, never to app/private."""
    settings.RECRUITMENT_FILES_ROOT = tmp_path / "recruitment"


@pytest.fixture
def actor(db: None) -> User:
    return User.objects.create_user("rec_actor", password="x-long-pass-123")  # noqa: S106


@pytest.fixture
def hr_user(db: None) -> User:
    user = User.objects.create_user("rec_hr", password="x-long-pass-123")  # noqa: S106
    user.user_permissions.add(Permission.objects.get(codename="manage_recruitment"))
    return user


def _hire(by: User, family: str, register_no: str) -> Employee:
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values: dict[str, Any] = {
        "family_name": family,
        "given_name": "Сараа",
        "register_no": register_no,
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
    }
    return history.hire(values, {}, start=date(2026, 1, 5), job=job, salary=Decimal("2500000"), by=by)


def make_manager(by: User, username: str, register_no: str) -> tuple[User, Employee]:
    """A login linked to its own employee record (a would-be hiring manager)."""
    user = User.objects.create_user(username, password="x-long-pass-123")  # noqa: S106
    employee = _hire(by, username.title(), register_no)
    employee.ext.user = user
    employee.ext.save()
    return user, employee


@pytest.fixture
def new_employee(actor: User) -> Employee:
    return _hire(actor, "Шинэ", "УБ11223344")


def make_vacancy(title: str = "Нягтлан", *, headcount: int = 1, manager: Employee | None = None) -> Vacancy:
    return Vacancy.objects.create(
        title=title,
        position=Position.objects.filter(name="Нягтлан").first() or Position.objects.create(name="Нягтлан"),
        department=Department.objects.filter(name="Санхүү").first() or Department.objects.create(name="Санхүү"),
        headcount=headcount,
        hiring_manager=manager,
    )


@pytest.fixture
def vacancy(db: None) -> Vacancy:
    return make_vacancy()


@pytest.fixture
def candidate(vacancy: Vacancy, actor: User) -> Candidate:
    from recruitment.services import pipeline

    return pipeline.add_candidate(vacancy, by=actor, surname="Дорж", given_name="Бат")
