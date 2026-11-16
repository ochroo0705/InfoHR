"""The record side of the report corrections (D-080, phase 4): which job or salary record a report cell corrects, what
it shows, its form, whether it may be corrected now, and the save itself.

The reports app calls these plain functions and never names the job, salary or history models (test T-028). A
correction is the employee page's «Засвар» (history.correct_job / correct_salary): it changes the record in place and
logs «Засвар: <reason>». The rules are the employee page's too: a record whose change is still scheduled or waits for
its signed order is cancelled on the employee page, not corrected here.
"""

from datetime import date
from typing import Any

from accounts.models import User
from django.forms import BaseForm
from django.http import QueryDict
from django.utils import timezone

from employees import access
from employees.forms import JobCorrectionForm, SalaryCorrectionForm
from employees.models import CompanySettings, Employee, Event, JobRecord, SalaryRecord
from employees.services import history
from employees.services.display import shown
from employees.templatetags.hr import mnt

HistoryError = history.HistoryError
DB_REFUSED = "Мэдээллийг хадгалж чадсангүй: утга хэт урт эсвэл зөвшөөрөгдөөгүй байна."
NOT_CURRENT = "Зөвхөн одоогийн ажлын мөрийг эндээс засна. Өмнөх мөрийг ажилтны хуудаснаас засна уу."
SCHEDULED = "Энэ өөрчлөлт хүлээгдэж байна (тушаал гараагүй). Ажилтны хуудаснаас үзнэ үү."

Record = JobRecord | SalaryRecord


def setting_on() -> bool:
    """The company setting «Тайлангаас засвар хийх»."""
    return CompanySettings.get().report_corrections


def may_correct(user: User, employee: Employee, key: str) -> bool:
    """The right to correct this key of this employee: the employee is visible, and manage employees (a job field) or
    manage salary (salary). The company setting is checked by the caller."""
    if not access.visible_employees(user).filter(pk=employee.pk).exists():
        return False
    if key == "salary":
        return access.can_manage_salary(user)
    return access.can_manage(user)


def _scheduled(event: Event | None, today: date) -> bool:
    """A change that can still be cancelled: scheduled, or waiting for its signed order (any date). The same check as
    the employee page's correction (employees.views._is_scheduled)."""
    return event is not None and event.status(today) in ("scheduled", "awaiting_signature")


def lookup(employee: Employee, key: str, record_id: int | None) -> tuple[Record | None, str]:
    """The record a cell corrects and why it cannot be corrected now ("" when it can).

    A salary cell corrects today's salary record. A job cell corrects the job record `record_id` of this employee, and
    only when it is the record in force today. Returns (None, "") when there is no such record. Otherwise returns the
    record and the message to show instead of the editor's inputs."""
    today = timezone.localdate()
    if key == "salary":
        salary = history.salary_on(employee, today)
        if salary is None:
            return None, ""
        return salary, SCHEDULED if _scheduled(salary.event, today) else ""
    job = JobRecord.objects.select_related("event").filter(pk=record_id, employee_id=employee.pk).first()
    if job is None:
        return None, ""
    current = history.job_on(employee, today)
    if current is None or current.pk != job.pk:
        return job, NOT_CURRENT
    return job, SCHEDULED if _scheduled(job.event, today) else ""


def record_for(employee: Employee, key: str, record_id: int | None) -> Record | None:
    """The record a cell may correct now: None when there is none, or when it is not correctable (not the record in
    force today, or its change is scheduled or awaits its signed order)."""
    record, blocked = lookup(employee, key, record_id)
    return None if blocked else record


def shown_text(record: Record, key: str) -> str:
    """The text the cell shows for this record, as the report draws it (a salary with the ₮ sign)."""
    if key == "salary":
        assert isinstance(record, SalaryRecord)  # noqa: S101
        return "" if record.base_salary is None else mnt(record.base_salary)
    assert isinstance(record, JobRecord)  # noqa: S101
    value = getattr(record, key)
    if key in ("department", "position"):  # the staff list shows the name
        return "" if value is None else str(value.name)
    return shown(JobRecord._meta.get_field(key), value)


def field_of(key: str) -> str:
    """The form field a cell key edits: the salary form calls its one field «amount»."""
    return "amount" if key == "salary" else key


def form_for(user: User, record: Record, key: str, data: QueryDict | None = None) -> BaseForm:
    """The employee page's form for this cell, bound to `data` when given (the editor's own widget)."""
    if key == "salary":
        assert isinstance(record, SalaryRecord)  # noqa: S101
        return SalaryCorrectionForm(data, initial={"amount": record.base_salary})
    assert isinstance(record, JobRecord)  # noqa: S101
    return JobCorrectionForm(data, instance=record, user=user)


def apply(user: User, record: Record, key: str, value: Any, reason: str) -> Record:
    """Save one correction through the history service (it logs «Засвар: <reason>»).

    Raises HistoryError when the service refuses it.
    """
    if key == "salary":
        assert isinstance(record, SalaryRecord)  # noqa: S101
        return history.correct_salary(record, amount=value, reason=reason, by=user)
    assert isinstance(record, JobRecord)  # noqa: S101
    return history.correct_job(record, changes={key: value}, reason=reason, by=user)
