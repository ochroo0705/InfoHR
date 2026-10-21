"""manage.py copy_educ_to_qualification: old educ (+ HR EducationExt) rows become qualification rows (Task 7)."""

from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from macs.models import EducRow, EduType, ProfessionType, QualificationRow

from employees.models import EducationExt, Employee

pytestmark = pytest.mark.django_db


def _educ(employee: Employee, start_year: int = 2010, **ext: Any) -> EducRow:
    edu_type = EduType.objects.get_or_create(name="Бакалавр")[0]
    row = EducRow.objects.create(employee=employee, edu_type=edu_type, start_year=start_year)
    if ext:
        EducationExt.objects.create(educ=row, **ext)
    return row


def _run(*args: str) -> str:
    out = StringIO()
    call_command("copy_educ_to_qualification", *args, stdout=out)
    return out.getvalue()


def test_copy_creates_qualification(hired: Employee) -> None:
    _educ(hired, 2010, school="МУИС", field="", graduation_year=2014)

    out = _run()

    row = QualificationRow.objects.get(employee=hired)
    assert (row.org_name, row.start_year, row.end_year) == ("МУИС", 2010, 2014)
    assert row.profession_type_id is None
    assert "copied" in out


def test_copy_is_rerunnable(hired: Employee) -> None:
    _educ(hired, 2010, school="МУИС", field="", graduation_year=2014)

    _run()
    out = _run()

    assert QualificationRow.objects.filter(employee=hired).count() == 1
    assert "skipped" in out


def test_copy_dry_run_writes_nothing(hired: Employee) -> None:
    _educ(hired, 2010, school="МУИС", field="", graduation_year=2014)

    out = _run("--dry-run")

    assert not QualificationRow.objects.filter(employee=hired).exists()
    assert "copied" in out or "would copy" in out
    # The system user is only created when a write happens.
    from accounts.models import User

    assert not User.objects.filter(username="system").exists()


def test_copy_long_school_cut_and_reported(hired: Employee) -> None:
    school = "А" * 80
    _educ(hired, 2010, school=school, field="", graduation_year=2014)

    out = _run()

    row = QualificationRow.objects.get(employee=hired)
    assert row.org_name == "А" * 60
    assert "cut to 60" in out
    # Re-running still matches the cut name, so nothing is copied twice.
    _run()
    assert QualificationRow.objects.filter(employee=hired).count() == 1


def test_copy_field_matched_to_profession_type(hired: Employee) -> None:
    profession = ProfessionType.objects.create(name="Инженер")
    _educ(hired, 2010, school="МУИС", field="инженер", graduation_year=2014)
    _educ(hired, 2012, school="ШУТИС", field="Хуульч", graduation_year=2016)

    out = _run()

    matched = QualificationRow.objects.get(employee=hired, start_year=2010)
    unmatched = QualificationRow.objects.get(employee=hired, start_year=2012)
    assert matched.profession_type_id == profession.pk
    assert unmatched.profession_type_id is None
    assert "field not matched" in out
    assert "Хуульч" in out
