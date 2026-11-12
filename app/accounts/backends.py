"""Login backend: a username longer than the user column cannot exist, so it cannot log in."""

from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from . import login_throttle
from .models import User


class LengthCheckedModelBackend(ModelBackend):
    """Django's ModelBackend. Firebird raises SQL -303 when a lookup value is longer than its column,
    so an over-long username is answered with "no user" here. authenticate() still sends
    user_login_failed, so the attempt is logged (the signal cuts the name to the column length)."""

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        max_length = getattr(User._meta.get_field(User.USERNAME_FIELD), "max_length", None)
        if username is not None and max_length and len(username) > max_length:
            return None
        if login_throttle.is_locked(request, username or ""):
            return None  # locked: refused even with the right password (accounts/login_throttle.py)
        return super().authenticate(request, username=username, password=password, **kwargs)
