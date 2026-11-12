"""The connection the governed SQL runs on: the `governed` alias (config/settings.py, Firebird only).

The alias reads the same file as `default`. Its login is the read-only one from scripts/grant_governed_fb.sql when
FIREBIRD_GOVERNED_USER is set, and the default login otherwise (development only).
"""

from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.db.backends.base.base import BaseDatabaseWrapper

GOVERNED_ALIAS = "governed"


def governed_connection() -> BaseDatabaseWrapper:
    """The governed connection. Raises ImproperlyConfigured when the alias is absent (any engine but Firebird)."""
    if GOVERNED_ALIAS not in connections.databases:
        raise ImproperlyConfigured("The governed alias exists only with DB_ENGINE=firebird.")
    return connections[GOVERNED_ALIAS]
