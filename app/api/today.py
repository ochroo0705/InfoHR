"""GET /api/v1/today: the Today page's facts for the signed-in user, from services.today_page (the page's rules)."""

from dataclasses import asdict
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

from accounts.models import User
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.dateformat import format as date_format
from employees import access, company_stats
from employees import today as facts
from employees.listing import employee_rows
from employees.services.today_page import today_facts
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from api.attention import AttentionBoxOut, box_out

today_router = Router(tags=["today"])


class ShortcutsOut(Schema):
    add_employee: bool
    record_leave: bool
    orders: bool


class StripCellOut(Schema):
    day: str  # YYYY-MM-DD
    num: int  # the day of the month
    weekday: str
    count: int | None  # people away; None on an off day or without the leave right
    shade: str  # a key of services.today_page.SHADE_CLASSES
    is_today: bool
    holiday: str  # the public holiday's name, "" otherwise
    clickable: bool  # the count opens the names of that day


class StripOut(Schema):
    show_leave: bool
    first: str
    last: str
    cells: list[StripCellOut]
    today_line: str  # the sentence under the strip (data-away-today)


class HolidayOut(Schema):
    day: str
    name: str


class ChecklistOut(Schema):
    open: int
    overdue: int


class UpcomingOut(Schema):
    holidays: list[HolidayOut]
    open_vacancies: int | None  # None: no recruitment right, no line
    checklist: ChecklistOut | None  # None: no checklist right, no line
    show_birthdays: bool
    birthdays: int
    anniversaries: int
    new_hires: int


class TodayCompanyOut(Schema):
    hires_month: int
    leavers_month: int


class TodayOut(Schema):
    today: str
    headcount: int
    away_today: int
    has_own_page: bool
    shortcuts: ShortcutsOut
    box: AttentionBoxOut
    show_views: bool
    strip: StripOut
    upcoming: UpcomingOut
    company: TodayCompanyOut | None  # None without the employee-list right


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _today_line(strip: facts.AwayStrip) -> str:
    """The sentence under the away strip, as the Django template writes it."""
    if strip.today_split:
        return "Өнөөдөр: " + " · ".join(f"{name} {n}" for name, n in strip.today_split)
    if strip.days[0].off:
        return "Өнөөдөр амралтын өдөр"
    return "Өнөөдөр чөлөөтэй хүн алга."


def _strip_out(strip: facts.AwayStrip, cells: list[SimpleNamespace]) -> dict[str, object]:
    return {
        "show_leave": strip.show_leave,
        "first": strip.days[0].day.isoformat(),
        "last": strip.days[-1].day.isoformat(),
        "cells": [
            {
                "day": cell.day.day.isoformat(),
                "num": cell.day.day.day,
                "weekday": date_format(cell.day.day, "D"),
                "count": cell.count,
                "shade": cell.shade,
                "is_today": cell.day.is_today,
                "holiday": cell.day.holiday,
                "clickable": not (cell.day.off or cell.count is None),
            }
            for cell in cells
        ],
        "today_line": _today_line(strip) if strip.show_leave else "",  # no leave right: no sentence about who is away
    }


def _upcoming_out(found: dict[str, Any]) -> dict[str, object]:
    counts = found["upcoming_counts"]
    checklist = found["checklist_summary"]
    holidays = found["holidays"]
    return {
        "holidays": [{"day": day.isoformat(), "name": name} for day, name in holidays],
        "open_vacancies": found["open_vacancies"],
        "checklist": {"open": checklist[0], "overdue": checklist[1]} if checklist is not None else None,
        "show_birthdays": found["show_birthdays"],
        "birthdays": counts["birthday"] if found["show_birthdays"] else 0,  # without the right the count stays hidden
        "anniversaries": counts["anniversary"],
        "new_hires": found["new_hires_count"],
    }


def _company_out(company: company_stats.Company | None) -> dict[str, int] | None:
    if company is None:
        return None
    return {"hires_month": company.hires_month, "leavers_month": company.leavers_month}


@today_router.get("", auth=django_auth, response=TodayOut)
def today(request: HttpRequest) -> dict[str, object]:
    assert isinstance(request.user, User)
    user = request.user
    day: date = timezone.localdate()
    found: dict[str, Any] = today_facts(user, day)
    strip: facts.AwayStrip = found["away_strip"]
    return {
        "today": found["today"].isoformat(),
        "headcount": found["headcount"],
        "away_today": len(found["away"]),
        "has_own_page": found["has_own_page"],
        "shortcuts": {
            "add_employee": found["can_manage"],
            "record_leave": user.has_perm("leave.record_leave"),
            "orders": found["can_manage"],
        },
        "box": box_out(found["box"]),
        "show_views": user.has_perm("reports.view_reports"),
        "strip": _strip_out(strip, found["away_cells"]),
        "upcoming": _upcoming_out(found),
        "company": _company_out(found["company"]),
    }


class AwayPersonOut(Schema):
    id: int
    full_name: str
    label: str  # the leave type's name
    until: str  # YYYY-MM-DD


class AwayOut(Schema):
    day: str  # YYYY-MM-DD
    people: list[AwayPersonOut]


class UpcomingItemOut(Schema):
    id: int
    full_name: str
    kind: str  # "birthday" | "anniversary"
    on: str  # YYYY-MM-DD
    years: int | None  # anniversaries only


class UpcomingListOut(Schema):
    kind: str
    items: list[UpcomingItemOut]


class HireOut(Schema):
    id: int
    full_name: str
    hired: str  # YYYY-MM-DD


class TodayViewOut(Schema):
    name: str
    report: str
    count: int
    url: str


@today_router.get("/away", auth=django_auth, response=AwayOut)
def today_away(request: HttpRequest, response: HttpResponse, day: str = "") -> dict[str, object]:
    """The names of people away on one day of the Today strip (`?day=YYYY-MM-DD`, inside the 14-day window)."""
    user, today = _user(request), timezone.localdate()
    try:
        day_date = date.fromisoformat(day)
    except ValueError:
        raise HttpError(404, "Хуудас олдсонгүй") from None
    if not today <= day_date < today + timedelta(days=facts.WINDOW_DAYS):
        raise HttpError(404, "Хуудас олдсонгүй")
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    facts.prime_exts(rows)
    response["Cache-Control"] = "no-store"
    return {
        "day": day_date.isoformat(),
        "people": [
            {
                "id": a.row.employee.pk,
                "full_name": a.row.employee.full_name,
                "label": a.label,
                "until": a.until.isoformat(),
            }
            for a in facts.away_on_day(user, rows, day_date)
        ],
    }


@today_router.get("/upcoming", auth=django_auth, response=UpcomingListOut)
def today_upcoming(request: HttpRequest, response: HttpResponse, kind: str = "") -> dict[str, object]:
    """The birthdays or the work anniversaries in the next 30 days (`?kind=birthday|anniversary`)."""
    user, today = _user(request), timezone.localdate()
    if kind not in ("birthday", "anniversary"):
        raise HttpError(404, "Хуудас олдсонгүй")
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    facts.prime_exts(rows)  # the personal-data check reads each person's HR row (own record)
    found = [u for u in facts.upcoming(user, rows, today) if u.kind == kind]
    response["Cache-Control"] = "no-store"
    return {
        "kind": kind,
        "items": [
            {
                "id": u.row.employee.pk,
                "full_name": u.row.employee.full_name,
                "kind": u.kind,
                "on": u.on.isoformat(),
                "years": u.years,
            }
            for u in found
        ],
    }


@today_router.get("/hires", auth=django_auth, response=list[HireOut])
def today_hires(request: HttpRequest, response: HttpResponse) -> list[dict[str, object]]:
    """The names of people who joined in the last 30 days (the hires line of «Ойрын 30 хоног»)."""
    user, today = _user(request), timezone.localdate()
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    facts.prime_exts(rows)
    response["Cache-Control"] = "no-store"
    return [
        {
            "id": r.employee.pk,
            "full_name": r.employee.full_name,
            "hired": r.employee.first_hire_date.isoformat(),
        }
        for r in facts.new_hires(rows, today)
    ]


@today_router.get("/views", auth=django_auth, response=list[TodayViewOut])
def today_views(request: HttpRequest, response: HttpResponse) -> list[dict[str, object]]:
    """The report setups that say what is coming up, with their counts (empty without reports.view_reports)."""
    from reports.today_tiles import tiles  # loaded per call: it pulls in the report registry, which imports employees

    response["Cache-Control"] = "no-store"
    return [asdict(t) for t in tiles(_user(request))]
