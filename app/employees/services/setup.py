"""Onboarding setup checklist ("Бүрдүүлэлт") for new hires."""

from dataclasses import dataclass
from datetime import datetime

from accounts.models import User
from django.db import transaction

from employees import access
from employees.models import ActivityEntry, ActivityKind, Employee, SetupItem

ITEMS = [
    ("contract", "Гэрээ байгуулсан"),
    ("id_copy", "Иргэний үнэмлэхний хуулбар авсан"),
    ("equipment", "Тоног төхөөрөмж өгсөн"),
    ("bank", "Банкны мэдээлэл бүртгэсэн"),
]
AUTO = frozenset({"bank"})


@dataclass
class Item:
    key: str
    label: str
    done: bool
    auto: bool
    done_by: User | None
    done_at: datetime | None


def _all(employee: Employee) -> list[Item]:
    ticked = {i.key: i for i in employee.setup_items.select_related("done_by")}
    auto_done = {"bank": bool(employee.account_no)}
    items = []
    for key, label in ITEMS:
        tick = ticked.get(key)
        if key in AUTO:
            items.append(Item(key, label, auto_done[key], True, None, None))
        else:
            items.append(
                Item(
                    key, label, tick is not None, False, tick.done_by if tick else None, tick.done_at if tick else None
                )
            )
    return items


def status(employee: Employee, user: User) -> list[Item]:
    items = _all(employee)
    if access.can_view_salary(user):
        return items
    return [i for i in items if i.key != "bank"]


def is_complete(employee: Employee) -> bool:
    return all(i.done for i in _all(employee))


def complete_for(employee: Employee, user: User) -> bool:
    """Complete over the items this user can see (a hidden bank item must not block or leak)."""
    return all(i.done for i in status(employee, user))


@transaction.atomic
def toggle(employee: Employee, key: str, by: User) -> None:
    labels = dict(ITEMS)
    if key not in labels or key in AUTO:
        raise ValueError(f"Unknown or automatic setup item: {key}")
    Employee.objects.select_for_update().get(pk=employee.pk)  # serialise concurrent toggles
    deleted, _ = SetupItem.objects.filter(employee=employee, key=key).delete()
    if deleted:
        verb = "болиулсан"
    else:
        SetupItem.objects.create(employee=employee, key=key, done_by=by)
        verb = "хийсэн"
    ActivityEntry.objects.create(
        employee=employee,
        by=by,
        kind=ActivityKind.CHANGED,
        message=f"Бүрдүүлэлт: {labels[key]} — {verb}",
        personal=False,
        sensitive=False,
    )
