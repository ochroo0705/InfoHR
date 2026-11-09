"""The budget line shown on a vacancy: free posts for its position and branch, a warning when there are none.

Read-only and advisory: nothing here blocks a vacancy (the hire form's `slots.gate` is the hard check). It reads the
numbers from `employees.services.slots.check`, so it can never disagree with the slot screen. Shown only while the
company's `enforce_position_slots` switch is on. A vacancy has no contract field, so the Main kind is counted.
"""

from dataclasses import dataclass
from datetime import date

from accounts import modules
from django.db.models import Count, Q
from django.utils import timezone
from employees.models import CompanySettings
from employees.services import slots
from employees.slot_kind import MAIN
from macs.models import Branch, Position

from recruitment.models import Stage, Vacancy, VacancyStatus


@dataclass(frozen=True)
class SlotLine:
    numbers: str  # «2026 он · орон тоо 3 · ажиллаж буй 2 · сул 1»; empty when there is no branch to check
    warning: str  # one short reason; empty when all is well


def _on(start: date | None) -> date:
    """The day the budget is read on, as the slot screen does: today for this year, else the year's first day."""
    today = timezone.localdate()
    year = start.year if start is not None else today.year
    return today if year == today.year else date(year, 1, 1)


def _reserved(position: Position, branch: Branch, year: int, exclude: int | None) -> int:
    """People the other open vacancies of this position and branch (starting in `year`) still want to hire."""
    rows = (
        Vacancy.objects.filter(position=position, branch=branch, status=VacancyStatus.OPEN)
        .annotate(hired=Count("candidates", filter=Q(candidates__stage=Stage.HIRED)))
        .values_list("headcount", "hired", "desired_start")
    )
    if exclude is not None:
        rows = rows.exclude(pk=exclude)
    this_year = timezone.localdate().year
    return sum(max(want - hired, 0) for want, hired, start in rows if (start.year if start else this_year) == year)


def describe(
    *,
    position: Position | None,
    branch: Branch | None,
    start: date | None,
    headcount: int,
    exclude_vacancy: int | None = None,
) -> SlotLine | None:
    """The line for this vacancy, or None when it is not to be shown (switch off, no position chosen yet)."""
    if position is None or not modules.enabled("slots") or not CompanySettings.get().enforce_position_slots:
        return None
    on = _on(start)
    if branch is None:
        return SlotLine(numbers="", warning="Орон тоо шалгахын тулд салбар сонгоно уу.")
    result = slots.check(position, branch, kind=MAIN, on=on)
    reserved = _reserved(position, branch, on.year, exclude_vacancy)
    numbers = f"{on.year} он · орон тоо {result.posts} · ажиллаж буй {result.used} · сул {max(result.free, 0)}"
    available = result.free - reserved
    if result.posts == 0:  # nothing planned: the hint to add a post, not «no free post left»
        warning = slots.no_posts_message(position, branch, on.year, MAIN)
    elif result.free <= 0:
        warning = "Сул орон тоо алга."
    elif available <= 0:
        warning = "Сул орон тоог өөр нээлттэй ажлын байр авна."
    elif headcount > available:
        warning = f"Сул орон тоо хүрэхгүй: {available}."
    else:
        warning = ""
    return SlotLine(numbers=numbers, warning=warning)
