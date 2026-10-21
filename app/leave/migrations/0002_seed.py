from datetime import date
from decimal import Decimal
from typing import Any

from django.db import migrations

TYPES = [  # code, name, is_paid, uses_annual_balance, order
    ("annual", "Ээлжийн амралт", True, True, 1),
    ("sick", "Өвчний чөлөө", True, False, 2),
    ("unpaid", "Цалингүй чөлөө", False, False, 3),
    ("personal", "Цалинтай хувийн чөлөө", True, False, 4),
    ("other", "Бусад", False, False, 5),
]
BRACKETS = [
    {"from_month": 61, "extra_days": 3},
    {"from_month": 121, "extra_days": 5},
    {"from_month": 181, "extra_days": 7},
    {"from_month": 241, "extra_days": 9},
    {"from_month": 301, "extra_days": 11},
    {"from_month": 373, "extra_days": 14},
]
# Frozen copy of accounts.roles.DEFAULT_LEAVE_PERMS.
NAMES = {"view_leave": "Чөлөө харах", "record_leave": "Чөлөө бүртгэх", "manage_leave_settings": "Чөлөөний тохиргоо"}
DEFAULTS = {"Admin": tuple(NAMES), "HR": tuple(NAMES), "Accountant": ("view_leave",)}


def forwards(apps: Any, schema_editor: Any) -> None:
    LeaveType = apps.get_model("leave", "LeaveType")
    for code, name, paid, uses, order in TYPES:
        LeaveType.objects.get_or_create(
            code=code, defaults={"name": name, "is_paid": paid, "uses_annual_balance": uses, "order": order}
        )
    apps.get_model("leave", "AnnualLeaveRule").objects.get_or_create(
        effective_from=date(2022, 1, 1),
        defaults={"base_days": Decimal(15), "base_days_minor_or_disabled": Decimal(20), "brackets": BRACKETS},
    )
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.get_or_create(app_label="leave", model="leave")
    perms = {
        c: Permission.objects.get_or_create(codename=c, content_type=ct, defaults={"name": n})[0]
        for c, n in NAMES.items()
    }
    for group_name, codes in DEFAULTS.items():
        group = Group.objects.filter(name=group_name).first()
        if group is not None:
            group.permissions.add(*(perms[c] for c in codes))


class Migration(migrations.Migration):
    dependencies = [("leave", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
