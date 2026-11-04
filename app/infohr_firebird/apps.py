from django.apps import AppConfig


class InfohrFirebirdConfig(AppConfig):
    """Installed only when DB_ENGINE=firebird (config/settings.py). Its ready() registers the system checks."""

    name = "infohr_firebird"
    verbose_name = "Info HR Firebird backend"

    def ready(self) -> None:
        from infohr_firebird import checks  # noqa: F401 (import registers the checks)
