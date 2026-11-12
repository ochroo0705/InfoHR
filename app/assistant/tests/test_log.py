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


def test_question_row_keeps_token_counts() -> None:
    row = HelpQuestion.objects.create(question="q", outcome=Outcome.NONE, tokens_in=310, tokens_out=42)
    row.refresh_from_db()
    assert (row.tokens_in, row.tokens_out) == (310, 42)
    assert HelpQuestion.objects.create(question="q2", outcome=Outcome.NONE).tokens_in == 0


def test_answer_logs_only_its_own_tokens() -> None:
    from datetime import date

    from assistant import services
    from assistant.providers import Choice
    from assistant.tests.helpers import plan_from_choice

    user = User.objects.create_user("tok_user", password=PASSWORD)

    class Counting:
        name = "counting"
        model = "m"
        tokens_in = 1000  # earlier questions on the same provider object
        tokens_out = 100

        def plan(self, *args: object, **kwargs: object) -> object:
            self.tokens_in += 80
            self.tokens_out += 9
            return plan_from_choice(Choice("", "", ""))

    services.answer(user, "яаж чөлөө бүртгэх вэ", date(2026, 11, 9), Counting())  # type: ignore[arg-type]
    row = HelpQuestion.objects.get(user=user)
    assert (row.tokens_in, row.tokens_out) == (80, 9)
