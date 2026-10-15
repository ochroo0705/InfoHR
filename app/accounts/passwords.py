"""Temporary passwords (scoping D-014): the system makes one, it is shown once, the user must change it.
Nobody chooses another person's password; the plain password is never logged."""

import secrets

from accounts.models import User

# No 0/O, 1/l/I look-alikes, so the password can be read out loud or copied from paper.
TEMP_ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TEMP_LENGTH = 10


def temp_password() -> str:
    """Random, but always with a lowercase letter, an uppercase letter and a digit (the password rule)."""
    while True:
        password = "".join(secrets.choice(TEMP_ALPHABET) for _ in range(TEMP_LENGTH))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
        ):
            return password


def set_temp_password(user: User, *, save: bool = True) -> str:
    """Give `user` a new temporary password and return it (to show once)."""
    password = temp_password()
    user.set_password(password)
    user.must_change_password = True
    if save:
        user.save(update_fields=["password", "must_change_password"])
    return password
