"""The personal-tab lists: B5 the discipline penalties of a period, B6 the awards of a period.

Rows come from the production `discipline` and `awards` tables. Each row is paired with its person's listing row for
today, so the department and position come from the same service as the screens. A row with no date cannot sit in a
period, so an award without a date is left out. Both lists need the personal-tab right, not only the employee list.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from accounts.models import User
from django.db.models import QuerySet
from django.urls import reverse
from django.utils import timezone
from employees import access, listing
from macs.models import AwardRow, DisciplineRow, Employee

from reports import staff_list
from reports.filters import Filters, period_of
from reports.types import Column, Report

NEEDS = ("macs.view_employees", "macs.view_personal")  # the employee list's right and the personal tab's right


@dataclass(frozen=True)
class ListRow:
    """One penalty or award with the person it belongs to, as the listing service shows them today."""

    item: Any  # the production row: a DisciplineRow or an AwardRow
    row: listing.Row  # the person's listing row for today


def people(user: User) -> QuerySet[Employee]:
    """The people the user may see, without the ones who never worked here."""
    return access.visible_employees(user).exclude(emptype__in=listing.NEVER_WORKED)


def with_rows(items: Sequence[Any], today: date) -> list[ListRow]:
    """Pairs each row with its person's listing row. One service call covers every person in the result, and the
    departments and positions the jobs name are loaded in one query each, so the cells cost no query per row."""
    ids = {item.employee_id for item in items}
    by_pk = {r.employee.pk: r for r in listing.employee_rows(Employee.objects.filter(pk__in=ids), today)}
    found = [ListRow(item, by_pk[item.employee_id]) for item in items if item.employee_id in by_pk]
    staff_list.load_job_names([r.row.job for r in found if r.row.job is not None])
    return found


def full_name(r: ListRow) -> str:
    return r.row.employee.full_name


def detail_url(r: ListRow) -> str:
    return reverse("employees:detail", args=[r.row.employee.pk])


def or_none(text: str | None) -> str | None:
    """The text, or None when it is empty, so the cell sorts last."""
    return text or None


def department(r: ListRow) -> str | None:
    """The person's department today; None when the person has no job row or no department."""
    job = r.row.job
    if job is None or job.department_id is None:
        return None
    return job.department.name


def position(r: ListRow) -> str | None:
    """The person's position today; None when the person has no job row or no position."""
    job = r.row.job
    if job is None or job.position_id is None:
        return None
    return job.position.name


def _discipline_rows(user: User, f: Filters) -> list[ListRow]:
    """B5: the penalties dated in the period, of the people the user may see, sorted by date then name."""
    start, end = period_of(f)
    items = DisciplineRow.objects.select_related("discipline_type").filter(
        employee__in=people(user),
        discipline_date__gte=start,
        discipline_date__lt=end + timedelta(days=1),
    )
    if f.discipline is not None:
        items = items.filter(discipline_type_id=f.discipline)
    found = with_rows(list(items), timezone.localdate())
    return sorted(found, key=lambda r: (r.item.discipline_date, full_name(r)))


def _award_rows(user: User, f: Filters) -> list[ListRow]:
    """B6: the awards dated in the period, of the people the user may see, sorted by date then name."""
    start, end = period_of(f)
    items = AwardRow.objects.filter(
        employee__in=people(user),
        award_date__gte=start,
        award_date__lt=end + timedelta(days=1),
    )
    found = with_rows(list(items), timezone.localdate())
    return sorted(found, key=lambda r: (r.item.award_date or date.min, full_name(r)))


# The columns the two lists share: the person and the job they hold today.
PERSON_COLUMNS: tuple[Column, ...] = (
    Column(key="code", label="Код", value=lambda r: r.row.employee.code),
    Column(key="name", label="Ажилтан", value=full_name, href=detail_url),
    Column(key="department", label="Хэлтэс", value=department),
    Column(key="position", label="Албан тушаал", value=position),
)

DISCIPLINE_COLUMNS: tuple[Column, ...] = (
    Column(key="date", label="Огноо", value=lambda r: r.item.discipline_date),
    *PERSON_COLUMNS,
    Column(key="type", label="Шийтгэлийн төрөл", value=lambda r: r.item.discipline_type.name),
    Column(key="from_org", label="Хаанаас", value=lambda r: or_none(r.item.from_discipline)),
    Column(key="percent", label="Хувь", value=lambda r: r.item.discipline_sal_percent, numeric=True),
    Column(key="end", label="Дуусах огноо", value=lambda r: r.item.discipline_enddate),
    Column(key="description", label="Тайлбар", value=lambda r: or_none(r.item.description)),
)

AWARD_COLUMNS: tuple[Column, ...] = (
    Column(key="date", label="Огноо", value=lambda r: r.item.award_date),
    *PERSON_COLUMNS,
    Column(key="award", label="Шагнал", value=lambda r: r.item.award_name),
    Column(key="from_org", label="Хаанаас", value=lambda r: or_none(r.item.give_org)),
    Column(key="description", label="Тайлбар", value=lambda r: or_none(r.item.description)),
)


def _discipline_note(f: Filters) -> str:
    """The grey line: the department and position are today's, whatever the period."""
    return "Хэлтэс, албан тушаал нь ажилтны өнөөдрийн ажил."


def _award_note(f: Filters) -> str:
    """The grey line: as the penalties, plus that an award with no date is not in any period."""
    return "Хэлтэс, албан тушаал нь ажилтны өнөөдрийн ажил. Огноогүй шагнал орохгүй."


DISCIPLINE = Report(
    key="discipline",
    title="Ажилчдын сахилгын шийтгэл",
    filters=("discipline", "period"),
    columns=DISCIPLINE_COLUMNS,
    default_columns=tuple(c.key for c in DISCIPLINE_COLUMNS),
    rows=_discipline_rows,
    needs=NEEDS,
    source=DisciplineRow,
    group_options=("type", "department"),
    note=_discipline_note,
)

AWARDS = Report(
    key="awards",
    title="Ажилчдын шагнал урамшуулал",
    filters=("period",),
    columns=AWARD_COLUMNS,
    default_columns=tuple(c.key for c in AWARD_COLUMNS),
    rows=_award_rows,
    needs=NEEDS,
    source=AwardRow,
    group_options=("department",),
    note=_award_note,
)
