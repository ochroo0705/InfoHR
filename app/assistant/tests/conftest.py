import itertools
from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from employees.models import Employee, JobRecord
from employees.services import history, macs_writes
from employees.tests.conftest import _no_offboarding_templates, hire_values, link_login  # noqa: F401 (autouse)
from leave.models import LeaveSettings

PASSWORD = "x-long-pass-123"  # noqa: S105
_NAMES = itertools.count(1)
_GROUP_OF: dict[str, str | None] = {
    "hr": roles.HR,
    "accountant": roles.ACCOUNTANT,
    "staff": roles.EMPLOYEE,
    "approver": roles.EMPLOYEE,
    "none": None,
}


@pytest.fixture(autouse=True)
def _no_request_time_daily_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """DailySyncMiddleware runs on the first signed-in request of each process; keep it out of these tests."""
    from employees import daily_sync

    monkeypatch.setattr(daily_sync, "_needs_sync", lambda request: False)


def _hire(actor: User) -> Employee:
    n = next(_NAMES)
    job = {
        "position": macs_writes.save_position("Нягтлан"),
        "department": macs_writes.save_department("Санхүү"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    return history.hire(
        hire_values(f"УБ{n:08d}"), {}, start=date(2026, 1, 5), job=job, salary=Decimal("2500000"), by=actor
    )


@pytest.fixture
def role_user(db: None) -> Callable[[str], User]:
    """A fresh login per call. Kinds: hr, accountant, staff (Employee + own record), approver (staff who is the line
    manager of another hired employee), none (no group, no record)."""
    actor = User.objects.create_superuser("help_actor", password=PASSWORD)

    def make(kind: str) -> User:
        user = User.objects.create_user(f"help_{kind}_{next(_NAMES)}", password=PASSWORD)
        group = _GROUP_OF[kind]
        if group is not None:
            user.groups.add(Group.objects.get(name=group))
        if kind in ("staff", "approver"):
            own = _hire(actor)
            link_login(own, user)
            if kind == "approver":
                report = _hire(actor)
                JobRecord.objects.filter(employee=report).update(manager=own)
        return user

    return make


@pytest.fixture
def approval_on(db: None) -> None:
    LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": True})
