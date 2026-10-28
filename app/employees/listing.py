from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import QuerySet

from employees.models import ContractType, Employee, JobRecord, JobStatus, SalaryRecord
from employees.services.history import salary_on

# MACS emptype values, firebird-rules-audit.md. Every other value counts as working.
# NEVER_WORKED: never worked here (2 external reserve, 4 applicant).
# LEGACY_NOT_WORKING: no longer works here or never did (adds 3 dismissed).
NEVER_WORKED = {2, 4}
LEGACY_NOT_WORKING = NEVER_WORKED | {3}
STATE_LABELS: dict[str, str] = {
    "active": "Ажиллаж байгаа",
    "upcoming": "Ажилд орох",
    "long_leave": "Урт чөлөөтэй",
    "left": "Гарсан",
}


@dataclass
class Row:
    employee: Employee
    job: JobRecord | None
    state: str  # active / long_leave / left / upcoming
    legacy: bool = False  # no HR job history: `job` is read from the MACS row and is not saved


def legacy_job(employee: Employee) -> JobRecord:
    """Unsaved job read from the MACS row, for employees HR has no job history for (QC 1a/1b). Display only:
    never saved, and history/sync never see it."""
    if employee.emptype in LEGACY_NOT_WORKING:
        status = JobStatus.LEFT
    elif employee.taken_leave:
        status = JobStatus.LONG_LEAVE
    else:
        status = JobStatus.ACTIVE
    ids: dict[str, Any] = {"department_id": employee.department_id, "position_id": employee.position_id}  # may be NULL
    return JobRecord(
        employee=employee,
        **ids,
        status=status,
        contract_type=ContractType.FIXED_TERM if employee.emptype == 5 and employee.contract_end else "",
        contract_no=employee.contract_no or "",
        contract_start=employee.contract_start,
        contract_end=employee.contract_end,
    )


def current_salary(employee: Employee, today: date) -> SalaryRecord | None:
    """Salary valid today; for employees with no HR salary history, an unsaved one from MACS `salary` (QC 1c)."""
    salary = salary_on(employee, today)
    if salary is None and not employee.salary_records.exists() and employee.salary:
        return SalaryRecord(employee=employee, base_salary=employee.salary)
    return salary


def _period_order(job: JobRecord) -> tuple[date, bool, date]:
    """The order of the old `order_by("period")`: by start, then by end (no end sorts last)."""
    upper = job.period.upper
    return (job.period.lower, upper is None, upper or date.max)


def row_for(employee: Employee, today: date) -> Row:
    # Read from the records once and sorted here, not with a query per person: employee_rows prefetches them.
    records = list(employee.job_records.all())
    containing = [r for r in records if today in r.period]
    job = min(containing, key=lambda r: r.pk) if containing else None  # the job on `today` (same as job_on)
    if job is not None:
        return Row(employee, job, job.status)
    if not records:
        job = legacy_job(employee)
        return Row(employee, job, job.status, legacy=True)
    first = min(records, key=_period_order)
    if first.period.lower > today:
        return Row(employee, first, "upcoming")
    last = max(records, key=_period_order)
    return Row(employee, last, "left")


def employee_rows(qs: QuerySet[Employee], today: date) -> list[Row]:
    return [row_for(e, today) for e in qs.prefetch_related("job_records__position", "job_records__department")]
