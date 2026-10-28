"""C6 «Чөлөө хүссэн жагсаалт»: every leave row of the period, with its state and its source.

Rows come from `leave.services.rows.leaves` (the overlap rule: a leave that starts before the period and ends inside it
counts). Every state is shown unless the state filter narrows it, so a cancelled or rejected request stays visible
with its state. Old-program rows are included and marked as such. Reports never write.
"""

from dataclasses import dataclass

from accounts.models import User
from django.utils import timezone
from leave.services import rows
from leave.services.rows import LeaveRow, State
from macs.models import LeaveAssign

from reports.filters import Filters, period_of
from reports.leave_common import LEAVE_NEEDS, Person, detail_url, people, sort_key
from reports.types import Column, Report

STATE_BY_KEY: dict[str, State] = {
    "recorded": State.RECORDED,
    "cancelled": State.CANCELLED,
    "mistake": State.MISTAKE,
    "rejected": State.REJECTED,
}


@dataclass(frozen=True)
class Line:
    person: Person
    leave: LeaveRow


def _rows(user: User, f: Filters) -> list[Line]:
    """The leave rows of the period for the people the user may see, newest start first, then by name."""
    start, end = period_of(f)
    by_id = {p.employee.pk: p for p in people(user, f, timezone.localdate())}
    wanted = STATE_BY_KEY.get(f.leave_state)
    lines: list[Line] = []
    for lv in rows.leaves(employee_ids=list(by_id), start=start, end=end):
        if wanted is not None and lv.state is not wanted:
            continue
        if f.leave_type is not None and lv.leave_type.pk != f.leave_type:
            continue
        lines.append(Line(person=by_id[lv.employee_id], leave=lv))
    return sorted(lines, key=lambda line: sort_key(line.person, line.leave.start))


def _source(line: Line) -> str:
    return "Хуучин програм" if line.leave.from_old_system else "Info HR"


COLUMNS: tuple[Column, ...] = (
    Column(key="start", label="Эхлэх", value=lambda line: line.leave.start),
    Column(key="end", label="Дуусах", value=lambda line: line.leave.end),
    Column(key="code", label="Код", value=lambda line: line.person.employee.code),
    Column(
        key="name",
        label="Ажилтан",
        value=lambda line: line.person.employee.full_name,
        href=lambda line: detail_url(line.person.employee),
    ),
    Column(key="department", label="Хэлтэс", value=lambda line: line.person.department),
    Column(key="type", label="Төрөл", value=lambda line: line.leave.leave_type.name),
    Column(key="days", label="Хоног", value=lambda line: line.leave.days, numeric=True),
    Column(key="state", label="Төлөв", value=lambda line: line.leave.state.value),
    Column(key="comment", label="Тайлбар", value=lambda line: line.leave.comment or None),
    Column(key="source", label="Эх сурвалж", value=_source),
)

REPORT = Report(
    key="leave-requests",
    title="Чөлөө хүссэн жагсаалт",
    filters=("period", "leave_state", "leave_type", "department"),
    columns=COLUMNS,
    default_columns=tuple(c.key for c in COLUMNS),
    rows=_rows,
    needs=LEAVE_NEEDS,
    source=LeaveAssign,
    group_options=("department", "type", "state"),
)
