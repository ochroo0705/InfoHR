import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections, transaction
from django.db.models.signals import pre_migrate
from infohr_firebird.testdb import WORK_DIR, discard, prepare
from pytest_django.fixtures import SettingsWrapper
from pytest_django.plugin import DjangoDbBlocker
from tests_guard.structure_load import STRUCTURE_SQL, chunked, chunks_left, is_complete, loaded_note

# INFOHR_TEST_DB=firebird: the whole session runs on ONE migrated Firebird copy (infohr_firebird/testdb.py).
# Read once at import: the switch is fixed for a pytest run. With it unset, pytest-django's own setup is used.
FIREBIRD_TEST_DB = os.environ.get("INFOHR_TEST_DB", "") == "firebird"


@pytest.fixture(autouse=True)
def fast_password_hasher(settings: SettingsWrapper) -> None:
    """Tests create many logins; production-strength hashing made each one take ~1 s."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _modules_cache_clear() -> Iterator[None]:
    """The on/off state of the optional modules is cached for a few seconds; a test must never see another's."""
    from accounts import modules

    modules.clear_cache()
    yield
    modules.clear_cache()


@pytest.fixture(autouse=True)
def _throttle_cache_in_memory(settings: SettingsWrapper) -> Iterator[None]:
    """Failed-login counters live in memory during tests (no files), and each test starts with none."""
    from django.core.cache import caches

    settings.CACHES = {
        **settings.CACHES,
        "throttle": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "test-throttle"},
    }
    caches["throttle"].clear()
    yield
    caches["throttle"].clear()


@pytest.fixture(autouse=True)
def _assistant_off(settings: SettingsWrapper) -> None:
    """A developer's real assistant key in .env must not change other tests or call the API."""
    settings.ASSISTANT_PROVIDER = ""


def _load_production_structure(sender: object, using: str = "default", **kwargs: object) -> None:
    """Test databases get the real production tables (D-018) and an empty `hr` schema before
    Django migrates, loaded in committed chunks (tests_guard/structure_load.py). Never runs
    against a non-test database, and only on PostgreSQL (the Firebird copy is migrated by testdb.prepare)."""
    conn = connections[using]
    if conn.vendor != "postgresql" or not str(conn.settings_dict["NAME"]).startswith("test_"):
        return
    with conn.cursor() as c:
        c.execute(
            "select to_regclass('public.employee') is not null, obj_description('public'::regnamespace, 'pg_namespace')"
        )
        loaded_whole, note = c.fetchone()
        if not is_complete(note):  # the hook runs once per app; only the first call loads
            digest, chunks = chunked(STRUCTURE_SQL.read_text(encoding="utf-8"))
            for n in chunks_left(note, loaded_whole, digest, len(chunks)):
                with transaction.atomic(using=using):
                    c.execute(chunks[n])
                    c.execute(f"comment on schema public is '{loaded_note(digest, n + 1, len(chunks))}'")
            c.execute(f"comment on schema public is '{loaded_note(digest, len(chunks), len(chunks))}'")
        # Only after the load: the search path is hr,public, so unqualified tables would land in hr.
        c.execute("create schema if not exists hr")


pre_migrate.connect(_load_production_structure, dispatch_uid="load_production_structure")


if FIREBIRD_TEST_DB:

    @pytest.fixture(scope="session")
    def django_db_setup(django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
        """Firebird switch: the `default` alias uses one migrated copy of the template for the whole session.

        Replaces pytest-django's django_db_setup, and only when the switch is on, so PostgreSQL keeps it. No
        test_ database is created: Django would create a new Firebird file, and the copy is migrated here instead.
        """
        if connections["default"].vendor != "firebird":
            raise pytest.UsageError("INFOHR_TEST_DB=firebird needs DB_ENGINE=firebird")
        template = os.environ.get("FB_TEMPLATE_FDB", "")
        if not template or not Path(template).is_file():
            raise pytest.UsageError("INFOHR_TEST_DB=firebird needs FB_TEMPLATE_FDB set to an existing template file")
        clone = prepare(template, WORK_DIR, empty=True)
        connections.close_all()
        connections["default"].settings_dict["NAME"] = clone
        if "governed" in connections.databases:  # the governed alias reads the same copy (app/hr_sql)
            connections["governed"].settings_dict["NAME"] = clone
        try:
            # The seeds (role groups, permissions, content types) are in the copy now, and the flush of the first
            # transactional test deletes them. TransactionTestCase(serialized_rollback=True) puts them back from this.
            with django_db_blocker.unblock():
                connection = connections["default"]
                # Django sets this attribute itself (create_test_db); the stub does not declare it.
                connection._test_serialized_contents = connection.creation.serialize_db_to_string()  # type: ignore[attr-defined]
            yield
        finally:
            connections.close_all()
            discard(Path(clone))


@pytest.fixture(scope="session", autouse=True)
def production_structure_unchanged(
    django_db_setup: None, django_db_blocker: DjangoDbBlocker, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """Fails the run if anything in it changed a production table (D-017).

    PostgreSQL: the production structure must be loaded, and its fingerprint must not change. Firebird: the
    fb_guard snapshot is taken before the run and `fb_guard verify` runs after it.
    """
    if connections["default"].vendor == "firebird":
        snapshot = tmp_path_factory.mktemp("fb_guard") / "snapshot.json"
        with django_db_blocker.unblock():
            call_command("fb_guard", "snapshot", str(snapshot))
        yield
        with django_db_blocker.unblock():
            try:
                call_command("fb_guard", "verify", str(snapshot))
            except CommandError as exc:
                pytest.fail(str(exc))
        return

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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """@pytest.mark.pg_only("reason") marks a test that checks something only PostgreSQL has. The reason is required.

    With the Firebird switch on, such a test is skipped and the skip shows the reason.
    """
    for item in items:
        for marker in item.iter_markers("pg_only"):
            reason = str(marker.args[0]) if marker.args else ""
            if not reason.strip():
                raise pytest.UsageError(
                    f"{item.nodeid}: @pytest.mark.pg_only needs a reason naming what is PostgreSQL-only"
                )
            if FIREBIRD_TEST_DB:
                item.add_marker(pytest.mark.skip(reason=f"PostgreSQL only: {reason}"))
