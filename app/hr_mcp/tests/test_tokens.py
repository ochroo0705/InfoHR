import hashlib

import pytest
from accounts.models import User

from hr_mcp.models import McpToken
from hr_mcp.tokens import authenticate_token, issue_token, revoke

PASSWORD = "x-long-pass-123"  # noqa: S105


@pytest.fixture
def user() -> User:
    return User.objects.create_user("mcp_token_user", password=PASSWORD)


@pytest.mark.django_db
def test_issue_returns_raw_once(user: User) -> None:
    row, raw = issue_token(user, "Claude Desktop")

    assert raw.startswith("mhc_")
    assert row.token_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert raw not in row.token_hash
    assert row.prefix == raw[:8]
    assert not McpToken.objects.filter(token_hash=raw).exists()


@pytest.mark.django_db
def test_authenticate_valid(user: User) -> None:
    row, raw = issue_token(user, "Claude Desktop")
    assert row.last_used_at is None

    result = authenticate_token(raw)

    assert result is not None
    assert result.pk == user.pk
    row.refresh_from_db()
    assert row.last_used_at is not None


@pytest.mark.django_db
def test_unknown_and_empty_do_not_authenticate() -> None:
    assert authenticate_token("") is None
    assert authenticate_token("mhc_nope") is None


@pytest.mark.django_db
def test_revoked_and_inactive_tokens_do_not_authenticate(user: User) -> None:
    row, raw = issue_token(user, "Claude Desktop")
    revoke(row)
    assert authenticate_token(raw) is None

    active_row, active_raw = issue_token(user, "Second client")
    assert authenticate_token(active_raw) is not None
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert authenticate_token(active_raw) is None
    assert McpToken.objects.get(pk=active_row.pk).revoked_at is None
