"""The movement reports: B1 the movements of a period, B2 the change list per person, B3 the leavers.

Rows come only from `employees.services.movements.changes`. A change dated after today is not a movement yet, so the
period is cut at today. People with no Info HR job history show only as a hire (the grey note says so).
"""

from collections.abc import Collection
from typing import Any

from accounts.models import User
from django.urls import reverse
from django.utils import timezone
from employees import access, listing
from employees.services.movements import Change, changes
from employees.services.order_register import age_on
from macs.models import Employee

from reports.filters import MOVEMENT_KINDS, Filters, period_of
from reports.types import Column, Report

NEEDS = ("macs.view_employees",)  # the employee list's right: an Employee-role user sees only themself and is refused
LEAVE_KINDS = frozenset({"termination"})
NOTE = (
    "Info HR-д бүртгэсэн өөрчлөлтүүд, өнөөдрийг хүртэл. Хуучин програмаас ирсэн ажилтны ажилд орсон огноо нь анх "
    "ажилд орсон огноогоор гарна; хуучин програмд бүртгэсэн шилжилт, ажлаас гарсан нь энд гарахгүй."
)


def _pk(obj: Any) -> int | None:
    """The id of a related row, None when there is none."""
    return obj.pk if obj is not None else None


def _name(obj: Any) -> str | None:
    """The name of a related row; None when there is none, so the cell sorts last."""
    return obj.name if obj is not None else None


def _detail_url(c: Change) -> str:
    return reverse("employees:detail", args=[c.employee.pk])


def _note(f: Filters) -> str:
    """The same grey line whatever the filters: it says what Info HR holds and what it does not."""
    return NOTE


def _changes(user: User, f: Filters, kinds: Collection[str] | None) -> list[Change]:
    """The changes these filters ask for, of the people the user may see, dated from the period's start to today."""
    people = access.visible_employees(user).exclude(emptype__in=listing.NEVER_WORKED)
    if f.branch is not None:
        people = people.filter(branch_id=f.branch)
    if f.employee is not None:
        people = people.filter(pk=f.employee)
    start, end = period_of(f)
    found = changes(people, start, min(end, timezone.localdate()), kinds)
    if f.department is not None:
        found = [c for c in found if _pk(c.department) == f.department]
    if f.reason is not None:
        found = [c for c in found if _pk(c.fired_reason) == f.reason]
    return found


def _movement_rows(user: User, f: Filters) -> list[Any]:
    """B1: the change filter picks one kind; otherwise the six kinds B1 shows."""
    kinds = {f.change} if f.change else set(MOVEMENT_KINDS)
    return _changes(user, f, kinds)


def _history_rows(user: User, f: Filters) -> list[Any]:
    """B2: every change kind, the Work tab's list."""
    return _changes(user, f, None)


def _leaver_rows(user: User, f: Filters) -> list[Any]:
    """B3: the terminations only."""
    return _changes(user, f, LEAVE_KINDS)


# The columns B1 and B2 share: the date, the person, the change and the job before and after it, the order.
MOVEMENT_COLUMNS: tuple[Column, ...] = (
    Column(key="day", label="Огноо", value=lambda c: c.day),
    Column(key="code", label="Код", value=lambda c: c.employee.code),
    Column(key="name", label="Ажилтан", value=lambda c: c.employee.full_name, href=_detail_url),
    Column(key="kind", label="Өөрчлөлт", value=lambda c: c.kind_label),
    Column(key="from_department", label="Өмнөх хэлтэс", value=lambda c: _name(c.from_department)),
    Column(key="department", label="Хэлтэс", value=lambda c: _name(c.department)),
    Column(key="from_position", label="Өмнөх албан тушаал", value=lambda c: _name(c.from_position)),
    Column(key="position", label="Албан тушаал", value=lambda c: _name(c.position)),
    Column(key="order", label="Тушаал", value=lambda c: c.order_number or None),
)

LEAVER_COLUMNS: tuple[Column, ...] = (
    Column(key="day", label="Гарсан огноо", value=lambda c: c.day),
    Column(key="code", label="Код", value=lambda c: c.employee.code),
    Column(key="name", label="Ажилтан", value=lambda c: c.employee.full_name, href=_detail_url),
    Column(key="department", label="Хэлтэс", value=lambda c: _name(c.department)),
    Column(key="position", label="Албан тушаал", value=lambda c: _name(c.position)),
    Column(
        key="years",
        label="Ажилласан жил",
        value=lambda c: age_on(c.employee.first_hire_date, c.day),
        numeric=True,
    ),
    Column(key="reason", label="Шалтгаан", value=lambda c: _name(c.fired_reason)),
    Column(key="order", label="Тушаал", value=lambda c: c.order_number or None),
)

MOVEMENTS = Report(
    key="movements",
    title="Ажилчдын шилжилт хөдөлгөөний тайлан",
    filters=("branch", "department", "change", "period"),
    columns=MOVEMENT_COLUMNS,
    default_columns=tuple(c.key for c in MOVEMENT_COLUMNS),
    rows=_movement_rows,
    needs=NEEDS,
    source=Employee,
    group_options=("kind", "department"),
    note=_note,
)

HISTORY = Report(
    key="history",
    title="Шилжилт хөдөлгөөний жагсаалт",
    filters=("employee", "department", "period"),
    columns=MOVEMENT_COLUMNS,
    default_columns=tuple(c.key for c in MOVEMENT_COLUMNS),
    rows=_history_rows,
    needs=NEEDS,
    source=Employee,
    group_options=("name", "kind"),
    note=_note,
)

LEAVERS = Report(
    key="leavers",
    title="Ажлаас чөлөөлөгдсөн ажилчдын судалгаа",
    filters=("department", "reason", "period"),
    columns=LEAVER_COLUMNS,
    default_columns=tuple(c.key for c in LEAVER_COLUMNS),
    rows=_leaver_rows,
    needs=NEEDS,
    source=Employee,
    group_options=("reason", "department"),
    note=_note,
)
