"""Check a typed password against the MACS user table (SECURITY).

ASSUMPTION (to confirm with the desktop program): SECURITY.PASSW holds the login password as plain digits.
SECURITY.FPASS is a second, differently shaped value that this module does NOT accept: the desktop program's
use of it is unknown, so a user whose real password lives only there cannot log in here (fails closed).
"""

import hmac


def matches(stored: str | None, given: str) -> bool:
    """True when `given` equals the stored password. An empty stored value never matches."""
    stored = (stored or "").strip()
    given = given.strip()
    if not stored or not given:
        return False
    return hmac.compare_digest(stored.encode(), given.encode())
