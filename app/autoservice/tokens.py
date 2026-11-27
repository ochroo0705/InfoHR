"""Bearer tokens for the Online Auto Service API.

A token is a signed, time-limited payload (django.core.signing). Nothing is stored in a database, so issuing
one never writes to the shared MACS tables. A token cannot be revoked before it expires; the lifetime is
settings.AUTOSERVICE_TOKEN_TTL seconds (default 12 hours).
"""

import time
from dataclasses import dataclass

from django.conf import settings
from django.core import signing

SALT = "autoservice.token.v1"
DEFAULT_TTL = 12 * 60 * 60


@dataclass(frozen=True)
class TokenUser:
    username: str
    rights: str
    expires_at: int  # seconds since the epoch


def ttl() -> int:
    return int(getattr(settings, "AUTOSERVICE_TOKEN_TTL", DEFAULT_TTL))


def issue(username: str, rights: str) -> tuple[str, int]:
    """A signed token for this user and the time (epoch seconds) it stops working."""
    expires_at = int(time.time()) + ttl()
    return signing.dumps({"u": username, "r": rights, "x": expires_at}, salt=SALT, compress=True), expires_at


def read(token: str) -> TokenUser | None:
    """The user a token was issued for, or None when it is forged, damaged or expired."""
    try:
        data = signing.loads(token, salt=SALT, max_age=ttl())
        user = TokenUser(str(data["u"]), str(data["r"]), int(data["x"]))
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None
    return user if user.expires_at > time.time() else None
