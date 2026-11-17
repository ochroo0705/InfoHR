"""The shared parts of a password change, used by the web form and by the API."""

from typing import Any

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm
from django.http import HttpRequest

from accounts.audit import Category, record_safe
from accounts.forms import ChangePasswordForm, NewPasswordForm
from accounts.models import User


def form_class_for(user: User) -> "type[SetPasswordForm[Any]]":
    """A temporary password is replaced without asking for the old one; a normal change asks for it."""
    if getattr(user, "must_change_password", False):
        return NewPasswordForm
    return ChangePasswordForm


def finish_password_change(request: HttpRequest, user: User) -> None:
    """Call after the form has saved the new password: keep this session logged in, clear the forced-change flag,
    and write the audit entry. No password text is recorded: the entry only says the user changed their own password."""
    update_session_auth_hash(request, user)
    user.must_change_password = False
    user.save(update_fields=["must_change_password"])
    record_safe(Category.ACCESS, "password_changed", actor=user, target_type="user", target_label=user.username)
