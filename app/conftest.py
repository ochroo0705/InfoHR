import pytest
from pytest_django.fixtures import SettingsWrapper


@pytest.fixture(autouse=True)
def fast_password_hasher(settings: SettingsWrapper) -> None:
    """Tests create many logins; production-strength hashing made each one take ~1 s."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
