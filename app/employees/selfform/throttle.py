"""A per-IP counter in Django's cache, used to slow down guessing of self-form tokens.

The counter lives in the cache (per process, cleared on restart), which is enough to stop a casual loop of
guesses. It is not a hard security boundary: the tokens are long and random.
"""

import hashlib

from django.core.cache import cache


def allow(ip: str | None, bucket: str, *, limit: int, window_seconds: int) -> bool:
    """True while this IP has made at most `limit` calls in `bucket` within the window. An unknown IP counts as one."""
    digest = hashlib.sha256(f"{bucket}|{ip or 'unknown'}".encode()).hexdigest()
    key = f"selfform-throttle:{digest}"
    if cache.add(key, 1, timeout=window_seconds):
        return 1 <= limit
    try:
        count = cache.incr(key)
    except ValueError:  # the window ended between add and incr: start a new one
        cache.set(key, 1, timeout=window_seconds)
        count = 1
    return count <= limit
