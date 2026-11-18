"""The employee page's save (the header, work and salary fields), without the HTTP part.

employees.views.employee_save keeps the request side: the redirect, the htmx refresh and the 400 status. save_page does
the rest: the rights, the form completed from the stored values, the stale check (employees.stale) and the write.
page_form_state gives the unbound forms the page shows (the rule detail_context uses).
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from accounts.models import User
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied
from django.db import DataError, IntegrityError, transaction
from django.forms import BaseForm
from django.http import Http404, QueryDict
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.datastructures import MultiValueDict

from employees import access, sections, stale
from employees.forms import (
    BIRTH_FIELDS,
    FORMS,
    EmployeeForm,
    JobCorrectionForm,
    PersonalRowForm,
    SalaryCorrectionForm,
    SalaryInsuranceForm,
    SetSalaryForm,
)
from employees.models import PERSONAL_FIELDS, Employee, Event, JobRecord, SalaryRecord
from employees.sections import _as_posted, _posted_from_loaded
from employees.services import detail_page, history, logins, personal_rows, records, setup
from employees.services import personal_writes as pw

logger = logging.getLogger(__name__)

DB_REFUSED = "Мэдээллийг хадгалж чадсангүй: утга хэт урт эсвэл зөвшөөрөгдөөгүй байна."
TABS = ("work", "personal", "salary")
WORK_TAB_FIELDS = frozenset(
    {
        "first_hire_date",
        "work_conditions",
        "work_schedule",
        "probation_end",
        "job_type",
        "job_figure",
        "second_position",
        "office",
        "section",
        "branch",
        "sector_years",
    }
)
SALARY_PREFIX = "si-"  # the salary form's HTML names are prefixed; its errors and conflicts are keyed the same way
ADDRESS_PRESET = ("city", "district", "street")  # the address form's fields a GET may preset (views._get_override)


@dataclass
class SaveResult:
    ok: bool
    field_errors: dict[str, list[str]]  # by HTML name (salary fields carry the «si-» prefix); posted fields only
    form_errors: list[str]  # the form-wide lines, incl. errors of fields the post did not include (with the label)
    conflicts: dict[str, str]  # HTML name -> the value MACS stored meanwhile, as the user reads it
    loaded: str  # the hidden `loaded` value of a fresh form on the stored employee (for a re-render)
    tab: str  # on success the posted tab; on failure the tab that shows the first error
    form: EmployeeForm | None
    si_form: SalaryInsuranceForm | None


def employee_form(user: User, employee: Employee, data: Any = None, files: Any = None) -> EmployeeForm:
    form = EmployeeForm(data, files, employee=employee, user=user)
    if not access.can_view_personal(user, employee):  # those inputs are not on the page
        for name in PERSONAL_FIELDS:
            form.fields.pop(name, None)
    return form


def salary_form(employee: Employee, data: Any = None) -> SalaryInsuranceForm:
    return SalaryInsuranceForm(data, prefix="si", employee=employee)


def page_form_state(user: User, employee: Employee) -> tuple[EmployeeForm | None, SalaryInsuranceForm | None]:
    """The unbound forms the employee page shows: None for a form the user has no right to."""
    form = employee_form(user, employee) if access.can_manage(user) else None
    si_form = salary_form(employee) if access.can_manage_salary(user) else None
    return form, si_form


def _error_tab(form: EmployeeForm | None, si_form: SalaryInsuranceForm | None, posted: str) -> str:
    """The tab to open after a failed save, so the first error is not hidden behind another tab."""
    if si_form is not None and si_form.errors:
        return "salary"
    errors = set(form.errors) if form is not None else set()
    if errors & (PERSONAL_FIELDS | set(BIRTH_FIELDS)):
        return "personal"
    if errors & WORK_TAB_FIELDS:
        return "work"
    return posted if posted in TABS else "work"


def _surface_hidden_errors(form: BaseForm, posted: QueryDict, prefix: str = "") -> None:
    """A field the page did not post (completed from the stored value) has no box to show its error: copy it to the
    form-wide error line above the form, with the field's label."""
    for name in list(form.errors):
        if name == NON_FIELD_ERRORS or f"{prefix}{name}" in posted:
            continue
        label = form.fields[name].label if name in form.fields else name
        for message in form.errors[name]:
            form.add_error(None, f"{label}: {message}")


def _field_errors(form: BaseForm | None, posted: QueryDict, prefix: str) -> dict[str, list[str]]:
    if form is None:
        return {}
    return {
        f"{prefix}{name}": [str(message) for message in messages]
        for name, messages in form.errors.items()
        if name != NON_FIELD_ERRORS and f"{prefix}{name}" in posted
    }


def _loaded_now(user: User, employee: Employee) -> str:
    """The `loaded` snapshot of a fresh form on the stored employee (after a write or a refused one)."""
    if not access.can_manage(user):
        return ""
    fresh = Employee.objects.get(pk=employee.pk)
    return stale.snapshot(employee_form(user, fresh))


def save_section(user: User, employee: Employee, section: str, post: QueryDict) -> SaveResult:
    """Save one personal-tab section (employees.sections.SECTIONS). Only the section's own fields are validated as
    required and written; a clash or a refused write writes nothing. The personal-tab view and the API both call it."""
    if section not in sections.SECTIONS:
        raise Http404
    if not (access.can_manage(user) and access.can_view_personal(user, employee)):
        raise PermissionDenied
    names = sections.SECTIONS[section]
    # Fresh instance for the form, so update_employee can diff against the unmodified `employee`; the stored row
    # is what a clash is checked against (a value MACS changed meanwhile names the stored value).
    stored = Employee.objects.get(pk=employee.pk)
    form = EmployeeForm(
        sections.section_data(EmployeeForm(employee=stored, user=user), post, names),
        employee=stored,
        user=user,
    )
    sections.only_section_required(form, names)
    if form.is_valid():
        columns, ext = form.values()
        changes = stale.resolve(form, stored, {**columns, **ext})
        if not getattr(form, "conflicts", None):
            try:
                with transaction.atomic():
                    records.update_employee(employee, changes, user)
                    place = form.birth_place()
                    if place is not None:
                        records.set_birth_place(employee, *place, user)
            except (IntegrityError, DataError) as exc:
                form.add_error(None, DB_REFUSED)
                logger.warning("employee section write refused: %s", exc)
            else:
                return SaveResult(
                    ok=True,
                    field_errors={},
                    form_errors=[],
                    conflicts={},
                    loaded=_loaded_now(user, employee),
                    tab="personal",
                    form=form,
                    si_form=None,
                )
    return SaveResult(
        ok=False,
        field_errors={
            name: [str(message) for message in messages] for name, messages in form.errors.items() if name in names
        },
        form_errors=sections.outside_errors(form, names),
        conflicts=dict(getattr(form, "conflicts", {})),
        loaded=_loaded_now(user, employee),
        tab="personal",
        form=form,
        si_form=None,
    )


def _salary_loaded(post: QueryDict) -> dict[str, Any] | None:
    """The salary form's `si-loaded` snapshot the page posted, or None when absent or unreadable."""
    raw = post.get(f"{SALARY_PREFIX}{stale.LOADED}")
    if not raw:
        return None
    try:
        found = json.loads(raw)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def complete_salary_post(si_form: SalaryInsuranceForm, post: QueryDict) -> QueryDict:
    """The POST of the salary form when the client sends only the fields it changed (the React page).

    A field not posted takes the value the page showed (`si-loaded`), so the change check reads it as "left as
    shown" and nothing is blanked. Without `si-loaded` the stored value is used. Django's own page posts every
    salary field, so its view does not call this.
    """
    data = post.copy()
    loaded = _salary_loaded(post)
    for name, field in si_form.fields.items():
        key = f"{SALARY_PREFIX}{name}"
        if key in data:
            continue
        if loaded is not None and name in loaded:
            data[key] = _posted_from_loaded(loaded[name])
        else:
            data[key] = _as_posted(si_form.get_initial_for_field(field, name))
    return data


def save_page(
    user: User,
    employee: Employee,
    post: QueryDict,
    files: MultiValueDict[str, Any],
    *,
    complete_salary: bool = False,
) -> SaveResult:
    """Save what this user may change on the employee page. Nothing is written when a field clashes or is invalid.

    `complete_salary` is for the React API, which posts only the changed salary fields (see complete_salary_post).
    """
    can_manage, can_salary = access.can_manage(user), access.can_manage_salary(user)
    if not (can_manage or can_salary):
        raise PermissionDenied
    # The stored row as it is now: the forms and the stale check read it, so a clash names the value MACS holds.
    stored = Employee.objects.get(pk=employee.pk)
    # Fresh instance for the form so update_employee can diff against the unmodified `employee`.
    form = None
    if can_manage:  # the Ажил tab posts no personal fields: they are completed from the stored values
        posted = sections.complete_post(EmployeeForm(employee=stored, user=user), post)
        form = employee_form(user, stored, posted, files)
    si_form = None
    si_post = post
    if can_salary:  # without the permission, salary POST data is ignored entirely
        if complete_salary:
            si_post = complete_salary_post(salary_form(stored), post)
        si_form = salary_form(stored, si_post)
    tab = post.get("tab", "")
    valid = (form is None or form.is_valid()) and (si_form is None or si_form.is_valid())
    changes: dict[str, Any] = {}
    si_changes: dict[str, Any] = {}
    if valid:
        # Only what this user changed is written; a field MACS changed meanwhile is asked about.
        if form is not None:
            columns, ext = form.values()
            changes = stale.resolve(form, stored, {**columns, **ext})
        if si_form is not None:
            si_changes = stale.resolve(si_form, stored, {f: si_form.cleaned_data[f] for f in si_form.changed_data})
        valid = not getattr(form, "conflicts", None) and not getattr(si_form, "conflicts", None)
    written = False
    if valid:
        try:
            with transaction.atomic():
                if form is not None:
                    records.update_employee(employee, changes, user)
                    place = form.birth_place()
                    if place is not None:
                        records.set_birth_place(employee, *place, user)
                    photo = form.photo_bytes()
                    if photo is not None:
                        records.set_photo(employee, photo or None, by=user)
                if si_changes:
                    records.update_salary_insurance(employee, si_changes, user)
        except (IntegrityError, DataError) as exc:
            target = form if form is not None else si_form  # an accountant's save has only the salary form
            if target is not None:
                target.add_error(None, DB_REFUSED)
            logger.warning("employee write refused: %s", exc)
        else:
            written = True
    if written:
        return SaveResult(
            ok=True,
            field_errors={},
            form_errors=[],
            conflicts={},
            loaded=_loaded_now(user, employee),
            tab=tab,
            form=form,
            si_form=si_form,
        )
    if form is not None and form.errors:
        _surface_hidden_errors(form, post)
    if si_form is not None and si_form.errors:
        _surface_hidden_errors(si_form, si_post, prefix=SALARY_PREFIX)
    conflicts = {
        **getattr(form, "conflicts", {}),
        **{f"{SALARY_PREFIX}{name}": text for name, text in getattr(si_form, "conflicts", {}).items()},
    }
    form_errors: list[str] = []
    for part in (form, si_form):
        if part is not None:
            form_errors.extend(str(message) for message in part.non_field_errors())
    return SaveResult(
        ok=False,
        field_errors={**_field_errors(form, post, ""), **_field_errors(si_form, si_post, SALARY_PREFIX)},
        form_errors=form_errors,
        conflicts=conflicts,
        loaded=_loaded_now(user, employee),
        tab=_error_tab(form, si_form, tab),
        form=form,
        si_form=si_form,
    )


class RowSnapshotMissing(Exception):
    """An edit or delete of a personal row posted without the hidden loaded_* values its form showed."""


@dataclass
class RowResult:
    ok: bool
    field_errors: dict[str, list[str]]  # by the form's field name; empty on a form-wide refusal
    form_errors: list[str]  # the form-wide lines: a validation message or a refused write (pw.PersonalConflict)


def _row_form_class(kind: str) -> type[PersonalRowForm]:
    if kind not in FORMS:
        raise Http404
    return FORMS[kind]


def _check_personal_rights(user: User, employee: Employee) -> None:
    if not (access.can_manage(user) and access.can_view_personal(user, employee)):
        raise PermissionDenied


def row_form(kind: str, employee: Employee, key: int | None, overrides: dict[str, str]) -> PersonalRowForm:
    """The unbound form a personal-row pop-up shows: an empty add form (key None) or the edit form of one row, with
    its loaded_* values for the stale check. Only an address honours `overrides` (city, district, street)."""
    form_cls = _row_form_class(kind)
    preset = {name: value for name, value in overrides.items() if kind == "address" and name in ADDRESS_PRESET}
    if key is None:
        return form_cls(adding=True, initial=preset)
    row = personal_rows.row(kind, employee, key)
    if row is None:
        raise Http404
    return form_cls(initial=form_cls.from_snapshot(row.snapshot, row.ext) | preset)


def _bound_row(kind: str, values: dict[str, str], *, adding: bool = False) -> PersonalRowForm:
    return _row_form_class(kind)(values, adding=adding)


def _row_failed(form: BaseForm) -> RowResult:
    return RowResult(
        ok=False,
        field_errors={
            name: [str(message) for message in messages]
            for name, messages in form.errors.items()
            if name != NON_FIELD_ERRORS
        },
        form_errors=[str(message) for message in form.non_field_errors()],
    )


def _require_loaded(form: PersonalRowForm) -> None:
    """Edit and delete compare the row with the values the form showed. A missing, partial or malformed set (snapshot()
    reads each value as JSON and dates and decimals as their types) is refused before anything is written."""
    if form.LOADED and not form.snapshot():
        raise RowSnapshotMissing


def add_row(user: User, employee: Employee, kind: str, values: dict[str, str]) -> RowResult:
    """Validate and insert one personal row. Nothing is written when the form is invalid or the write is refused."""
    _check_personal_rights(user, employee)
    form = _bound_row(kind, values, adding=True)
    if not form.is_valid():
        return _row_failed(form)
    columns, ext = form.values()
    try:
        pw.add(kind, employee, columns, ext, by=user)
    except pw.PersonalConflict as error:
        form.add_error(None, str(error))
        return _row_failed(form)
    return RowResult(ok=True, field_errors={}, form_errors=[])


def edit_row(user: User, employee: Employee, kind: str, key: int, values: dict[str, str]) -> RowResult:
    """Change one personal row if it still matches the loaded values posted with the form (else a form error)."""
    _check_personal_rights(user, employee)
    form = _bound_row(kind, values)  # Http404 for an unknown list; a row another user removed is a stale-check refusal
    _require_loaded(form)
    if not form.is_valid():
        return _row_failed(form)
    columns, ext = form.values()
    try:
        pw.update(kind, employee, key, form.snapshot(), columns, ext, by=user)
    except pw.PersonalConflict as error:
        form.add_error(None, str(error))
        return _row_failed(form)
    return RowResult(ok=True, field_errors={}, form_errors=[])


def delete_row(user: User, employee: Employee, kind: str, key: int, values: dict[str, str]) -> RowResult:
    """Delete one personal row if it still matches the loaded values posted with the form."""
    _check_personal_rights(user, employee)
    form = _bound_row(kind, values)  # Http404 for an unknown list; a row another user removed is a stale-check refusal
    _require_loaded(form)
    try:
        pw.delete(kind, employee, key, form.snapshot(), by=user)
    except pw.PersonalConflict as error:
        return RowResult(ok=False, field_errors={}, form_errors=[str(error)])
    return RowResult(ok=True, field_errors={}, form_errors=[])


def add_note(user: User, employee: Employee, text: str) -> None:
    """A manager's note in the employee's activity log. Blank text after the strip writes nothing (as the pop-up)."""
    if not access.can_manage(user):
        raise PermissionDenied
    if text.strip():
        records.add_note(employee, text=text, by=user)


def toggle_setup(user: User, employee: Employee, key: str) -> None:
    """Tick or untick one setup item, only while the employee's checklist is still open. A system item raises
    ValueError (the caller answers 400)."""
    if not (access.can_manage(user) and detail_page.needs_setup(employee)):
        raise PermissionDenied
    setup.toggle(employee, key, by=user)


def create_login(user: User, employee: Employee, username: str) -> tuple[str, str]:
    """Create the employee's login with a temporary password. Returns (username, password); the password is shown
    once and never logged. A second login for the same employee, or a taken name, raises ValueError."""
    if not access.can_manage(user):
        raise PermissionDenied
    login, password = logins.create_login(employee, username, by=user)
    return login.username, password


CORRECTION_TITLES = {
    "set-salary": "Цалин тогтоох",
    "correct-salary": "Цалин засварлах",
    "correct-job": "Ажлын түүх засварлах",
}  # the pop-up titles of the Django views (views.set_salary, correct_salary, correct_job)


def _check_correction_rights(user: User, which: str) -> None:
    """The salary corrections need the salary right, the job correction the manage right (403 otherwise)."""
    allowed = access.can_manage(user) if which == "correct-job" else access.can_manage_salary(user)
    if not allowed:
        raise PermissionDenied


def _require_not_scheduled(event: Event | None) -> None:
    """A change that can still be cancelled is cancelled, not corrected (the Django views answer 403)."""
    if detail_page._is_scheduled(event, timezone.localdate()):
        raise PermissionDenied


def _correction(
    user: User, employee: Employee, which: str, record_id: int | None, data: Any
) -> tuple[BaseForm, SalaryRecord | JobRecord | None]:
    """The form of one correction and the record it changes (None for a set). `data` binds the form on a save and is
    None on a GET. Rights first, then the record (404 when it is not this employee's), then the scheduled check (403),
    as the Django views do."""
    if which not in CORRECTION_TITLES:
        raise Http404
    _check_correction_rights(user, which)
    if which == "set-salary":
        if employee.salary_records.exists():  # later changes go through corrections
            raise PermissionDenied
        set_form = SetSalaryForm(data, initial={"effective": employee.first_hire_date})
        return set_form, None
    if record_id is None:
        raise Http404
    if which == "correct-salary":
        salary = get_object_or_404(employee.salary_records.select_related("event"), pk=record_id)
        _require_not_scheduled(salary.event)
        salary_form = SalaryCorrectionForm(data, initial={"amount": salary.base_salary})
        return salary_form, salary
    record = get_object_or_404(employee.job_records.select_related("event"), pk=record_id)
    _require_not_scheduled(record.event)
    job_form = JobCorrectionForm(data, instance=JobRecord.objects.get(pk=record.pk), user=user)
    return job_form, record


def correction_form(user: User, employee: Employee, which: str, record_id: int | None) -> BaseForm:
    """The unbound pop-up form of a salary set, a salary correction or a job correction (see _correction)."""
    form, _ = _correction(user, employee, which, record_id, None)
    return form


def submit_correction(
    user: User, employee: Employee, which: str, record_id: int | None, values: dict[str, str]
) -> RowResult:
    """Save a salary set, a salary correction or a job correction. A blank or invalid field, or a refused write
    (history.HistoryError), answers ok false with the messages; nothing is written then."""
    form, record = _correction(user, employee, which, record_id, values)
    if not form.is_valid():
        return _row_failed(form)
    try:
        if isinstance(record, SalaryRecord):
            history.correct_salary(
                record, amount=form.cleaned_data["amount"], reason=form.cleaned_data["reason"], by=user
            )
        elif isinstance(record, JobRecord):
            changes = {field: form.cleaned_data[field] for field in JobRecord.JOB_FIELDS}
            history.correct_job(record, changes=changes, reason=form.cleaned_data["reason"], by=user)
        else:
            history.change_salary(
                employee,
                effective=form.cleaned_data["effective"],
                amount=form.cleaned_data["amount"],
                change_type="hire",
                note="",
                by=user,
                first_only=True,
            )
    except history.HistoryError as error:
        form.add_error(None, str(error))
        return _row_failed(form)
    return RowResult(ok=True, field_errors={}, form_errors=[])
