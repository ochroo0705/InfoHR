from dataclasses import dataclass
from datetime import date

from django.db.models import QuerySet

from employees.models import Employee, JobRecord
from employees.services.history import job_on


@dataclass
class Row:
    employee: Employee
    job: JobRecord | None
    state: str  # active / long_leave / left / upcoming


def row_for(employee: Employee, today: date) -> Row:
    job = job_on(employee, today)
    if job is not None:
        return Row(employee, job, job.status)
    first = employee.job_records.order_by("period").first()
    if first is not None and first.period.lower > today:
        return Row(employee, first, "upcoming")
    last = employee.job_records.order_by("-period").first()
    return Row(employee, last, "left")


def employee_rows(qs: QuerySet[Employee], today: date) -> list[Row]:
    return [row_for(e, today) for e in qs.prefetch_related("job_records__position", "job_records__department")]
