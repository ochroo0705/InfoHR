"""Real users of each role, for the checks that must see what a role is really offered: the tests (to build the role
lists from `allowed_entries`) and the `assistant_eval` command (to score each role). Create them inside a transaction
that is rolled back; nothing here cleans up.
"""

import itertools
import uuid
from datetime import date
from decimal import Decimal

from accounts import roles
from accounts.models import User
from django.contrib.auth.models import Group
from employees.models import Employee, JobRecord, ensure_ext
from employees.services import history, macs_writes

__all__ = ["GROUP_OF", "make_role_user", "hire_staff_member"]

# The group each user kind's rights come from. A kind without a group has no rights at all.
GROUP_OF: dict[str, str | None] = {
    "hr": roles.HR,
    "accountant": roles.ACCOUNTANT,
    "staff": roles.EMPLOYEE,
    "approver": roles.EMPLOYEE,
    "admin": roles.ADMIN,
    "auditor": roles.AUDITOR,
    "none": None,
}

_REGISTERS = itertools.count(1)


def hire_staff_member(actor: User) -> Employee:
    """A hired employee with a register number of their own (onboarding not done, no login)."""
    n = next(_REGISTERS)
    job = {
        "position": macs_writes.save_position("Туршилтын албан тушаал"),
        "department": macs_writes.save_department("Туршилтын хэлтэс"),
        "employee_type": "full_time",
        "status": "active",
        "contract_type": "open_ended",
    }
    values = {
        "family_name": "Батын",
        "given_name": "Сараа",
        "register_no": f"УБ9{uuid.uuid4().int % 10**5:05d}{n % 100:02d}",
        "birth_date": date(1999, 11, 22),
        "gender": "F",
        "work_phone": "99112233",
        "first_hire_date": date(2026, 1, 5),
        "work_conditions": 1,
    }
    return history.hire(values, {}, start=date(2026, 1, 5), job=job, salary=Decimal("2500000"), by=actor)


def make_role_user(actor: User, kind: str, username: str) -> User:
    """A fresh login of the kind. Kinds: hr, accountant, admin (staff), auditor, staff (Employee + own record),
    approver (staff who is the line manager of another hired employee), none (no group, no record)."""
    user = User.objects.create_user(username, password="x-long-pass-123")  # noqa: S106
    # Every new user gets the Employee group (accounts/signals.py), so the groups are set, not added to: the kind
    # «none» ends with no group at all, as the real no-group user does.
    group = GROUP_OF[kind]
    user.groups.set([Group.objects.get(name=group)] if group is not None else [])
    if kind == "admin":
        user.is_staff = True
        user.save(update_fields=["is_staff"])
    if kind in ("staff", "approver"):
        own = hire_staff_member(actor)
        ext = ensure_ext(own)
        ext.user = user
        ext.save(update_fields=["user"])
        if kind == "approver":
            report = hire_staff_member(actor)
            JobRecord.objects.filter(employee=report).update(manager=own)
    return user
