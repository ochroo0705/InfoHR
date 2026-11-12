import itertools
from collections.abc import Callable
from datetime import date

import pytest
from accounts import roles
from accounts.models import User
from django.db import transaction
from employees.tests.conftest import _no_offboarding_templates, link_login  # noqa: F401 (autouse)
from leave.models import LeaveSettings

from assistant.entries import allowed_entries
from assistant.evalset import fill_role_entries
from assistant.role_users import make_role_user as build_role_user

PASSWORD = "x-long-pass-123"  # noqa: S105
_NAMES = itertools.count(1)
_GROUP_OF: dict[str, str | None] = {
    "hr": roles.HR,
    "accountant": roles.ACCOUNTANT,
    "staff": roles.EMPLOYEE,
    "approver": roles.EMPLOYEE,
    "admin": roles.ADMIN,
    "auditor": roles.AUDITOR,
    "none": None,
}


@pytest.fixture(autouse=True)
def _no_request_time_daily_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """DailySyncMiddleware runs on the first signed-in request of each process; keep it out of these tests."""
    from employees import daily_sync

    monkeypatch.setattr(daily_sync, "_needs_sync", lambda request: False)


TODAY = date(2026, 11, 4)
# role -> (user kind, leave approval on?). The eval roles ending in «_off» are the same users with approval off.
ROLE_SETUP: dict[str, tuple[str, bool]] = {
    "hr": ("hr", True),
    "hr_off": ("hr", False),
    "accountant": ("accountant", True),
    "staff": ("staff", True),
    "staff_off": ("staff", False),
    "approver": ("approver", True),
    "admin": ("admin", True),
    "auditor": ("auditor", True),
    "none": ("none", True),
}


def make_role_user(actor: User, kind: str) -> User:
    """A fresh login of the kind (see assistant.role_users.make_role_user)."""
    return build_role_user(actor, kind, f"help_{kind}_{next(_NAMES)}")


@pytest.fixture(scope="session", autouse=True)
def _role_entry_lists(django_db_setup: None, django_db_blocker: object) -> None:
    """Build evalset.ROLE_ENTRIES from the real rules: for each role, a real user's `allowed_entries`. Nothing is
    kept in the database (the transaction is rolled back), and nothing is written by hand."""
    by_role: dict[str, tuple[str, ...]] = {}
    with django_db_blocker.unblock(), transaction.atomic():  # type: ignore[attr-defined]
        actor = User.objects.create_superuser("help_actor_lists", password=PASSWORD)
        for role, (kind, approval) in ROLE_SETUP.items():
            LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": approval})
            user = make_role_user(actor, kind)
            by_role[role] = tuple(e.key for e in allowed_entries(user, TODAY))
        transaction.set_rollback(True)
    fill_role_entries(by_role)


@pytest.fixture
def role_user(db: None) -> Callable[[str], User]:
    """A fresh login per call (see make_role_user)."""
    actor = User.objects.create_superuser("help_actor", password=PASSWORD)

    def make(kind: str) -> User:
        return make_role_user(actor, kind)

    return make


@pytest.fixture
def approval_on(db: None) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": True})
