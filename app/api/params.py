"""Small parsers for the query strings the API routes read, shared by the routers that page their lists."""

from logs.employee_query import PAGE_MAX_OFFSET


def batch_offset(raw: str) -> int:
    """A non-negative number up to PAGE_MAX_OFFSET, else 0 (a bad, negative or too large offset starts at batch one)."""
    if not raw.isdecimal() or len(raw) > 18:
        return 0
    value = int(raw)
    return value if value <= PAGE_MAX_OFFSET else 0
