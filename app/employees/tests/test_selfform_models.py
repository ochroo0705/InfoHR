"""Employee self-form data model: the invitation table and the self-form settings on CompanySettings."""

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from employees.models import CompanySettings, SelfFormInvitation

pytestmark = pytest.mark.django_db


def test_invitation_defaults() -> None:
    row = SelfFormInvitation.objects.create(token="t" * 32, label="Бат", expires_at=timezone.now())
    assert row.status == "open"
    assert row.answers == "{}"
    assert row.employee_id is None


def test_token_is_unique() -> None:
    now = timezone.now()
    SelfFormInvitation.objects.create(token="t" * 32, label="Бат", expires_at=now)
    with pytest.raises(IntegrityError), transaction.atomic():
        SelfFormInvitation.objects.create(token="t" * 32, label="Дорж", expires_at=now)


def test_company_settings_defaults() -> None:
    row = CompanySettings.get()
    assert row.selfform_retention_days == 30
    assert row.selfform_default_hours == 72
    assert row.selfform_base_url == ""
    assert row.selfform_notice == ""


def test_rejected_status_is_labelled_tatgalzsan() -> None:
    from employees.models import SelfFormStatus

    assert SelfFormStatus.REJECTED.label == "Татгалзсан"
