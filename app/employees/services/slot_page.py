"""The request-free part of the position-slot screen «Орон тооны төлөвлөгөө»: the year from the query string, the day
people are counted on, the lines of the budget table with the people using each row, the totals and the kind label.

The views (employees.views_slots) and, later, the API routes call these functions; none of them reads the request.
The counting rule itself lives in employees.services.slots.
"""

from dataclasses import dataclass
from datetime import date
from typing import cast

from macs.models import Branch, NazgRow, Position

from employees.services import slots
from employees.slot_kind import TEMPORARY

MIN_YEAR, MAX_YEAR = 2000, 2100


def exists_message(holder: NazgRow) -> str:
    """The refusal when the key (position, branch, kind, year) is already held by another row."""
    return (
        f"Ийм мөр аль хэдийн байна ({cast(Position, holder.position).name}, {cast(Branch, holder.branch).name}, "
        f"{slots.KIND_LABELS.get(holder.kind, holder.kind)}, {holder.year} он: орон тоо {holder.qty}). "
        "Шинэ мөр нэмэхгүй, жагсаалтаас тэр мөрийг нээж засна уу."
    )


@dataclass(frozen=True)
class SlotLine:
    row: NazgRow
    posts: int
    used: int
    free: int  # negative when more people use the row than it has posts


@dataclass(frozen=True)
class SlotTotals:
    posts: int
    used: int
    free: int


def year_param(raw: str | None, default: int) -> int:
    """A year from the query string; anything that is not a four-digit year in range is the default."""
    if raw and len(raw) == 4 and raw.isascii() and raw.isdigit() and MIN_YEAR <= int(raw) <= MAX_YEAR:
        return int(raw)
    return default


def used_on(year: int, today: date) -> date:
    """The day the screen counts people on: today for the current year, else the year's first day (so the people who
    work at any time in that year are counted, as the hire check counts people who start later in the year)."""
    return today if year == today.year else date(year, 1, 1)


def slot_lines(year: int, today: date, *, on: date | None = None) -> list[SlotLine]:
    """Every row of `year`, in screen order, with the people using it. `on` overrides the counting day (default
    `used_on(year, today)`); it is for callers that already computed the day, the API passes only `today`."""
    rows = list(
        NazgRow.objects.filter(year=year)
        .select_related("position", "branch")
        .order_by("position__name", "branch__name", "kind", "pk")
    )
    used = slots.used_by_key(year, on if on is not None else used_on(year, today))
    lines: list[SlotLine] = []
    for row in rows:
        count = used.get((row.position_id, row.branch_id, row.kind), 0)
        lines.append(SlotLine(row=row, posts=row.qty, used=count, free=row.qty - count))
    return lines


def totals(lines: list[SlotLine]) -> SlotTotals:
    return SlotTotals(
        posts=sum(line.posts for line in lines),
        used=sum(line.used for line in lines),
        free=sum(line.free for line in lines),
    )


def kind_label(kind: str) -> str:
    """The Mongolian kind name shown on the screen, as `_slot_rows.html` draws it."""
    return "Түр" if kind == TEMPORARY else "Үндсэн"
