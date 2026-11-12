"""The reports that are built. A catalogue entry with no registered report is shown greyed as «удахгүй»."""

from dataclasses import replace

from accounts import modules
from accounts.models import User
from django.contrib.auth.models import AnonymousUser

from reports import (
    absences,
    annual_leave,
    children,
    compare,
    contacts,
    data_gaps,
    development_lists,
    engineers,
    gifts,
    household_income,
    leave_balance,
    leave_requests,
    loans,
    movements,
    orders,
    performance,
    personal_lists,
    safety,
    staff_list,
    trends,
)
from reports.types import Report

ALL_LAYOUTS = ("board", "calendar", "timeline", "cards", "chart", "pivot")


def _with_tools(report: Report) -> Report:
    """Every report keeps saved views; a row report that declares no layouts of its own offers them all
    (offered_layouts still hides a layout with no suitable column). Statistic reports (no count line) stay tables."""
    layouts = report.layouts or (ALL_LAYOUTS if report.shows_count else ())
    return replace(report, saved_views=True, layouts=layouts)


REPORTS: dict[str, Report] = {
    report.key: _with_tools(report)
    for report in (
        staff_list.REPORT,
        children.REPORT,
        contacts.REPORT,
        engineers.REPORT,
        household_income.REPORT,
        annual_leave.REPORT,
        leave_balance.REPORT,
        leave_requests.REPORT,
        absences.ABSENCES,
        absences.AWAY,
        absences.TOTALS,
        movements.MOVEMENTS,
        movements.HISTORY,
        movements.LEAVERS,
        orders.REPORT,
        personal_lists.DISCIPLINE,
        personal_lists.AWARDS,
        development_lists.TRAINING,
        development_lists.HEALTH_CHECKS,
        development_lists.SKILL_TASKS,
        development_lists.COMPLAINTS,
        gifts.GIVEN,
        gifts.DUE,
        loans.LOANS,
        performance.REPORT,
        performance.SUMMARY,
        safety.ACCIDENTS,
        safety.POISONING,
        trends.REPORT,
        compare.REPORT,
        data_gaps.REPORT,
    )
}


def get(key: str) -> Report | None:
    return REPORTS.get(key)


def can_open(user: User | AnonymousUser, report: Report) -> bool:
    if report.module and not modules.enabled(report.module):
        return False
    return user.has_perm("reports.view_reports") and all(user.has_perm(p) for p in report.needs)
