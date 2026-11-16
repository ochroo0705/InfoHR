"""The report corrections switch (CompanySettings.report_corrections): on by default."""

import pytest

from employees.models import CompanySettings

pytestmark = pytest.mark.django_db


def test_report_corrections_defaults_to_on() -> None:
    assert CompanySettings.get().report_corrections is True
