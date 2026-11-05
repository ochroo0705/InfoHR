import itertools
from collections.abc import Callable

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from employees.models import JobRecord
from employees.tests.conftest import _no_offboarding_templates, link_login  # noqa: F401 (autouse)
from leave.models import LeaveSettings

from assistant.tests.helpers import hire_one

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


@pytest.fixture
def role_user(db: None) -> Callable[[str], User]:
    """A fresh login per call. Kinds: hr, accountant, admin (staff), auditor, staff (Employee + own record), approver
    (staff who is the line manager of another hired employee), none (no group, no record)."""
    actor = User.objects.create_superuser("help_actor", password=PASSWORD)

    def make(kind: str) -> User:
        user = User.objects.create_user(f"help_{kind}_{next(_NAMES)}", password=PASSWORD)
        group = _GROUP_OF[kind]
        if group is not None:
            user.groups.add(Group.objects.get(name=group))
        if kind == "admin":
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        if kind in ("staff", "approver"):
            own = hire_one(actor)
            link_login(own, user)
            if kind == "approver":
                report = hire_one(actor)
                JobRecord.objects.filter(employee=report).update(manager=own)
        return user

    return make


@pytest.fixture
def approval_on(db: None) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": True})
