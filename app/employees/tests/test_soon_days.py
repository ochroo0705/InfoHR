"""The «дөхсөн» window: how many days ahead a contract or probation end counts as near (CompanySettings.soon_days)."""

from typing import Any

import pytest

from employees.admin import CompanySettingsForm
from employees.models import CompanySettings

pytestmark = pytest.mark.django_db


def _form_data(soon_days: int) -> dict[str, Any]:
    row = CompanySettings.get()
    return {
        "soon_days": soon_days,
        "selfform_base_url": row.selfform_base_url,
        "selfform_notice": row.selfform_notice,
        "selfform_retention_days": row.selfform_retention_days,
        "selfform_default_hours": row.selfform_default_hours,
    }


def test_soon_days_defaults_to_30() -> None:
    assert CompanySettings.get().soon_days == 30


def test_form_rejects_0_and_366() -> None:
    for value in (0, 366):
        form = CompanySettingsForm(data=_form_data(value), instance=CompanySettings.get())
        assert form.is_valid() is False
        assert "soon_days" in form.errors


def test_form_accepts_1_and_365() -> None:
    for value in (1, 365):
        form = CompanySettingsForm(data=_form_data(value), instance=CompanySettings.get())
        assert form.is_valid() is True, form.errors
        assert form.cleaned_data["soon_days"] == value
