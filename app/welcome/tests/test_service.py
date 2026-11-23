import pytest
from django.core import mail
from pytest_django.fixtures import SettingsWrapper

from welcome import service
from welcome.models import DemoRequest

pytestmark = pytest.mark.django_db

VISITOR_EMAIL = "visitor@example.mn"


def _create(*, name: str = "Б. Саруул", email: str = VISITOR_EMAIL, organisation: str = "Тест ХХК") -> DemoRequest:
    return service.create_request(
        name=name,
        email=email,
        organisation=organisation,
        phone="99112233",
        size_band="11-50",
        note="Сонирхож байна",
        ip="127.0.0.1",
    )


def test_saves_and_mails(settings: SettingsWrapper) -> None:
    settings.EMAIL_HOST = "smtp.test"
    settings.DEMO_REQUEST_NOTIFY = ["hr@x.mn"]

    req = _create()

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert "Тест ХХК" in message.subject
    assert message.to == ["hr@x.mn"]
    assert DemoRequest.objects.filter(pk=req.pk).exists()
    req.refresh_from_db()
    assert req.mail_status == "sent"
    assert req.mail_error == ""


def test_not_configured_when_no_recipients(settings: SettingsWrapper) -> None:
    settings.EMAIL_HOST = "smtp.test"
    settings.DEMO_REQUEST_NOTIFY = []

    req = _create()

    assert DemoRequest.objects.filter(pk=req.pk).exists()
    req.refresh_from_db()
    assert req.mail_status == "not_configured"
    assert len(mail.outbox) == 0


def test_mail_failure_keeps_request(settings: SettingsWrapper, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.EMAIL_HOST = "smtp.test"
    settings.DEMO_REQUEST_NOTIFY = ["hr@x.mn"]

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(service, "send_mail", boom)

    req = _create()

    assert DemoRequest.objects.filter(pk=req.pk).exists()
    req.refresh_from_db()
    assert req.mail_status == "failed"
    assert req.mail_error == "boom"


def test_trims_and_keeps_unicode(settings: SettingsWrapper) -> None:
    settings.EMAIL_HOST = ""
    settings.DEMO_REQUEST_NOTIFY = []

    req = _create(name="  Ө. Үүрцайх  ")

    req.refresh_from_db()
    assert req.name == "Ө. Үүрцайх"


def test_no_mail_to_visitor(settings: SettingsWrapper) -> None:
    settings.EMAIL_HOST = "smtp.test"
    settings.DEMO_REQUEST_NOTIFY = ["hr@x.mn"]

    _create()

    assert len(mail.outbox) == 1
    for message in mail.outbox:
        assert VISITOR_EMAIL not in message.recipients()


def test_clean_recipients_strips_and_drops_blanks() -> None:
    assert service.clean_recipients([" a@x.mn ", "", "b@x.mn", "   "]) == ["a@x.mn", "b@x.mn"]


def test_recipients_with_spaces_are_mailed_clean(settings: SettingsWrapper) -> None:
    settings.EMAIL_HOST = "smtp.test"
    settings.DEMO_REQUEST_NOTIFY = [" hr@x.mn", "ops@x.mn "]

    req = _create()

    assert mail.outbox[0].to == ["hr@x.mn", "ops@x.mn"]
    req.refresh_from_db()
    assert req.mail_status == "sent"


def test_newline_in_organisation_is_mailed_as_one_line_subject(settings: SettingsWrapper) -> None:
    settings.EMAIL_HOST = "smtp.test"
    settings.DEMO_REQUEST_NOTIFY = ["hr@x.mn"]

    req = _create(organisation="Тест\nХХК")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Шинэ демо хүсэлт: Тест ХХК"
    req.refresh_from_db()
    assert req.mail_status == "sent"
    assert req.mail_error == ""
