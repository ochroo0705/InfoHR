import pytest
from django.conf import settings

pytestmark = pytest.mark.skipif(
    "welcome" in settings.INSTALLED_APPS,
    reason="runs only when PUBLIC_WELCOME is off",
)


def test_app_absent_when_flag_off() -> None:
    assert "welcome" not in settings.INSTALLED_APPS
    assert settings.PUBLIC_WELCOME is False
