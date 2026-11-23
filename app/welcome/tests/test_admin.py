from types import SimpleNamespace
from typing import Any, cast

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from welcome.models import DemoRequest

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser() -> Any:
    # No password: force_login below is the only way in, so no credential is needed.
    return get_user_model().objects.create_superuser("welcome-admin", password=None, is_active=True)


def _welcome_sidebar_item() -> dict[str, Any]:
    unfold = cast(dict[str, Any], settings.UNFOLD)  # typed as object in settings.py
    for section in unfold["SIDEBAR"]["navigation"]:
        for item in section["items"]:
            if item["title"] == "Демо хүсэлтүүд":
                found: dict[str, Any] = item
                return found
    raise AssertionError("welcome sidebar item is missing")


def test_changelist_lists_demo_requests(client: Client, superuser: Any) -> None:
    DemoRequest.objects.create(name="Б. Саруул", email="a@b.mn", organisation="Тест ХХК")
    client.force_login(superuser)
    response = client.get(reverse("admin:welcome_demorequest_changelist"))
    assert response.status_code == 200
    assert "Тест ХХК".encode() in response.content


def test_add_page_is_forbidden(client: Client, superuser: Any) -> None:
    client.force_login(superuser)
    response = client.get(reverse("admin:welcome_demorequest_add"))
    assert response.status_code == 403


def test_sidebar_item_needs_view_permission() -> None:
    staff = get_user_model().objects.create_user("welcome-staff", password=None, is_staff=True)
    permission = _welcome_sidebar_item()["permission"]
    assert not permission(SimpleNamespace(user=staff))

    view_perm = Permission.objects.get(codename="view_demorequest", content_type__app_label="welcome")
    staff.user_permissions.add(view_perm)
    fresh = get_user_model().objects.get(pk=staff.pk)  # reload so the permission cache is empty
    assert permission(SimpleNamespace(user=fresh))
