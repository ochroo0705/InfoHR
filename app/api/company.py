"""GET /api/v1/company: the company figures page (`employees/company.html` and `_company.html`), as display strings.

The figures come from employees.company_stats.company (the same numbers the Django page and the Today strip use).
The chart geometry comes from the same template-tag functions the Django page calls (employees.templatetags.charts),
so the polylines and bars match the page exactly. This module only presents them.
"""

from typing import Any

from accounts.models import User
from django.http import HttpRequest
from django.utils import timezone
from django.utils.formats import localize
from employees import access, company_stats
from employees.listing import employee_rows
from employees.templatetags.charts import bar_chart, line_chart
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

company_router = Router(tags=["company"])

_FORBIDDEN = "Хандах эрх байхгүй."
_TITLE = "Компанийн байдал"
_SCOPE_LABEL = "Таны харах ажилтнууд"
_HISTORY_NOTE = "MACS-ийн ажилтны түүх бүрэн биш тул график ойролцоо"
_TURNOVER_NOTE = "Сарын эргэлт = гарсан ÷ сарын дундаж ажилтны тоо"
_HEADCOUNT_TITLE = "Ажилтны тоо, 12 сар"
_TURNOVER_TITLE = "Сарын эргэлт"
_DEPARTMENTS_TITLE = "Хэлтсээр"
_TENURE_TITLE = "Ажилласан хугацаа"


class CompanyPageDotOut(Schema):
    cx: str  # the last point's dot, as SVG numbers
    cy: str


class CompanyPageLineOut(Schema):
    title: str
    head: str  # the heading's figure: the last month's value with its unit, "" without one
    label: str  # the chart's aria label: «title: first → last», or the title alone
    polylines: list[str]  # one SVG `points` string per unbroken run
    last_dot: CompanyPageDotOut | None
    view_box: str  # the SVG viewBox
    first_label: str  # YYYY-MM
    last_label: str  # YYYY-MM
    no_data: bool
    no_data_text: str  # «Мэдээлэл алга» when no_data


class CompanyPageBarOut(Schema):
    label: str
    value: str  # the count, as the page prints it
    width: str  # the bar's fill, e.g. «42%»


class CompanyPageBarsOut(Schema):
    title: str
    summary: str  # the chart's aria label
    no_data: bool
    no_data_text: str
    bars: list[CompanyPageBarOut]


class CompanyPageOut(Schema):
    title: str  # «Компанийн байдал»
    today: str  # YYYY-MM-DD
    partial_scope: bool
    scope_label: str  # «Таны харах ажилтнууд» when partial_scope, "" otherwise
    partial_history: bool
    history_note: str  # shown when partial_history, "" otherwise
    hires_text: str  # «Энэ сард орсон N»
    leavers_text: str  # «Гарсан N»
    headcount: CompanyPageLineOut
    turnover: CompanyPageLineOut
    turnover_note: str
    departments: CompanyPageBarsOut
    tenure: CompanyPageBarsOut


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _line_out(title: str, points: list[Any], unit: str) -> dict[str, Any]:
    chart = line_chart(points, unit, title)
    last = points[-1].value if points else None
    dot = chart["last_dot"]
    return {
        "title": title,
        "head": "" if last is None else f"{localize(last)}{unit}",
        "label": chart["label"],
        "polylines": chart["polylines"],
        "last_dot": {"cx": f"{dot[0]:g}", "cy": f"{dot[1]:g}"} if dot else None,
        "view_box": f"-4 -4 {chart['width'] + 8} {chart['height'] + 8}",
        "first_label": chart["first_label"],
        "last_label": chart["last_label"],
        "no_data": chart["no_data"],
        "no_data_text": chart["no_data_text"],
    }


def _bars_out(title: str, bars: list[Any]) -> dict[str, Any]:
    chart = bar_chart(bars, title)
    return {
        "title": title,
        "summary": chart["summary"],
        "no_data": chart["no_data"],
        "no_data_text": chart["no_data_text"],
        "bars": [{"label": b.label, "value": localize(b.value), "width": f"{localize(b.pct)}%"} for b in bars],
    }


@company_router.get("", auth=django_auth, response=CompanyPageOut)
def company(request: HttpRequest) -> dict[str, Any]:
    """The company figures page (403 without the employee-list right, as company_page)."""
    user, today = _user(request), timezone.localdate()
    if not user.has_perm("macs.view_employees"):
        raise HttpError(403, _FORBIDDEN)
    rows = employee_rows(access.visible_employees(user).filter(ext__isnull=False), today)
    found = company_stats.company(user, rows, today)
    if found is None:
        raise HttpError(403, _FORBIDDEN)
    return {
        "title": _TITLE,
        "today": today.isoformat(),
        "partial_scope": found.partial_scope,
        "scope_label": _SCOPE_LABEL if found.partial_scope else "",
        "partial_history": found.partial_history,
        "history_note": _HISTORY_NOTE if found.partial_history else "",
        "hires_text": f"Энэ сард орсон {localize(found.hires_month)}",
        "leavers_text": f"Гарсан {localize(found.leavers_month)}",
        "headcount": _line_out(_HEADCOUNT_TITLE, found.headcount, ""),
        "turnover": _line_out(_TURNOVER_TITLE, found.turnover, "%"),
        "turnover_note": _TURNOVER_NOTE,
        "departments": _bars_out(_DEPARTMENTS_TITLE, found.departments),
        "tenure": _bars_out(_TENURE_TITLE, found.tenure),
    }
