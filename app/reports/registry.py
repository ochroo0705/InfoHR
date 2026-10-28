"""The reports that are built. A catalogue entry with no registered report is shown greyed as «удахгүй»."""

from accounts.models import User
from django.contrib.auth.models import AnonymousUser

from reports import (
    absences,
    ages,
    annual_leave,
    children,
    contacts,
    development_lists,
    elders,
    employee_info,
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
    sizes,
    staff_list,
    statistics,
)
from reports.types import Report

REPORTS: dict[str, Report] = {
    report.key: report
    for report in (
        staff_list.REPORT,
        employee_info.REPORT,
        ages.REPORT,
        elders.REPORT,
        children.REPORT,
        contacts.REPORT,
        engineers.REPORT,
        household_income.REPORT,
        sizes.REPORT,
        statistics.REPORT,
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
    )
}


def get(key: str) -> Report | None:
    return REPORTS.get(key)


def can_open(user: User | AnonymousUser, report: Report) -> bool:
    return user.has_perm("reports.view_reports") and all(user.has_perm(p) for p in report.needs)
