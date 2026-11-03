"""Start the onboarding checklist when somebody is hired or rehired.

Onboarding only tracks work: it never blocks a hire, an event, leave or an order. So `start_for_hire` never raises;
a missing template or any failure just means there is no checklist (the failure is logged).
"""

import logging
from datetime import date

from accounts.models import User
from macs.models import Employee

from checklists.models import Checklist, ChecklistKind
from checklists.services import lifecycle

logger = logging.getLogger(__name__)


def start_for_hire(employee: Employee, *, start_date: date, employee_type: str | None, by: User) -> Checklist | None:
    """Start (or reuse the open) onboarding checklist of `employee`, anchored on `start_date`.

    `employee_type` is the EmployeeType value of the new job; it picks the template that lists it, else the default.
    Returns None when no active template applies or when anything fails.
    """
    try:
        return lifecycle.start(
            employee, ChecklistKind.ONBOARDING, reason=employee_type or None, anchor_day=start_date, by=by
        )
    except Exception:
        logger.warning("onboarding checklist was not started for employee %s", employee.pk, exc_info=True)
        return None
