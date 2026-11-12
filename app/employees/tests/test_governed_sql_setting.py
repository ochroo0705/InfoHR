"""The governed SQL switch (CompanySettings.governed_sql_enabled): off by default, saved from the admin form."""

from typing import Any

import pytest

from employees.admin import CompanySettingsForm
from employees.models import CompanySettings

pytestmark = pytest.mark.django_db


def _form_data(enabled: bool) -> dict[str, Any]:
    row = CompanySettings.get()
    return {
        "soon_days": row.soon_days,
        "governed_sql_enabled": enabled,
        "selfform_base_url": row.selfform_base_url,
        "selfform_notice": row.selfform_notice,
        "selfform_retention_days": row.selfform_retention_days,
        "selfform_default_hours": row.selfform_default_hours,
    }


def test_setting_defaults_to_off() -> None:
    assert CompanySettings.get().governed_sql_enabled is False


def test_admin_form_saves_the_setting() -> None:
    form = CompanySettingsForm(data=_form_data(True), instance=CompanySettings.get())
    assert form.is_valid(), form.errors
    form.save()
    assert CompanySettings.get().governed_sql_enabled is True
