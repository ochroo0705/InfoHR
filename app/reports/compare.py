"""The two-day comparison («Хоёр өдрийн харьцуулалт»): who joined, left or moved between two days. A row is one
person, so the report offers row selection. Two staff reads (one per day) decide everything.
"""

from dataclasses import dataclass, replace
from datetime import date

from accounts.models import User
from django.urls import reverse
from django.utils import timezone
from employees import listing
from macs.models import Employee

from reports import staff_list
from reports.filters import Filters, period_of
from reports.types import Column, Report

JOINED, LEFT, MOVED = "Орсон", "Гарсан", "Шилжсэн"
KIND_ORDER = {JOINED: 0, MOVED: 1, LEFT: 2}


@dataclass(frozen=True)
class CompareRow:
    employee: Employee
    kind: str  # JOINED, LEFT or MOVED
    before: listing.Row | None  # the person's row on the first day; None for JOINED
    after: listing.Row | None  # the person's row on the second day; None for LEFT


def days(f: Filters) -> tuple[date, date]:
    """The first and second day: the period's ends, the second cut to today (a day not yet come is not compared)."""
    start, end = period_of(f)
    second = min(end, timezone.localdate())
    return min(start, second), second


def _working(user: User, f: Filters, day: date) -> dict[int, listing.Row]:
    """The people working on `day` for the branch filter, by employee pk. The department filter is applied later,
    so a person who moved out of the department is still found."""
    kept, _ = staff_list.kept_rows(user, replace(Filters(), state="working", as_of=day, branch=f.branch))
    return {r.employee.pk: r for r in kept}


def _placement(row: listing.Row) -> tuple[int | None, int | None]:
    """The department and position ids of a row; a row with no job has neither."""
    job = row.job
    return (job.department_id, job.position_id) if job is not None else (None, None)


def _department_id(row: listing.Row | None) -> int | None:
    return row.job.department_id if row is not None and row.job is not None else None


def rows(user: User, f: Filters) -> list[CompareRow]:
    """The people who joined, moved or left between the two days, in the order joined, moved, left."""
    first, second = days(f)
    before = _working(user, f, first)
    after = _working(user, f, second)
    staff_list.load_job_names([r.job for r in [*before.values(), *after.values()] if r.job is not None])
    found: list[CompareRow] = []
    for pk in before.keys() | after.keys():
        was, now = before.get(pk), after.get(pk)
        if was is None:
            kind = JOINED
        elif now is None:
            kind = LEFT
        elif _placement(was) != _placement(now):
            kind = MOVED
        else:
            continue
        employee = now.employee if now is not None else was.employee  # type: ignore[union-attr]
        found.append(CompareRow(employee=employee, kind=kind, before=was, after=now))
    if f.department is not None:
        found = [r for r in found if f.department in (_department_id(r.before), _department_id(r.after))]
    found.sort(key=lambda r: (KIND_ORDER[r.kind], r.employee.family_name or "", r.employee.given_name or ""))
    return found


def _department_name(row: listing.Row | None) -> str | None:
    job = row.job if row is not None else None
    return job.department.name if job is not None and job.department_id is not None else None


def _position_name(row: listing.Row | None) -> str | None:
    job = row.job if row is not None else None
    return job.position.name if job is not None and job.position_id is not None else None


def _detail_url(r: CompareRow) -> str:
    return reverse("employees:detail", args=[r.employee.pk])


COLUMNS: tuple[Column, ...] = (
    Column(key="code", label="Код", value=lambda r: r.employee.code),
    Column(key="name", label="Ажилтан", value=lambda r: r.employee.full_name, href=_detail_url),
    Column(key="kind", label="Өөрчлөлт", value=lambda r: r.kind),
    Column(key="department_before", label="Хэлтэс (өмнө)", value=lambda r: _department_name(r.before)),
    Column(key="department_after", label="Хэлтэс (дараа)", value=lambda r: _department_name(r.after)),
    Column(key="position_before", label="Албан тушаал (өмнө)", value=lambda r: _position_name(r.before)),
    Column(key="position_after", label="Албан тушаал (дараа)", value=lambda r: _position_name(r.after)),
)


def _note(f: Filters) -> str:
    first, second = days(f)
    return (
        f"{first.isoformat()} ба {second.isoformat()} өдрийн ажиллаж байсан ажилтнуудыг харьцуулав. "
        "«Хугацаа»-ны эхний өдөр нь эхний өдөр, сүүлийн өдөр нь хоёр дахь өдөр (өнөөдрөөс хойш биш). "
        "Хуучин програмаас ирсэн, ажлын түүхгүй ажилтныг хоёр өдөрт хоёуланд нь өнөөдрийн төлөв, хэлтэс, "
        "албан тушаалаар нь уншина: тэдний гарсан, шилжсэн нь энд гарахгүй."
    )


REPORT = Report(
    key="staff-compare",
    title="Хоёр өдрийн харьцуулалт",
    filters=("branch", "department", "period"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=rows,
    needs=("macs.view_employees",),
    source=Employee,
    group_options=("kind", "department_before", "department_after"),
    person=lambda r: r.employee.pk,
    note=_note,
)
