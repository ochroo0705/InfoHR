"""D-083: an order is never pending. Number every pending order, once.

Each pending order gets the next number of its year (the highest all-digit number of that year's orders and MACS
commands, plus one), in creation order, and becomes registered. A pending order that already has a number keeps it
unless another order or command of its year has that number; then it gets the next free number.
An order with no date gets its creation day (local time) as its date: a registered order always has a date, and its
year keeps its number unique. An order whose number would be longer than the field allows is skipped and logged; it
stays pending.

The migration reads only the historical models and the functions below, never the app code (no app imports), so a
later change to the app cannot break a fresh migrate. The reverse does nothing: the numbers stay.
"""

import logging

from django.db import migrations
from django.utils import timezone

PENDING = "pending"
REGISTERED = "registered"
NUMBER_MAX = 10  # max_length of HrOrder.number
CHANGE_TEXT_LIMIT = 20000  # the folded change text kept on a row, as employees' log rows do
logger = logging.getLogger(__name__)


def _fold(text):
    """The search fold of employees' log rows: case-folded, Mongolian ө read as о and ү as у."""
    return text.casefold().replace("ө", "о").replace("ү", "у")


def _change_text(changes):
    """The folded text of a change list: field, old and new value of each change, joined by single spaces."""
    pieces = []
    for change in changes:
        for key in ("field", "old", "new"):
            value = change.get(key)
            if value is not None and str(value):
                pieces.append(str(value))
    return _fold(" ".join(pieces))[:CHANGE_TEXT_LIMIT]


def _used_keys(hr_order, command, year):
    """The number keys (stripped, casefolded) used in `year` by the registered or signed and cancelled HR orders and by
    the MACS commands, and the highest all-digit number among them (0 when none). Pending orders are not counted:
    they are the ones being numbered here."""
    used = list(hr_order.objects.filter(date__year=year).exclude(state=PENDING).values_list("number", flat=True))
    used += [c.number for c in command.objects.filter(date__year=year)]
    keys = {n.strip().casefold() for n in used if n.strip()}
    top = max((int(n.strip()) for n in used if n.strip().isdecimal()), default=0)
    return keys, top


def number_pending_orders(apps):
    """Number and register every pending order of `apps` (a migration state). Returns how many were numbered.

    A pending order that already has a number keeps it, unless another order or MACS command of its year has the same
    number: then it gets the next free number and its history line says which number it replaced."""
    hr_order = apps.get_model("employees", "HrOrder")
    activity_entry = apps.get_model("employees", "ActivityEntry")
    command = apps.get_model("macs", "Command")
    pending = list(hr_order.objects.filter(state=PENDING).order_by("created_at", "pk"))
    used = {}  # year -> the number keys in use that year (grows as pending orders are numbered)
    tops = {}  # year -> the highest all-digit number in use that year
    numbered = 0
    for order in pending:
        if order.date is None:
            order.date = timezone.localtime(order.created_at).date()
        year = order.date.year
        if year not in used:
            used[year], tops[year] = _used_keys(hr_order, command, year)
        typed = order.number.strip()
        clash = bool(typed) and typed.casefold() in used[year]
        number = typed if typed and not clash else str(tops[year] + 1)
        if len(number) > NUMBER_MAX:
            logger.warning(
                "Pending order %s not numbered: %r is longer than %s characters", order.pk, number, NUMBER_MAX
            )
            continue
        used[year].add(number.casefold())
        if number.isdecimal():
            tops[year] = max(tops[year], int(number))
        order.number, order.number_key, order.state = number, number.casefold(), REGISTERED
        order.save()
        after = {"Дугаар": number, "Огноо": str(order.date), "Агуулга": order.summary, "Гаргасан": order.issued_by}
        changes = [{"field": k, "old": "", "new": v} for k, v in after.items() if v]
        message = f"Тушаал № {number} ({order.get_order_type_display()}): бүртгэсэн"
        if clash:
            changes[0]["old"] = typed  # the typed number that clashed
            message += f" (оруулсан дугаар {typed} давхцсан тул солигдсон)"
        activity_entry.objects.create(
            employee_id=order.employee_id,
            kind="changed",
            message=message,
            changes=changes,
            change_text=_change_text(changes),
            order=order,
        )
        numbered += 1
    return numbered


def forwards(apps, schema_editor):
    number_pending_orders(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0038_order_state_default"),
        ("macs", "0025_department_parent"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
