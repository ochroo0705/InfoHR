import pytest
from pytest_django.fixtures import SettingsWrapper


@pytest.fixture(autouse=True)
def fast_password_hasher(settings: SettingsWrapper) -> None:
    """Tests create many logins; production-strength hashing made each one take ~1 s."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


from pathlib import Path  # noqa: E402

from django.db import connections  # noqa: E402
from django.db.models.signals import pre_migrate  # noqa: E402

STRUCTURE_SQL = Path(__file__).resolve().parent.parent / "db" / "schema" / "macs_public.sql"


def _load_production_structure(sender: object, using: str = "default", **kwargs: object) -> None:
    """Test databases get the real production tables (D-018) and an empty `hr` schema before
    Django migrates. Never runs against a non-test database."""
    conn = connections[using]
    if not str(conn.settings_dict["NAME"]).startswith("test_"):
        return
    with conn.cursor() as c:
        c.execute("select to_regclass('public.employee')")
        if c.fetchone()[0] is None:
            c.execute(STRUCTURE_SQL.read_text(encoding="utf-8"))
        c.execute("create schema if not exists hr")


pre_migrate.connect(_load_production_structure, dispatch_uid="load_production_structure")


@pytest.fixture(scope="session", autouse=True)
def production_structure_unchanged(django_db_setup: None, django_db_blocker) -> object:  # type: ignore[no-untyped-def]
    """Fails the run if anything in it changed a production table (D-017)."""
    from tests_guard.test_structure import fingerprint

    with django_db_blocker.unblock(), connections["default"].cursor() as c:
        c.execute("select to_regclass('public.employee')")
        if c.fetchone()[0] is None:
            pytest.fail(
                "Production structure is not loaded in the test database. It is loaded only when the "
                "database is created and migrated. Rerun with --create-db (do not use --nomigrations "
                "or --reuse-db on a database that was never loaded)."
            )
        before = fingerprint(c)
    yield
    with django_db_blocker.unblock(), connections["default"].cursor() as c:
        assert fingerprint(c) == before, "A production table's structure changed during the test run"


@pytest.fixture(autouse=True)
def _order_files_tmp(settings: SettingsWrapper, tmp_path: Path) -> None:
    """Every test writes order files to a temporary folder, never to app/private."""
    settings.ORDER_FILES_ROOT = tmp_path / "orders"
