"""B4 the HR orders («Хүний нөөцийн тушаалууд»): the order register's rows of a period.

Rows come from `employees.services.order_register.register_rows`, so Info HR orders and the old program's commands both
show. An order with no date cannot sit in a period, so it is left out. Cancelled orders stay, with their state shown.
"""

from datetime import date

from accounts.models import User
from django.urls import reverse
from django.utils import timezone
from employees.services.order_register import RegisterRow, register_rows

from reports.filters import ORDER_TYPES, Filters, period_of
from reports.types import Column, Report

NEEDS = ("macs.view_employees",)  # the order register's right: an Employee-role user sees only themself and is refused
NOTE = (
    "Тушаалын бүртгэлийн мөрүүд (Info HR болон хуучин програмын). Огноогүй тушаал орохгүй. "
    "Хэлтэс нь ажилтны одоогийн хэлтэс."
)


def _detail_url(r: RegisterRow) -> str:
    return reverse("employees:detail", args=[r.employee_id])


def _or_none(text: str) -> str | None:
    """The text, or None when it is empty, so the cell sorts last."""
    return text or None


def _type(r: RegisterRow) -> str | None:
    """The order type's label; an old-program code with no label is shown as the code itself."""
    if r.order_type is None:
        return None
    return ORDER_TYPES.get(r.order_type, str(r.order_type))


def _note(f: Filters) -> str:
    """The same grey line whatever the filters: it says what the register holds."""
    return NOTE


def _rows(user: User, f: Filters) -> list[RegisterRow]:
    """The orders of the period, of the people the user may see, sorted by date then number."""
    today = timezone.localdate()
    start, end = period_of(f)
    found = register_rows(user, year=None, order_type=f.order_type, department_id=f.department, state=None, today=today)
    dated = [r for r in found if r.date is not None and start <= r.date <= end]
    return sorted(dated, key=lambda r: (r.date or date.min, r.number))


COLUMNS: tuple[Column, ...] = (
    Column(key="date", label="Огноо", value=lambda r: r.date),
    Column(key="number", label="Дугаар", value=lambda r: _or_none(r.number)),
    Column(key="code", label="Код", value=lambda r: _or_none(r.employee_code)),
    Column(key="name", label="Ажилтан", value=lambda r: _or_none(r.employee_name), href=_detail_url),
    Column(key="department", label="Хэлтэс", value=lambda r: _or_none(r.department)),
    Column(key="position", label="Албан тушаал", value=lambda r: _or_none(r.position)),
    Column(key="type", label="Төрөл", value=_type),
    Column(key="summary", label="Агуулга", value=lambda r: _or_none(r.summary)),
    Column(key="issued_by", label="Гаргасан", value=lambda r: _or_none(r.issued_by)),
    Column(key="state", label="Төлөв", value=lambda r: _or_none(r.state_label)),
)

REPORT = Report(
    key="orders",
    title="Хүний нөөцийн тушаалууд",
    filters=("order_type", "department", "period"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=NEEDS,
    source=None,
    group_options=("type", "department", "state"),
    note=_note,
)
