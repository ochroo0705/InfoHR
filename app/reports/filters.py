import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from urllib.parse import urlencode

from config.params import date_param, id_param
from django.db import models
from django.http import QueryDict
from django.utils import timezone
from employees.models import ChangeType, OrderType
from employees.services.personal_writes import TR_TYPES
from macs.models import (
    AbsenceType,
    Branch,
    ContactType,
    Department,
    DisciplineType,
    Employee,
    FiredReason,
    LeaveTypeRow,
    Position,
    PresentType,
)

STATES: dict[str, str] = {"working": "Ажиллаж байгаа", "left": "Гарсан", "all": "Бүгд"}
GENDERS: dict[str, str] = {"M": "Эрэгтэй", "F": "Эмэгтэй"}
# Movement kinds the change filter offers: the rows B1 and B2 show (ChangeType labels).
MOVEMENT_KINDS: dict[str, str] = {
    k: ChangeType(k).label for k in ("hire", "rehire", "transfer", "promotion", "demotion", "termination")
}
ORDER_TYPES: dict[int, str] = dict(OrderType.choices)
# Training kinds the training report filters by (the old «Хэлбэр»): the TR_TYPES codes of the personal tab.
TRAINING_TYPES: dict[int, str] = TR_TYPES
# Leave states the leave reports filter by: the leave_state values of leave.services.rows.State.
LEAVE_STATES: dict[str, str] = {
    "recorded": "Бүртгэсэн",
    "cancelled": "Цуцалсан",
    "mistake": "Буруу бүртгэсэн",
    "rejected": "Татгалзсан",
}
# The attributes the survey reports count people by (A3). The first key is the default.
ATTRIBUTES: dict[str, str] = {
    "gender": "Хүйс",
    "age": "Насны бүлэг",
    "department": "Хэлтэс",
    "position": "Албан тушаал",
    "branch": "Салбар",
    "education": "Боловсрол",
    "degree": "Эрдмийн зэрэг",
    "marital": "Гэрлэлтийн байдал",
    "nationality": "Үндэс угсаа",
    "citizenship": "Иргэншил",
    "social_origin": "Нийгмийн гарал",
    "housing": "Орон байрны нөхцөл",
    "car": "Автомашин эзэмшил",
    "clothing": "Хувцасны хэмжээ",
    "shoe": "Гутлын хэмжээ",
    "city": "Оршин суугаа аймаг, хот",
}
MIN_YEAR = 1990
MAX_YEAR = 2100
MAX_AGE = 120
# A report filter name that covers more than one field. Every other filter name is its own single field.
FILTER_FIELDS: dict[str, tuple[str, ...]] = {
    "period": ("date_from", "date_to"),
    "age_range": ("age_from", "age_to"),
}
MAX_COLUMNS = 60

# Column, group and sort keys are short lowercase words. A sort key may start with "-" for descending order.
_KEY = re.compile(r"[a-z_]{1,40}")
_SORT = re.compile(r"-?[a-z_]{1,40}")


@dataclass(frozen=True)
class Filters:
    state: str = "working"
    as_of: date | None = None  # None = today
    branch: int | None = None
    department: int | None = None
    position: int | None = None
    gender: str = ""  # "" = all, "M" or "F"
    date_from: date | None = None  # the period's first day; None = 1 January of this year
    date_to: date | None = None  # the period's last day; None = 31 December of this year
    change: str = ""  # a key of MOVEMENT_KINDS; "" = all kinds
    reason: int | None = None  # a leaving reason id
    order_type: int | None = None  # an OrderType value
    discipline: int | None = None  # a discipline type id
    employee: int | None = None  # an employee id
    leave_type: int | None = None  # a leave type id (macs LeaveTypeRow)
    leave_state: str = ""  # a key of LEAVE_STATES; "" = all states
    absence_type: int | None = None  # an old-log absence type id (macs AbsenceType)
    age_from: int | None = None  # the youngest age, 0-120
    age_to: int | None = None  # the oldest age, 0-120
    attribute: str = ""  # a key of ATTRIBUTES; "" = the default (gender)
    contact_type: int | None = None  # a contact type id (macs ContactType)
    year: int | None = None  # a survey year, 1990-2100; None = this year
    tr_type: int | None = None  # a key of TRAINING_TYPES (1 domestic, 2 foreign); None = all
    quarter: int | None = None  # a quarter, 1-4; None = this quarter
    present_type: int | None = None  # a gift type id (macs PresentType)
    columns: tuple[str, ...] = ()  # () = the report's default columns
    group: str = ""
    sort: str = ""  # column key; a leading "-" sorts descending


def _order_type(value: str | None) -> int | None:
    number = id_param(value)
    return number if number in ORDER_TYPES else None


def _training_type(value: str | None) -> int | None:
    number = id_param(value)
    return number if number in TRAINING_TYPES else None


def this_quarter() -> int:
    return (timezone.localdate().month - 1) // 3 + 1


_WHOLE = re.compile(r"-?[0-9]{1,12}")


def _int_in(value: str | None, low: int, high: int) -> int | None:
    """A whole number from `low` to `high` (both included), else None. Never raises."""
    if not value or _WHOLE.fullmatch(value) is None:
        return None
    number = int(value)
    return number if low <= number <= high else None


def parse_filters(get: QueryDict) -> Filters:
    """Read report parameters from the address. Bad values fall back to the defaults; this never raises."""
    columns: list[str] = []
    for key in get.getlist("cols"):
        if _KEY.fullmatch(key) and key not in columns:
            columns.append(key)
    state = get.get("state", "")
    gender = get.get("gender", "")
    change = get.get("change", "")
    group = get.get("group", "")
    sort = get.get("sort", "")
    leave_state = get.get("leave_state", "")
    attribute = get.get("attribute", "")
    return Filters(
        state=state if state in STATES else "working",
        as_of=date_param(get.get("as_of")),
        branch=id_param(get.get("branch")),
        department=id_param(get.get("department")),
        position=id_param(get.get("position")),
        gender=gender if gender in GENDERS else "",
        date_from=date_param(get.get("from")),
        date_to=date_param(get.get("to")),
        change=change if change in MOVEMENT_KINDS else "",
        reason=id_param(get.get("reason")),
        order_type=_order_type(get.get("order_type")),
        discipline=id_param(get.get("discipline")),
        employee=id_param(get.get("employee")),
        leave_type=id_param(get.get("leave_type")),
        leave_state=leave_state if leave_state in LEAVE_STATES else "",
        absence_type=id_param(get.get("absence_type")),
        age_from=_int_in(get.get("age_from"), 0, MAX_AGE),
        age_to=_int_in(get.get("age_to"), 0, MAX_AGE),
        attribute=attribute if attribute in ATTRIBUTES else "",
        contact_type=id_param(get.get("contact_type")),
        year=_int_in(get.get("year"), MIN_YEAR, MAX_YEAR),
        tr_type=_training_type(get.get("tr_type")),
        quarter=_int_in(get.get("quarter"), 1, 4),
        present_type=id_param(get.get("present_type")),
        columns=tuple(columns[:MAX_COLUMNS]),
        group=group if _KEY.fullmatch(group) else "",
        sort=sort if _SORT.fullmatch(sort) else "",
    )


def without_today(f: Filters) -> Filters:
    """The filters with an as-of date of today cleared: today is the default, so it is not a setting to keep."""
    return replace(f, as_of=None) if f.as_of == timezone.localdate() else f


def to_query(f: Filters) -> str:
    """The filters as an address query. Defaults are left out and keys keep a fixed order, so links stay stable."""
    params: dict[str, Any] = {}
    if f.state != "working":
        params["state"] = f.state
    as_of = without_today(f).as_of
    if as_of is not None:
        params["as_of"] = as_of.isoformat()
    if f.branch is not None:
        params["branch"] = f.branch
    if f.department is not None:
        params["department"] = f.department
    if f.position is not None:
        params["position"] = f.position
    if f.gender:
        params["gender"] = f.gender
    # the period's default (this calendar year) is not kept in the address, as today is not kept as-of
    year = timezone.localdate().year
    if f.date_from is not None and f.date_from != date(year, 1, 1):
        params["from"] = f.date_from.isoformat()
    if f.date_to is not None and f.date_to != date(year, 12, 31):
        params["to"] = f.date_to.isoformat()
    if f.change:
        params["change"] = f.change
    if f.reason is not None:
        params["reason"] = f.reason
    if f.order_type is not None:
        params["order_type"] = f.order_type
    if f.discipline is not None:
        params["discipline"] = f.discipline
    if f.employee is not None:
        params["employee"] = f.employee
    if f.leave_type is not None:
        params["leave_type"] = f.leave_type
    if f.leave_state:
        params["leave_state"] = f.leave_state
    if f.absence_type is not None:
        params["absence_type"] = f.absence_type
    if f.age_from is not None:
        params["age_from"] = f.age_from
    if f.age_to is not None:
        params["age_to"] = f.age_to
    if f.attribute:
        params["attribute"] = f.attribute
    if f.contact_type is not None:
        params["contact_type"] = f.contact_type
    if f.year is not None and f.year != timezone.localdate().year:  # this year is the default, so it is not kept
        params["year"] = f.year
    if f.tr_type is not None:
        params["tr_type"] = f.tr_type
    if f.quarter is not None and f.quarter != this_quarter():  # this quarter is the default, so it is not kept
        params["quarter"] = f.quarter
    if f.present_type is not None:
        params["present_type"] = f.present_type
    if f.columns:
        params["cols"] = list(f.columns)
    if f.group:
        params["group"] = f.group
    if f.sort:
        params["sort"] = f.sort
    return urlencode(params, doseq=True)


def period_of(f: Filters) -> tuple[date, date]:
    """The first and last day of the period. A missing end is the calendar year's; reversed dates are swapped."""
    today = timezone.localdate()
    start = f.date_from or date(today.year, 1, 1)
    end = f.date_to or date(today.year, 12, 31)
    return (start, end) if start <= end else (end, start)


def _name(objects: models.Manager[Any], pk: int) -> str | None:
    name: str | None = objects.filter(pk=pk).values_list("name", flat=True).first()
    return name


def describe(f: Filters, shown: tuple[str, ...]) -> list[str]:
    """Filter lines for print and Excel, in the order of `shown`. A filter that is set but has no name to show
    (an unknown id, a name left empty) reads «—», so the paper never hides an applied filter."""
    lines: list[str] = []
    for key in shown:
        if key == "state":
            lines.append(f"Төлөв: {STATES[f.state]}")
        elif key == "as_of":
            lines.append(f"Огноо: {(f.as_of or timezone.localdate()).isoformat()}")
        elif key == "period":
            start, end = period_of(f)
            lines.append(f"Хугацаа: {start.isoformat()} – {end.isoformat()}")
        elif key == "branch" and f.branch is not None:
            lines.append(f"Салбар: {_name(Branch.objects, f.branch) or '—'}")
        elif key == "department" and f.department is not None:
            lines.append(f"Хэлтэс: {_name(Department.objects, f.department) or '—'}")
        elif key == "position" and f.position is not None:
            lines.append(f"Албан тушаал: {_name(Position.objects, f.position) or '—'}")
        elif key == "gender" and f.gender:
            lines.append(f"Хүйс: {GENDERS[f.gender]}")
        elif key == "change" and f.change:
            lines.append(f"Өөрчлөлт: {MOVEMENT_KINDS.get(f.change, '—')}")
        elif key == "reason" and f.reason is not None:
            lines.append(f"Шалтгаан: {_name(FiredReason.objects, f.reason) or '—'}")
        elif key == "order_type" and f.order_type is not None:
            lines.append(f"Тушаалын төрөл: {ORDER_TYPES.get(f.order_type, '—')}")
        elif key == "discipline" and f.discipline is not None:
            lines.append(f"Шийтгэлийн төрөл: {_name(DisciplineType.objects, f.discipline) or '—'}")
        elif key == "employee" and f.employee is not None:
            person = Employee.objects.filter(pk=f.employee).first()
            lines.append(f"Ажилтан: {person or '—'}")
        elif key == "leave_type" and f.leave_type is not None:
            lines.append(f"Төрөл: {_name(LeaveTypeRow.objects, f.leave_type) or '—'}")
        elif key == "leave_state" and f.leave_state:
            lines.append(f"Төлөв: {LEAVE_STATES[f.leave_state]}")
        elif key == "absence_type" and f.absence_type is not None:
            lines.append(f"Төрөл: {_name(AbsenceType.objects, f.absence_type) or '—'}")
        elif key == "age_range" and (f.age_from is not None or f.age_to is not None):
            low = "" if f.age_from is None else str(f.age_from)
            high = "" if f.age_to is None else str(f.age_to)
            lines.append(f"Нас: {low} – {high}")
        elif key == "attribute":
            lines.append(f"Шинж: {ATTRIBUTES[f.attribute or 'gender']}")
        elif key == "contact_type" and f.contact_type is not None:
            lines.append(f"Холбоо барих төрөл: {_name(ContactType.objects, f.contact_type) or '—'}")
        elif key == "year":
            lines.append(f"Он: {f.year or timezone.localdate().year}")
        elif key == "tr_type" and f.tr_type is not None:
            lines.append(f"Хэлбэр: {TRAINING_TYPES.get(f.tr_type, '—')}")
        elif key == "quarter":
            lines.append(f"Улирал: {f.quarter or this_quarter()}")
        elif key == "present_type" and f.present_type is not None:
            lines.append(f"Бэлгийн төрөл: {_name(PresentType.objects, f.present_type) or '—'}")
    return lines
