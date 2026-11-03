import importlib

import pytest
from accounts.roles import ACCOUNTANT, ADMIN, AUDITOR, EMPLOYEE, HR
from django.apps import apps
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from macs.models import Department, Position

from recruitment.models import (
    Candidate,
    CandidateComment,
    CandidateEvent,
    CandidateFile,
    RecruitmentSettings,
    Stage,
    Vacancy,
    VacancyStatus,
)

migration = importlib.import_module("recruitment.migrations.0002_permissions")


@pytest.fixture
def vacancy(db: None) -> Vacancy:
    return Vacancy.objects.create(
        title="Нягтлан",
        position=Position.objects.create(name="Нягтлан"),
        department=Department.objects.create(name="Санхүү"),
    )


def _codes(group_name: str) -> set[str]:
    return set(
        Group.objects.get(name=group_name)
        .permissions.filter(content_type__app_label="recruitment")
        .values_list("codename", flat=True)
    )


def test_stage_labels_are_exact() -> None:
    assert {s.value: s.label for s in Stage} == {
        "new": "Шинэ",
        "screening": "Шалгаруулалт",
        "interview": "Ярилцлага",
        "offer": "Санал",
        "hired": "Ажилд авсан",
        "rejected": "Татгалзсан",
        "withdrawn": "Өөрөө татгалзсан",
    }


def test_models_save_with_defaults(vacancy: Vacancy) -> None:
    assert vacancy.status == VacancyStatus.OPEN
    assert vacancy.headcount == 1
    candidate = Candidate.objects.create(vacancy=vacancy, surname="Бат", given_name="Сараа")
    assert candidate.stage == Stage.NEW
    assert candidate.closed_at is None
    CandidateEvent.objects.create(candidate=candidate, from_stage="", to_stage=Stage.NEW)
    CandidateComment.objects.create(candidate=candidate, text="Сайн")
    CandidateFile.objects.create(candidate=candidate, file="1/cv.pdf", name="cv.pdf")
    assert candidate.events.count() == candidate.comments.count() == candidate.files.count() == 1


def test_headcount_must_be_at_least_one(vacancy: Vacancy) -> None:
    vacancy.headcount = 0
    with pytest.raises(ValidationError):
        vacancy.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        Vacancy.objects.filter(pk=vacancy.pk).update(headcount=0)


def test_settings_get_creates_row_with_twelve_months(db: None) -> None:
    assert not RecruitmentSettings.objects.exists()
    row = RecruitmentSettings.get()
    assert row.pk == 1
    assert row.retention_months == 12
    assert RecruitmentSettings.get().pk == 1
    assert RecruitmentSettings.objects.count() == 1


@pytest.mark.parametrize("months", [0, 121])
def test_retention_months_validated(db: None, months: int) -> None:
    row = RecruitmentSettings(pk=1, retention_months=months)
    with pytest.raises(ValidationError):
        row.full_clean()


def test_hr_and_admin_have_permission_others_do_not(db: None) -> None:
    assert _codes(HR) == {"manage_recruitment"}
    assert _codes(ADMIN) == {"manage_recruitment"}
    assert _codes(ACCOUNTANT) == set()
    assert _codes(AUDITOR) == set()
    assert _codes(EMPLOYEE) == set()


def test_migration_tolerates_missing_groups_and_reverses(db: None) -> None:
    Group.objects.filter(name=HR).update(name="HR-renamed")  # checklist tasks protect the HR group from deletion
    migration.revoke(apps, None)
    assert _codes(ADMIN) == set()
    migration.grant(apps, None)  # no HR group: must not crash
    assert _codes(ADMIN) == {"manage_recruitment"}
