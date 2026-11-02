"""Which models have their changes written to the system log (settings, lookup lists, leave rules).

Only these tables are audited. Hot tables (employees, orders, leave requests) are deliberately left out.
Design: docs/superpowers/specs/2026-10-29-audit-logs-design.md §5.3a.
"""

from django.db import models


def audited_models() -> list[type[models.Model]]:
    """Resolved inside the function, not at import time, so that importing this module cannot create a cycle."""
    from employees.models import CompanySettings, DepartmentExt, OrderTemplate, PositionExt, StaffImportSettings
    from leave.models import AnnualLeaveRule, LeaveSettings, LeaveTypeExt
    from lists.models import MeaningfulEntry
    from lists.registry import QUICK
    from macs.models import LeaveTypeRow, LegalHoliday

    from accounts.models import AccessScope

    found: list[type[models.Model]] = [spec.model for spec in QUICK.values()]
    found += [
        CompanySettings,
        OrderTemplate,
        StaffImportSettings,
        LeaveSettings,
        AnnualLeaveRule,
        LeaveTypeExt,
        LegalHoliday,
        LeaveTypeRow,
        MeaningfulEntry,
        DepartmentExt,
        PositionExt,
        AccessScope,
    ]
    return list(dict.fromkeys(found))  # one entry per model, order kept
