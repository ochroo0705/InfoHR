from datetime import UTC, datetime, timedelta

import pytest
from django.conf import settings

# Importing welcome.models raises when the app is not installed (flag off), so skip the module before the import.
if "welcome" not in settings.INSTALLED_APPS:
    pytest.skip("the welcome app is loaded only when PUBLIC_WELCOME=true", allow_module_level=True)

from welcome.models import DemoRequest  # noqa: E402

pytestmark = pytest.mark.django_db


def _request(**overrides):
    data = {"name": "Б. Саруул", "email": "a@b.mn", "organisation": "Тест ХХК", **overrides}
    return DemoRequest.objects.create(**data)


def test_saves_with_defaults() -> None:
    req = _request()
    req.refresh_from_db()
    assert req.mail_status == "pending"
    assert req.created_at is not None
    assert str(req) == "Тест ХХК — Б. Саруул"


def test_orders_newest_first() -> None:
    first = _request(name="Эхний")
    second = _request(name="Дараа")
    base = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
    DemoRequest.objects.filter(pk=first.pk).update(created_at=base)
    DemoRequest.objects.filter(pk=second.pk).update(created_at=base + timedelta(hours=1))
    ids = list(DemoRequest.objects.values_list("id", flat=True))
    assert ids == [second.pk, first.pk]
