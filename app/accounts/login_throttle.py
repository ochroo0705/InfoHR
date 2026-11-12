"""Slow down password guessing: failed logins are counted per IP+username and per IP, in a shared cache.

Two limits inside one fixed window: USER_LIMIT failures for the same username from the same IP, and IP_LIMIT
failures from one IP over all usernames (someone trying many accounts). While a limit is reached the login
backend refuses every attempt, even with the right password. A good login clears the IP+username counter.
The counters live in the file cache "throttle", so all workers on the server share them and a restart keeps them.
"""

import hashlib

from django.core.cache import caches
from django.http import HttpRequest

CACHE_ALIAS = "throttle"
USER_LIMIT = 5
IP_LIMIT = 20
WINDOW_SECONDS = 15 * 60
LOCK_MESSAGE = "Нэвтрэх оролдлого хэт олон удаа буруу боллоо. 15 минутын дараа дахин оролдоно уу."


def _ip(request: HttpRequest | None) -> str:
    from accounts.middleware import client_ip  # late: middleware imports models

    return (client_ip(request) if request is not None else None) or "unknown"


def _key(*parts: str) -> str:
    return "login-throttle:" + hashlib.sha256("|".join(parts).encode()).hexdigest()


def _user_key(request: HttpRequest | None, username: str) -> str:
    return _key("user", _ip(request), username.strip().lower()[:150])


def _ip_key(request: HttpRequest | None) -> str:
    return _key("ip", _ip(request))


def is_locked(request: HttpRequest | None, username: str) -> bool:
    cache = caches[CACHE_ALIAS]
    user_failures: int = cache.get(_user_key(request, username), 0)
    ip_failures: int = cache.get(_ip_key(request), 0)
    return user_failures >= USER_LIMIT or ip_failures >= IP_LIMIT


def _count(key: str) -> None:
    cache = caches[CACHE_ALIAS]
    if cache.add(key, 1, timeout=WINDOW_SECONDS):
        return
    try:
        cache.incr(key)
    except ValueError:  # the window ended between add and incr: start a new one
        cache.set(key, 1, timeout=WINDOW_SECONDS)


def record_failure(request: HttpRequest | None, username: str) -> None:
    _count(_user_key(request, username))
    _count(_ip_key(request))


def reset(request: HttpRequest | None, username: str) -> None:
    caches[CACHE_ALIAS].delete(_user_key(request, username))
