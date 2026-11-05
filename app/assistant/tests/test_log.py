import pytest
from accounts.models import User
from django.conf import settings
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

from assistant.models import HelpQuestion, Outcome

PASSWORD = "Test-pass-1"  # noqa: S105

pytestmark = pytest.mark.django_db


def test_question_row_saves() -> None:
    user = User.objects.create_user("help_user", password=PASSWORD)
    row = HelpQuestion(user=user, question="яаж чөлөө бүртгэх вэ", outcome=Outcome.NONE)
    row.save()
    row.refresh_from_db()
    assert row.asked_at is not None
    assert row.entry == ""
    assert row.duration_ms == 0


def test_admin_group_may_view_log() -> None:
    perms = {"codename": "view_helpquestion", "content_type__app_label": "assistant"}
    assert Group.objects.get(name="Admin").permissions.filter(**perms).exists()
    assert not Group.objects.get(name="HR").permissions.filter(**perms).exists()


def test_admin_list_is_read_only(client: Client) -> None:
    admin_user = User.objects.create_superuser("help_admin", "help_admin@example.com", PASSWORD)
    client.force_login(admin_user)
    assert client.get(reverse("admin:assistant_helpquestion_changelist")).status_code == 200
    assert client.get(reverse("admin:assistant_helpquestion_add")).status_code == 403


def test_settings_types() -> None:
    assert isinstance(settings.ASSISTANT_TIMEOUT, int)
    for name in ("ASSISTANT_PROVIDER", "ASSISTANT_API_KEY", "ASSISTANT_MODEL"):
        assert isinstance(getattr(settings, name), str)
