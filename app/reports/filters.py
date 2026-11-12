import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from urllib.parse import urlencode

from config.params import date_param, id_param
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

from reports import marks as marks_mod
from reports import rules as rules_mod
from reports import totals as totals_mod
from reports.column_filters import describe_extra, name_of, parse_extra

STATES: dict[str, str] = {
    "working": "Ажиллаж байгаа",
    "upcoming": "Удахгүй ажилд орох",
    "left": "Гарсан",
    "all": "Бүгд",
}
GENDERS: dict[str, str] = {"M": "Эрэгтэй", "F": "Эмэгтэй"}
# Movement kinds the change filter offers: the rows B1 and B2 show (ChangeType labels).
MOVEMENT_KINDS: dict[str, str] = {
    k: ChangeType(k).label for k in ("hire", "rehire", "transfer", "promotion", "demotion", "termination")
}
ORDER_TYPES: dict[int, str] = dict(OrderType.choices)
# Employee types the staff list filters by (JobRecord.emptype, else Employee.emptype). The number is the stored code.
EMPTYPES: dict[int, str] = {
    1: "Ажилчид",
    2: "Гадаад нөөц",
    3: "Ажиллаж байсан",
    4: "Орохоор бүртгүүлсэн",
    5: "Гэрээт ажилтан",
    6: "Өндөр настан",
    8: "Хөлсөөр ажиллах гэрээтэй",
    9: "Туршилтын хугацааны ажилтан",
}
# Employee types with no working state: the state filter is ignored for them and its control is disabled. 6 is here
# because a pension exit saves its job as left (events: termination), so the working state would hide them.
NO_WORKING_STATE: frozenset[int] = frozenset({2, 3, 4, 6})
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
# The views a report can show its rows in (the switcher). "table" is the default and is never written to the address.
LAYOUTS = ("table", "board", "calendar", "timeline", "cards", "chart", "pivot")
CHARTS = ("bar", "stacked", "line", "donut")
MIN_MONTH_YEAR = 1900
_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])")
# The new layout options: a date grouping, a percent, a chart order, a board order, the calendar's yearly repeat.
GRAINS = ("month", "quarter", "year")
SHOWS = ("pct", "rowpct", "colpct")
SORTS = ("value", "valueasc")
ORDERS = ("count",)
_FOUR_DIGITS = re.compile(r"[0-9]{4}")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# Column, group and sort keys are short lowercase words. A sort key may start with "-" for descending order.
# Sort takes up to MAX_SORT_KEYS comma-separated keys and group up to MAX_GROUP_KEYS.
MAX_SORT_KEYS = 5
MAX_GROUP_KEYS = 3
_KEY = re.compile(r"[a-z_]{1,40}")
_SORT_KEY = re.compile(r"-?[a-z_]{1,40}")
_GROUP_KEY = re.compile(r"[a-z_]{1,40}")


@dataclass(frozen=True)
class Filters:
    state: str = "working"
    as_of: date | None = None  # None = today
    branch: int | None = None
    department: int | None = None
    position: int | None = None
    gender: str = ""  # "" = all, "M" or "F"
    emptype: int | None = None  # a key of EMPTYPES; None = all types
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
    mode: str = ""  # "" = one row per person; "children" = one row per child (spike-builder only)
    contact_type: int | None = None  # a contact type id (macs ContactType)
    year: int | None = None  # a survey year, 1990-2100; None = this year
    tr_type: int | None = None  # a key of TRAINING_TYPES (1 domestic, 2 foreign); None = all
    quarter: int | None = None  # a quarter, 1-4; None = this quarter
    present_type: int | None = None  # a gift type id (macs PresentType)
    columns: tuple[str, ...] = ()  # () = the report's default columns
    group: str = ""
    sort: str = ""  # column key; a leading "-" sorts descending
    extra: tuple[tuple[str, str], ...] = ()  # column filters: (parameter, value) pairs; see column_filters.py
    rules: str = ""  # the rule tree as compact JSON (rules.dump_rules); "" = no rules
    totals: str = ""  # footer totals «col:agg,col:agg» (totals.dump_totals); "" = none
    marks: str = ""  # conditional colours as compact JSON (marks.dump_marks); "" = none
    pin: int = 0  # how many leading columns stay fixed when scrolling sideways, 0-3
    layout: str = ""  # a key of LAYOUTS; "" = the table
    lby: str = ""  # the layout's main column key (board lanes, calendar/timeline start, chart category, pivot row)
    lby2: str = ""  # the layout's second column key (timeline end, pivot column)
    lval: str = ""  # what a chart or pivot adds up: "count" or one "col:agg"; "" = count
    lchart: str = ""  # a key of CHARTS; "" = bar
    lmonth: str = ""  # the calendar month as "YYYY-MM"; "" = this month
    lgrain: str = ""  # a key of GRAINS: a date category grouped by month, quarter or year; "" = as the dates are
    lshow: str = ""  # a key of SHOWS: a percent of the total (chart, pivot) or of the row or column; "" = none
    lsort: str = ""  # a key of SORTS: a chart's order, high to low or low to high; "" = the category order
    lorder: str = ""  # "count" = a board's lanes by number of cards; "" = alphabetical
    lrep: str = ""  # the calendar's yearly repeat: "1" yes, "0" no; "" = automatic
    lweek: str = ""  # the calendar's week as a date "YYYY-MM-DD" (its Monday); "" = the month view
    lyear: str = ""  # the timeline's year window as four digits, or "all" (no window); "" = this year (the default)
    lgroup: str = ""  # the timeline's grouping column key (a category column); "" = no grouping
    lval2: str = ""  # the pivot's second value, as lval ("count" or "col:agg"); "" = no second value


def _keys(text: str, pattern: re.Pattern[str], limit: int) -> str:
    """A comma-separated list of keys: every part must match, at most `limit` parts, a repeated key is dropped.
    Any bad part gives "" for the whole value."""
    if not text:
        return ""
    parts = text.split(",")
    if len(parts) > limit or any(pattern.fullmatch(part) is None for part in parts):
        return ""
    kept: list[str] = []
    seen: set[str] = set()
    for part in parts:
        bare = part.lstrip("-")
        if bare not in seen:
            seen.add(bare)
            kept.append(part)
    return ",".join(kept)


def _order_type(value: str | None) -> int | None:
    number = id_param(value)
    return number if number in ORDER_TYPES else None


def _emptype(value: str | None) -> int | None:
    number = id_param(value)
    return number if number in EMPTYPES else None


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


def _layout_key(value: str | None) -> str:
    """A column key for lby or lby2, else "". Never raises."""
    return value if value and _KEY.fullmatch(value) else ""


def _layout_value(value: str | None) -> str:
    """«count», or the first valid «col:agg» pair, else "". Never raises."""
    if value == "count":
        return value
    pairs = totals_mod.parse_totals(value or "")
    return f"{pairs[0][0]}:{pairs[0][1]}" if pairs else ""


def _month(value: str | None) -> str:
    """A month as «YYYY-MM» with the year from MIN_MONTH_YEAR to MAX_YEAR, else "". Never raises."""
    match = _MONTH.fullmatch(value or "")
    if match is None or not MIN_MONTH_YEAR <= int(match.group(1)) <= MAX_YEAR:
        return ""
    return value or ""


def _choice(value: str | None, options: tuple[str, ...]) -> str:
    """The value when it is one of `options`, else "". Never raises."""
    return value if value in options else ""


def _week(value: str | None) -> str:
    """A date as «YYYY-MM-DD» with the year from MIN_MONTH_YEAR to MAX_YEAR, else "". Never raises."""
    if not value or _DAY.fullmatch(value) is None:
        return ""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return ""
    return value if MIN_MONTH_YEAR <= day.year <= MAX_YEAR else ""


def _year(value: str | None) -> str:
    """Four digits from MIN_MONTH_YEAR to MAX_YEAR, or «all» (no year window), else "". Never raises."""
    if value == "all":
        return value
    if not value or _FOUR_DIGITS.fullmatch(value) is None:
        return ""
    return value if MIN_MONTH_YEAR <= int(value) <= MAX_YEAR else ""


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
    sort = _keys(get.get("sort", ""), _SORT_KEY, MAX_SORT_KEYS)
    leave_state = get.get("leave_state", "")
    attribute = get.get("attribute", "")
    mode = get.get("mode", "")
    rule_tree = rules_mod.parse_rules(get.get("rules", ""))
    totals = totals_mod.dump_totals(totals_mod.parse_totals(get.get("totals", "")))
    marks = marks_mod.dump_marks(marks_mod.parse_marks(get.get("marks", "")))
    layout = get.get("layout", "")
    lchart = get.get("lchart", "")
    return Filters(
        state=state if state in STATES else "working",
        as_of=date_param(get.get("as_of")),
        branch=id_param(get.get("branch")),
        department=id_param(get.get("department")),
        position=id_param(get.get("position")),
        gender=gender if gender in GENDERS else "",
        emptype=_emptype(get.get("emptype")),
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
        mode=mode if mode == "children" else "",
        contact_type=id_param(get.get("contact_type")),
        year=_int_in(get.get("year"), MIN_YEAR, MAX_YEAR),
        tr_type=_training_type(get.get("tr_type")),
        quarter=_int_in(get.get("quarter"), 1, 4),
        present_type=id_param(get.get("present_type")),
        columns=tuple(columns[:MAX_COLUMNS]),
        group=_keys(group, _GROUP_KEY, MAX_GROUP_KEYS),
        sort=sort,
        extra=parse_extra(get),
        rules=rules_mod.dump_rules(rule_tree),
        totals=totals,
        marks=marks,
        pin=_int_in(get.get("pin"), 0, 3) or 0,
        layout=layout if layout in LAYOUTS and layout != "table" else "",
        lby=_layout_key(get.get("lby")),
        lby2=_layout_key(get.get("lby2")),
        lval=_layout_value(get.get("lval")),
        lchart=lchart if lchart in CHARTS else "",
        lmonth=_month(get.get("lmonth")),
        lgrain=_choice(get.get("lgrain"), GRAINS),
        lshow=_choice(get.get("lshow"), SHOWS),
        lsort=_choice(get.get("lsort"), SORTS),
        lorder=_choice(get.get("lorder"), ORDERS),
        lrep=_choice(get.get("lrep"), ("1", "0")),
        lweek=_week(get.get("lweek")),
        lyear=_year(get.get("lyear")),
        lgroup=_layout_key(get.get("lgroup")),
        lval2=_layout_value(get.get("lval2")),
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
    for name, value in f.extra:
        params[name] = value
    if f.emptype is not None:
        params["emptype"] = f.emptype
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
    if f.mode == "children":
        params["mode"] = f.mode
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
    if f.rules:
        params["rules"] = f.rules
    if f.totals:
        params["totals"] = f.totals
    if f.marks:
        params["marks"] = f.marks
    if f.pin > 0:
        params["pin"] = f.pin
    if f.layout and f.layout != "table":
        params["layout"] = f.layout
    if f.lby:
        params["lby"] = f.lby
    if f.lby2:
        params["lby2"] = f.lby2
    if f.lval:
        params["lval"] = f.lval
    if f.lchart:
        params["lchart"] = f.lchart
    if f.lmonth:
        params["lmonth"] = f.lmonth
    for name in ("lgrain", "lshow", "lsort", "lorder", "lrep", "lweek", "lyear", "lgroup", "lval2"):
        if getattr(f, name):
            params[name] = getattr(f, name)
    return urlencode(params, doseq=True)


def period_of(f: Filters) -> tuple[date, date]:
    """The first and last day of the period. A missing end is the calendar year's; reversed dates are swapped."""
    today = timezone.localdate()
    start = f.date_from or date(today.year, 1, 1)
    end = f.date_to or date(today.year, 12, 31)
    return (start, end) if start <= end else (end, start)


def describe(
    f: Filters, shown: tuple[str, ...], *, for_log: bool = False, labels: dict[str, str] | None = None
) -> list[str]:
    """Filter lines for print and Excel, in the order of `shown`. A filter that is set but has no name to show
    (an unknown id, a name left empty) reads «—», so the paper never hides an applied filter.
    `for_log` is the system log's label: it names no person (the employee line only says that one was chosen), and its
    rules line names only the columns the rules use, never the values typed."""
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
            lines.append(f"Салбар: {name_of(Branch.objects, f.branch) or '—'}")
        elif key == "department" and f.department is not None:
            lines.append(f"Хэлтэс: {name_of(Department.objects, f.department) or '—'}")
        elif key == "position" and f.position is not None:
            lines.append(f"Албан тушаал: {name_of(Position.objects, f.position) or '—'}")
        elif key == "gender" and f.gender:
            lines.append(f"Хүйс: {GENDERS[f.gender]}")
        elif key == "emptype" and f.emptype is not None:
            lines.append(f"Ажилтны төрөл: {EMPTYPES[f.emptype]}")
        elif key == "change" and f.change:
            lines.append(f"Өөрчлөлт: {MOVEMENT_KINDS.get(f.change, '—')}")
        elif key == "reason" and f.reason is not None:
            lines.append(f"Шалтгаан: {name_of(FiredReason.objects, f.reason) or '—'}")
        elif key == "order_type" and f.order_type is not None:
            lines.append(f"Тушаалын төрөл: {ORDER_TYPES.get(f.order_type, '—')}")
        elif key == "discipline" and f.discipline is not None:
            lines.append(f"Шийтгэлийн төрөл: {name_of(DisciplineType.objects, f.discipline) or '—'}")
        elif key == "employee" and f.employee is not None:
            if for_log:
                lines.append("Ажилтан: сонгосон")
            else:
                # Relies on reports/table.py:86 resetting an invisible employee filter first.
                person = Employee.objects.filter(pk=f.employee).first()
                lines.append(f"Ажилтан: {person or '—'}")
        elif key == "leave_type" and f.leave_type is not None:
            lines.append(f"Төрөл: {name_of(LeaveTypeRow.objects, f.leave_type) or '—'}")
        elif key == "leave_state" and f.leave_state:
            lines.append(f"Төлөв: {LEAVE_STATES[f.leave_state]}")
        elif key == "absence_type" and f.absence_type is not None:
            lines.append(f"Төрөл: {name_of(AbsenceType.objects, f.absence_type) or '—'}")
        elif key == "age_range" and (f.age_from is not None or f.age_to is not None):
            low = "" if f.age_from is None else str(f.age_from)
            high = "" if f.age_to is None else str(f.age_to)
            lines.append(f"Нас: {low} – {high}")
        elif key == "attribute":
            lines.append(f"Шинж: {ATTRIBUTES[f.attribute or 'gender']}")
        elif key == "mode" and f.mode == "children":
            lines.append("Горим: хүүхэд бүрээр")
        elif key == "contact_type" and f.contact_type is not None:
            lines.append(f"Холбоо барих төрөл: {name_of(ContactType.objects, f.contact_type) or '—'}")
        elif key == "year":
            lines.append(f"Он: {f.year or timezone.localdate().year}")
        elif key == "tr_type" and f.tr_type is not None:
            lines.append(f"Хэлбэр: {TRAINING_TYPES.get(f.tr_type, '—')}")
        elif key == "quarter":
            lines.append(f"Улирал: {f.quarter or this_quarter()}")
        elif key == "present_type" and f.present_type is not None:
            lines.append(f"Бэлгийн төрөл: {name_of(PresentType.objects, f.present_type) or '—'}")
    lines.extend(describe_extra(f.extra))
    if f.rules:
        tree = rules_mod.parse_rules(f.rules)
        if for_log:
            named = dict.fromkeys((labels or {}).get(column, column) for column in rules_mod.rule_columns(tree))
            names = ", ".join(named)
            if names:
                lines.append(f"Нөхцөл: {names}")
        else:
            words = rules_mod.describe_rules(tree, labels or {})
            if words:
                lines.append(f"Нөхцөл: {words}")
    return lines
