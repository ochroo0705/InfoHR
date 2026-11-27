"""The reporting line of an employee: the chain of managers above them on a day (direct manager first, then up).

Request-free and read-only. Uses the same day rules as `employees.scope.team_ids` (a job record is in force on a day
when `history_range.on(day)` matches it), and a loop in the data cannot make the walk run forever."""

from datetime import date, timedelta
from typing import NamedTuple

from employees import history_range
from employees.models import Employee, JobRecord


class Level(NamedTuple):
    """One manager in the chain. `job` is the manager's own job record in force on the day (None when they have none,
    so their title is unknown and the walk stops there). `until` is the last day the lower person stays with this
    manager (see `_relation_until`), None when that relation is open-ended."""

    employee: Employee
    job: JobRecord | None
    until: date | None


def _job_on(employee_id: int, day: date) -> JobRecord | None:
    return (
        JobRecord.objects.select_related("manager", "position", "department")
        .filter(history_range.on(day), employee_id=employee_id)
        .first()
    )


def _relation_until(lower: JobRecord) -> date | None:
    """The last day the lower person's relation to their manager lasts, from their job record `lower` onward.

    Job records split on any change (position, department, contract), so a record's end does not by itself end the
    relation. Walk forward through the contiguous records (each starts on the previous one's end) that keep the same
    manager. The result is the last day of the last such record, the day before the first end that is not followed by
    a same-manager record. None when the relation is open-ended."""
    record = lower
    while record.end_date is not None:
        following = JobRecord.objects.filter(employee_id=record.employee_id, start_date=record.end_date).first()
        if following is None or following.manager_id != lower.manager_id:
            return record.end_date - timedelta(days=1)
        record = following
    return None


def reporting_line(employee_id: int, day: date) -> list[Level]:
    """The managers above `employee_id` on `day`, direct manager first. Empty when the employee has no job in force
    on `day` or no manager. The walk stops at a manager without a job in force, and before a manager already seen."""
    lower = _job_on(employee_id, day)
    if lower is None:
        return []
    levels: list[Level] = []
    visited = {employee_id}
    until = _relation_until(lower)
    manager = lower.manager
    while manager is not None and manager.pk not in visited:
        visited.add(manager.pk)
        job = _job_on(manager.pk, day)
        levels.append(Level(employee=manager, job=job, until=until))
        if job is None:
            break
        until = _relation_until(job)
        manager = job.manager
    return levels
