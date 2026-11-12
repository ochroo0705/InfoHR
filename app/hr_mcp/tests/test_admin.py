"""Admin screens for MCP tokens and the call log: superuser only, the raw token shown once, the hash never shown."""

import hashlib
import re
from typing import Any

import pytest
from accounts.models import User
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import Client, RequestFactory
from django.urls import reverse

from hr_mcp.models import McpCall, McpToken
from hr_mcp.tokens import issue_token

PASSWORD = "x-long-pass-123"  # noqa: S105

pytestmark = pytest.mark.django_db

TOKEN_SHOWN = re.compile(r"Токен: <code>(mhc_[\w-]+)</code>")


@pytest.fixture
def superuser(client: Client) -> User:
    user = User.objects.create_superuser("mcp_admin", password=PASSWORD)
    client.force_login(user)
    return user


@pytest.fixture
def target() -> User:
    return User.objects.create_user("mcp_target", password=PASSWORD)


def test_add_form_asks_only_user_and_name(client: Client, superuser: User) -> None:
    response = client.get(reverse("admin:hr_mcp_mcptoken_add"))

    assert response.status_code == 200
    assert set(response.context["adminform"].form.fields) == {"user", "name"}


def test_add_token_shows_raw_once(client: Client, superuser: User, target: User) -> None:
    response = client.post(
        reverse("admin:hr_mcp_mcptoken_add"),
        {"user": target.pk, "name": "Claude Desktop"},
        follow=True,
    )

    row = McpToken.objects.get(name="Claude Desktop")
    html = response.content.decode("utf-8")
    shown = TOKEN_SHOWN.search(html)
    assert shown is not None
    raw = shown.group(1)
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == row.token_hash
    assert row.token_hash not in html

    again = client.get(reverse("admin:hr_mcp_mcptoken_changelist")).content.decode("utf-8")
    assert raw not in again
    assert "Зөвхөн одоо харагдана" not in again


def test_token_list_shows_prefix_not_hash(client: Client, superuser: User, target: User) -> None:
    row, raw = issue_token(target, "Claude Desktop")

    html = client.get(reverse("admin:hr_mcp_mcptoken_changelist")).content.decode("utf-8")

    assert row.prefix in html
    assert row.token_hash not in html
    assert raw not in html


def test_revoke_action_sets_revoked_at(client: Client, superuser: User, target: User) -> None:
    row, _raw = issue_token(target, "Claude Desktop")

    client.post(
        reverse("admin:hr_mcp_mcptoken_changelist"),
        {"action": "revoke_selected", "_selected_action": [row.pk], "index": 0},
    )

    row.refresh_from_db()
    assert row.revoked_at is not None


def test_call_log_is_read_only(client: Client, superuser: User) -> None:
    response = client.get(reverse("admin:hr_mcp_mcpcall_add"))

    assert response.status_code == 403


def test_call_log_list_is_visible_to_superuser(client: Client, superuser: User, target: User) -> None:
    row, _raw = issue_token(target, "Claude Desktop")
    McpCall.objects.create(token=row, tool="sql", sql="SELECT 1", ok=True, row_count=1, duration_ms=3)

    response = client.get(reverse("admin:hr_mcp_mcpcall_changelist"))

    assert response.status_code == 200
    assert "sql" in response.content.decode("utf-8")


def test_non_superuser_cannot_see(client: Client, target: User) -> None:
    staff = User.objects.create_user("mcp_staff", password=PASSWORD, is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="view_mcptoken", content_type__app_label="hr_mcp"))
    client.force_login(staff)

    assert client.get(reverse("admin:hr_mcp_mcptoken_changelist")).status_code == 403
    assert client.get(reverse("admin:hr_mcp_mcpcall_changelist")).status_code == 403


def test_token_cannot_be_deleted(rf: RequestFactory, client: Client, superuser: User, target: User) -> None:
    row, _raw = issue_token(target, "Claude Desktop")

    assert client.get(reverse("admin:hr_mcp_mcptoken_delete", args=[row.pk])).status_code == 403
    request = rf.get("/admin/")
    request.user = superuser
    assert "delete_selected" not in admin.site._registry[McpToken].get_actions(request)
    assert McpToken.objects.filter(pk=row.pk).exists()


def test_mcp_sidebar_group_is_superuser_only(rf: RequestFactory, superuser: User) -> None:
    def group_items(user: User) -> list[dict[str, Any]]:
        request = rf.get("/admin/")
        request.user = user
        groups: list[dict[str, Any]] = admin.site.get_sidebar_list(request)  # type: ignore[attr-defined]  # unfold adds it
        group = next(g for g in groups if g["title"] == "MCP хандалт")
        items: list[dict[str, Any]] = group["items"]
        return items

    assert group_items(superuser) and all(item["has_permission"] for item in group_items(superuser))
    staff = User.objects.create_user("mcp_sidebar_staff", password=PASSWORD, is_staff=True)
    assert not any(item["has_permission"] for item in group_items(staff))


def test_token_detail_is_read_only_and_hides_hash(client: Client, superuser: User, target: User) -> None:
    row, _raw = issue_token(target, "Claude Desktop")

    response = client.get(reverse("admin:hr_mcp_mcptoken_change", args=[row.pk]))

    assert response.status_code == 200
    assert row.token_hash not in response.content.decode("utf-8")
    assert client.post(reverse("admin:hr_mcp_mcptoken_change", args=[row.pk]), {"name": "x"}).status_code == 403
    row.refresh_from_db()
    assert row.name == "Claude Desktop"
