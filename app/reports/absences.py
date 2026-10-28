"""C3 «Амралт, чөлөөний тайлан» (the old program's «Амралт» log) and C5 «Чөлөөтэй буюу байхгүй ажилчид» (who is away).

The old log is read from `macs.Absence`, the read-only mirror of the old «Амралт» grid. It is a side log: it feeds no
balance and has no status. A row with no end date counts as that one day. Leave rows for C5 come from
`leave.services.rows.leaves`, and only counted (recorded) leave covers a date. Reports never write.
"""

from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.db.models import Q
from django.utils import timezone
from leave.services import calendar, rows
from macs.models import Absence, AbsenceType

from reports.filters import Filters, period_of
from reports.leave_common import LEAVE_NEEDS, Person, detail_url, people, sort_key
from reports.types import Column, Report

LEAVE_SOURCE = "Чөлөө"  # a counted leave row written in Info HR
OLD_LOG_SOURCE = "Амралтын бүртгэл (хуучин)"  # a row of the old program's «Амралт» log
NO_TYPE = "—"  # an old-log row whose type row is missing
ABSENCES_NOTE = "Хуучин програмын «Амралт» бүртгэл. Дууссан огноогүй мөр нэг өдөр гэж тооцогдоно."
AWAY_NOTE = "Тухайн өдөр чөлөөтэй (бүртгэсэн чөлөө) эсвэл хуучин програмын амралтын бүртгэлтэй ажилтнууд."


@dataclass(frozen=True)
class Entry:
    person: Person
    kind: str  # the leave type name, or the old-log absence type name
    start: date
    end: date
    source: str  # LEAVE_SOURCE or OLD_LOG_SOURCE
    comment: str


def old_log(people_by_id: dict[int, Person], start: date, end: date, absence_type: int | None) -> list[Entry]:
    """Old-log rows that overlap [start, end] for the given people. A row with no end date is one day, on its start."""
    if not people_by_id:
        return []
    qs = Absence.objects.filter(employee_id__in=list(people_by_id), from_date__lte=end).filter(
        Q(to_date__gte=start) | Q(to_date__isnull=True, from_date__gte=start)
    )
    if absence_type is not None:
        qs = qs.filter(absence_type_id=absence_type)
    found = list(qs.order_by("-from_date", "-id"))
    # no select_related: an inner join would silently drop a row whose type is missing. The database does enforce
    # the type foreign key (macs_public.sql, integ_1768), so such a row should not exist; the NO_TYPE branch is a guard.
    types = AbsenceType.objects.in_bulk({a.absence_type_id for a in found})
    entries: list[Entry] = []
    for a in found:
        person = people_by_id.get(a.employee_id)
        if person is None:
            continue
        kind_row = types.get(a.absence_type_id)
        entries.append(
            Entry(
                person=person,
                kind=kind_row.name if kind_row is not None else NO_TYPE,
                start=a.from_date,
                end=a.to_date or a.from_date,
                source=OLD_LOG_SOURCE,
                comment=a.note or "",
            )
        )
    return entries


def _entry_key(entry: Entry) -> tuple[int, str, str]:
    return sort_key(entry.person, entry.start)


def _absence_rows(user: User, f: Filters) -> list[Entry]:
    start, end = period_of(f)
    by_id = {p.employee.pk: p for p in people(user, f, timezone.localdate())}
    # old_log orders by date and id only; this sort adds the name order the report shows
    return sorted(old_log(by_id, start, end, f.absence_type), key=_entry_key)


def _away_rows(user: User, f: Filters) -> list[Entry]:
    """Counted leave and old-log rows that cover the day. People who have left are not dropped here."""
    day = f.as_of or timezone.localdate()
    by_id = {p.employee.pk: p for p in people(user, f, day)}
    entries: list[Entry] = []
    for lv in rows.leaves(employee_ids=list(by_id), start=day, end=day):
        if not lv.counts or lv.employee_id not in by_id:
            continue
        entries.append(
            Entry(
                person=by_id[lv.employee_id],
                kind=lv.leave_type.name,
                start=lv.start,
                end=lv.end,
                source=LEAVE_SOURCE,
                comment=lv.comment,
            )
        )
    entries.extend(old_log(by_id, day, day, None))
    return sorted(entries, key=_entry_key)


TOTALS_NOTE = (
    "Таслалт, хоцролтын мэдээлэл энд байхгүй: хуучин програмын тооцооллын эх сурвалж тодорхойгүй (OQ-054). "
    "Чөлөөний хоног нь тооцогдсон чөлөөнөөс, амралтын бүртгэл нь хуучин програмын «Амралт» бүртгэлээс."
)


@dataclass(frozen=True)
class Totals:
    person: Person
    leave_days: int  # counted leave days inside the period (working days where the leave crosses an edge)
    log_entries: int  # rows of the old «Амралт» log overlapping the period
    log_days: int  # calendar days of those rows, clipped to the period


def _leave_days_in(lv: rows.LeaveRow, start: date, end: date) -> int:
    """A leave wholly inside the period uses its own days; one crossing an edge counts only the part inside,
    and never more than the leave's own days."""
    if lv.start >= start and lv.end <= end:
        return lv.days
    return min(lv.days, calendar.working_days(max(lv.start, start), min(lv.end, end)))


def _totals_rows(user: User, f: Filters) -> list[Totals]:
    start, end = period_of(f)
    by_id = {p.employee.pk: p for p in people(user, f, timezone.localdate())}
    leave_days: dict[int, int] = {}
    for lv in rows.leaves(employee_ids=list(by_id), start=start, end=end):
        if not lv.counts or lv.employee_id not in by_id:
            continue
        leave_days[lv.employee_id] = leave_days.get(lv.employee_id, 0) + _leave_days_in(lv, start, end)
    log_entries: dict[int, int] = {}
    log_days: dict[int, int] = {}
    for entry in old_log(by_id, start, end, None):
        pk = entry.person.employee.pk
        clipped_start = max(entry.start, start)
        clipped_end = min(entry.end, end)
        log_entries[pk] = log_entries.get(pk, 0) + 1
        # a row whose end is before its start has no days inside the period: never negative
        log_days[pk] = log_days.get(pk, 0) + max(0, (clipped_end - clipped_start).days + 1)
    # `people` order is kept: the report lists people by name
    return [
        Totals(
            person=person,
            leave_days=leave_days.get(pk, 0),
            log_entries=log_entries.get(pk, 0),
            log_days=log_days.get(pk, 0),
        )
        for pk, person in by_id.items()
        if leave_days.get(pk, 0) > 0 or log_entries.get(pk, 0) > 0
    ]


def _start(entry: Entry) -> date:
    return entry.start


def _end(entry: Entry) -> date:
    return entry.end


ABSENCE_COLUMNS: tuple[Column, ...] = (
    Column(key="start", label="Эхэлсэн", value=_start),
    Column(key="end", label="Дууссан", value=_end),
    Column(key="code", label="Код", value=lambda e: e.person.employee.code),
    Column(
        key="name",
        label="Ажилтан",
        value=lambda e: e.person.employee.full_name,
        href=lambda e: detail_url(e.person.employee),
    ),
    Column(key="department", label="Хэлтэс", value=lambda e: e.person.department),
    Column(key="type", label="Төрөл", value=lambda e: e.kind),
    Column(key="note", label="Үндэслэл", value=lambda e: e.comment or None),
)

ABSENCES: Report = Report(
    key="absences",
    title="Амралт, чөлөөний тайлан",
    filters=("period", "absence_type", "department"),
    columns=ABSENCE_COLUMNS,
    default_columns=tuple(c.key for c in ABSENCE_COLUMNS),
    rows=_absence_rows,
    needs=LEAVE_NEEDS,
    source=Absence,
    group_options=("department", "type"),
    note=lambda _f: ABSENCES_NOTE,
)

AWAY_COLUMNS: tuple[Column, ...] = (
    Column(key="code", label="Код", value=lambda e: e.person.employee.code),
    Column(
        key="name",
        label="Ажилтан",
        value=lambda e: e.person.employee.full_name,
        href=lambda e: detail_url(e.person.employee),
    ),
    Column(key="department", label="Хэлтэс", value=lambda e: e.person.department),
    Column(key="type", label="Төрөл", value=lambda e: e.kind),
    Column(key="start", label="Эхлэх", value=_start),
    Column(key="end", label="Дуусах", value=_end),
    Column(key="source", label="Эх сурвалж", value=lambda e: e.source),
    Column(key="comment", label="Тайлбар", value=lambda e: e.comment or None),
)

AWAY: Report = Report(
    key="away-on-date",
    title="Чөлөөтэй буюу байхгүй ажилчид",
    filters=("as_of", "branch", "department"),
    columns=AWAY_COLUMNS,
    default_columns=tuple(c.key for c in AWAY_COLUMNS),
    rows=_away_rows,
    needs=LEAVE_NEEDS,
    source=None,
    group_options=("department", "source"),
    note=lambda _f: AWAY_NOTE,
)


TOTALS_COLUMNS: tuple[Column, ...] = (
    Column(key="code", label="Код", value=lambda t: t.person.employee.code),
    Column(
        key="name",
        label="Ажилтан",
        value=lambda t: t.person.employee.full_name,
        href=lambda t: detail_url(t.person.employee),
    ),
    Column(key="department", label="Хэлтэс", value=lambda t: t.person.department),
    Column(key="leave_days", label="Чөлөөний хоног", value=lambda t: t.leave_days, numeric=True),
    Column(key="log_entries", label="Амралтын бүртгэл (мөр)", value=lambda t: t.log_entries, numeric=True),
    Column(key="log_days", label="Амралтын бүртгэл (хоног)", value=lambda t: t.log_days, numeric=True),
)

TOTALS: Report = Report(
    key="absence-totals",
    title="Чөлөө, таслалт, хоцролтын тайлан",
    filters=("period", "department"),
    columns=TOTALS_COLUMNS,
    default_columns=tuple(c.key for c in TOTALS_COLUMNS),
    rows=_totals_rows,
    needs=LEAVE_NEEDS,
    source=None,
    group_options=("department",),
    note=lambda _f: TOTALS_NOTE,
)
