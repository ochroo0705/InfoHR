"""Who is doing the current request, and from which IP. Read by accounts.audit.record().

Set by the request middleware (or a login/logout signal) and cleared after each request, so that
code deep inside a request can write system-log entries without passing the user along.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from accounts.models import User

_user: ContextVar[User | None] = ContextVar("audit_user", default=None)
_ip: ContextVar[str | None] = ContextVar("audit_ip", default=None)


def set_context(user: User | None, ip: str | None) -> None:
    """Anonymous visitors (and None) count as no user."""
    if user is not None and not user.is_authenticated:
        user = None
    _user.set(user)
    _ip.set(ip)


def clear_context() -> None:
    set_context(None, None)


@contextmanager
def system() -> Iterator[None]:
    """Work that no visitor started (the daily MACS sync, run inside a request): logged with no actor and no IP,
    and the request's own user and IP are put back afterwards."""
    user_token = _user.set(None)
    ip_token = _ip.set(None)
    try:
        yield
    finally:
        _user.reset(user_token)
        _ip.reset(ip_token)


def current_user() -> User | None:
    return _user.get()


def current_ip() -> str | None:
    return _ip.get()
