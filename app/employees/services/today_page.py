"""The Today page rules, shared by the Django page and the API: the away strip shading and the page's facts."""

from datetime import date
from types import SimpleNamespace
from typing import Any

from accounts.models import User

from employees import access, attention, company_stats
from employees import today as facts
from employees.listing import employee_rows

# Shade keys of the away strip, and the classes each one renders with (the Django template and the React page use them).
SHADE_CLASSES: dict[str, str] = {
    "off": "bg-slate-100 text-slate-400",  # weekend, public holiday, or no count
    "zero": "bg-sky-50 text-slate-500",  # nobody away
    "low": "bg-sky-200",  # 1 person or more, below 5 % of the headcount
    "mid": "bg-sky-400",  # from 5 % of the headcount
    "high": "bg-sky-600 text-white",  # from 10 % of the headcount
}


def away_shade(count: int | None, off: bool, headcount: int) -> str:
    """The shade key of one day of the away strip (see SHADE_CLASSES)."""
    if off or count is None:
        return "off"
    if count == 0:
        return "zero"
    if headcount and count * 100 >= 10 * headcount:
        return "high"
    if headcount and count * 100 >= 5 * headcount:
        return "mid"
    return "low"


def away_cells(strip: facts.AwayStrip, headcount: int) -> list[SimpleNamespace]:
    """One cell per day of the Today strip, with its shade class (see away_shade)."""
    return [
        SimpleNamespace(
            day=day,
            count=count,
            shade=SHADE_CLASSES[away_shade(count, day.off, headcount)],
        )
        for day, count in zip(strip.days, strip.counts, strict=True)
    ]


def today_facts(user: User, day: date) -> dict[str, Any]:
    """Everything the Today page shows for `user` on `day`, including the attention box (under "box")."""
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), day)
    facts.prime_exts(rows)  # one query for every HR row: the attention rules read it per person
    headcount = facts.headcount(rows)
    strip = facts.away_strip(user, rows, day)
    return {
        "today": day,
        "headcount": headcount,
        "away": facts.away_on(user, rows, day),
        "can_manage": access.can_manage(user),
        "away_strip": strip,
        "away_cells": away_cells(strip, headcount),
        "upcoming_counts": facts.upcoming_counts(facts.upcoming(user, rows, day)),
        "new_hires_count": len(facts.new_hires(rows, day)),  # Ойрын 30 хоног: hires line (count only)
        "show_birthdays": user.has_perm("macs.view_personal"),  # without it the count is always 0: no line
        "holidays": facts.holidays_ahead(day),  # Ойрын 30 хоног: holidays line
        "open_vacancies": facts.open_vacancies(user),  # Ойрын 30 хоног: vacancies line (None: no line)
        "checklist_summary": facts.checklist_summary(user, rows, day),  # Ойрын 30 хоног: checklist line
        "company": company_stats.company(user, rows, day),
        "has_own_page": access.own_employee(user) is not None,  # header link to My page (Миний хуудас)
        "box": attention.box(user, attention.items(user, rows, day)),
    }
