import os
import shutil
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest
from asgiref.local import Local
from django.db import connections
from pytest_django.fixtures import SettingsWrapper
from pytest_django.plugin import DjangoDbBlocker

from infohr_firebird.testdb import WORK_DIR, discard, prepare
from infohr_firebird.tests.copies import remove_copy


@pytest.fixture
def fb_clone(tmp_path: Path) -> Iterator[str]:
    """Copy the Firebird template database into a temp folder and yield the copy's path.

    The template comes from the FB_TEMPLATE_FDB environment variable. Tests never open the
    template itself, only this copy, so the template stays unchanged. The copy is deleted at
    teardown; fb_alias depends on this fixture, so its connection is already closed by then.
    """
    template = os.environ.get("FB_TEMPLATE_FDB", "")
    if not template:
        pytest.skip("FB_TEMPLATE_FDB is not set")
    template_path = Path(template)
    if not template_path.is_file():
        pytest.skip(f"Firebird template not found: {template_path}")
    clone = tmp_path / "clone.fdb"
    shutil.copyfile(template_path, clone)
    try:
        yield str(clone)
    finally:
        remove_copy(clone)


@pytest.fixture
def fb_alias(fb_clone: str, settings: SettingsWrapper, django_db_blocker: DjangoDbBlocker) -> Iterator[str]:
    """Make the 'fb' alias usable for one test: connections["fb"] points at the cloned file.

    pytest-django cannot unblock a single alias, so this fixture:
    (a) registers settings.DATABASES["fb"] (assigned, so pytest-django restores it);
    (b) rebuilds Django's connection handler settings and gives this thread an empty
        connection store, so no stale or missing alias is reused;
    (c) unblocks database access for the fixture's lifetime only;
    (d) at teardown closes connections["fb"] and puts the old handler state back.
    """
    databases = dict(settings.DATABASES)
    # Optional (plan 5 spike): FB_RUNTIME_USER runs the test body as a limited user. Unset = SYSDBA as before.
    runtime_user = os.environ.get("FB_RUNTIME_USER", "")
    databases["fb"] = {
        "ENGINE": "infohr_firebird",
        "NAME": fb_clone,
        "USER": runtime_user or "SYSDBA",
        # secret: from the environment only
        "PASSWORD": (
            os.environ.get("FB_RUNTIME_PASSWORD", "") if runtime_user else os.environ.get("FIREBIRD_PASSWORD", "")
        ),
        "HOST": "",
        "OPTIONS": {"charset": "UTF8"},
        "TIME_ZONE": "Asia/Ulaanbaatar",  # Firebird stores local wall-clock time
    }
    with warnings.catch_warnings():
        # Django warns about every DATABASES override; this assignment is deliberate.
        warnings.filterwarnings("ignore", message="Overriding setting DATABASES", category=UserWarning)
        settings.DATABASES = databases

    saved_settings = connections.__dict__.get("settings")
    saved_store = connections.__dict__["_connections"]
    connections.__dict__["settings"] = connections.configure_settings(databases)
    connections.__dict__["_connections"] = Local(connections.thread_critical)
    try:
        with django_db_blocker.unblock():
            try:
                yield "fb"
            finally:
                connections["fb"].close()
    finally:
        connections.__dict__["_connections"] = saved_store
        if saved_settings is None:
            connections.__dict__.pop("settings", None)
        else:
            connections.__dict__["settings"] = saved_settings


@pytest.fixture(scope="module")
def migrated_clone() -> Iterator[str]:
    """Copy the template into a scratch folder and migrate the copy through every app (testdb.prepare)."""
    template_text = os.environ.get("FB_TEMPLATE_FDB", "")
    if not template_text:
        pytest.skip("FB_TEMPLATE_FDB is not set")
    template = Path(template_text)
    if not template.is_file():
        pytest.skip(f"Firebird template not found: {template}")
    clone = Path(prepare(str(template), WORK_DIR, empty=False))
    try:
        yield str(clone)
    finally:
        discard(clone)
