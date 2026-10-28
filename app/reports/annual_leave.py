"""C1 «Ээлжийн амралтын тайлан»: each person's annual leave for the work year that contains the as-of date.

The numbers come only from `leave.services.ledger.periods`, the same ones the employee page and `/leave/balances/`
show. A person with no work-year period on the date keeps a row with blank numbers and a note, never a missing row.
"""

from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.utils import timezone
from leave.services import entitlement, ledger
from leave.services.ledger import Period

from reports.filters import Filters
from reports.leave_common import LEAVE_NEEDS, Person, detail_url, people
from reports.types import Column, Report

NOTE = (
    "Ажлын жилийн эрх, эдэлсэн, үлдсэн хоног (ажилтны хуудастай ижил тооцоо). "
    "Ирээдүйд бүртгэсэн чөлөө «Эдэлсэн»-д орно."
)
NO_PERIOD = "Ажлын жилийн эрх бүртгэгдээгүй"


@dataclass(frozen=True)
class Line:
    person: Person
    period: Period | None  # the work year containing the as-of date; None when no period contains it
    waiting_until: date | None  # the right to leave starts on this day, when it is after the as-of date
    configured: bool = True  # False when no leave type uses the annual balance yet: the note says so


def annual_lines(user: User, f: Filters) -> list[Line]:
    """Everyone the user may see who has not left on the as-of date, with the period that contains that date."""
    as_of = f.as_of or timezone.localdate()
    configured = ledger.annual_configured()
    lines: list[Line] = []
    for person in people(user, f, as_of):
        if person.state == "left":
            continue
        found, _ = ledger.periods(person.employee, timezone.localdate())
        period = next((p for p in found if p.start <= as_of <= p.end), None)
        eligible = entitlement.eligible_from(person.employee)
        waiting = eligible if eligible is not None and as_of < eligible else None
        lines.append(Line(person=person, period=period, waiting_until=waiting, configured=configured))
    return lines


def _note_text(line: Line) -> str | None:
    """The reasons a row's numbers are blank or unusual, joined; None when there is nothing to say."""
    parts: list[str] = []
    if line.period is None:
        parts.append(NO_PERIOD if line.configured else ledger.NOT_CONFIGURED)
    if line.waiting_until is not None:
        parts.append(f"Эрх {line.waiting_until.isoformat()}-аас")
    if line.period is not None and line.period.doubled:
        parts.append("Давхар эрхтэй")
    return "; ".join(parts) or None


def _period_value(line: Line, pick: str) -> object:
    """One number or date of the line's period; None when the row has no period."""
    return getattr(line.period, pick) if line.period is not None else None


def _note(f: Filters) -> str:
    """The same grey line whatever the filters: it says where the numbers come from."""
    return NOTE


COLUMNS: tuple[Column, ...] = (
    Column(key="code", label="Код", value=lambda line: line.person.employee.code),
    Column(
        key="name",
        label="Ажилтан",
        value=lambda line: line.person.employee.full_name,
        href=lambda line: detail_url(line.person.employee),
    ),
    Column(key="department", label="Хэлтэс", value=lambda line: line.person.department),
    Column(key="start", label="Эхлэх", value=lambda line: _period_value(line, "start")),
    Column(key="end", label="Дуусах", value=lambda line: _period_value(line, "end")),
    Column(key="granted", label="Эрх", value=lambda line: _period_value(line, "granted"), numeric=True),
    Column(key="taken", label="Эдэлсэн", value=lambda line: _period_value(line, "taken"), numeric=True),
    Column(key="left", label="Үлдэгдэл", value=lambda line: _period_value(line, "left"), numeric=True),
    Column(key="note", label="Тайлбар", value=_note_text),
)

REPORT = Report(
    key="annual-leave",
    title="Ээлжийн амралтын тайлан",
    filters=("as_of", "branch", "department"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=annual_lines,
    needs=LEAVE_NEEDS,
    source=None,
    group_options=("department",),
    note=_note,
)
