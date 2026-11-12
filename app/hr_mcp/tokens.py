import hashlib
import secrets

from accounts.models import User
from django.utils import timezone

from hr_mcp.models import McpToken

TOKEN_PREFIX = "mhc_"  # noqa: S105  (a prefix, not a password)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_token(user: User, name: str) -> tuple[McpToken, str]:
    """Create a token for the user. The raw token is returned once here and never stored."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = McpToken.objects.create(user=user, name=name, prefix=raw[:8], token_hash=_hash(raw))
    return row, raw


def find_token(raw: str) -> McpToken | None:
    """Return the token row (with its user loaded), or None for an empty, unknown, revoked or inactive-user token."""
    if not raw:
        return None
    row = McpToken.objects.select_related("user").filter(token_hash=_hash(raw), revoked_at__isnull=True).first()
    if row is None or not row.user.is_active:
        return None
    McpToken.objects.filter(pk=row.pk).update(last_used_at=timezone.now())
    return row


def authenticate_token(raw: str) -> User | None:
    """Return the token's user, or None for an empty, unknown, revoked or inactive-user token."""
    row = find_token(raw)
    return row.user if row is not None else None


def revoke(token: McpToken) -> None:
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at"])
