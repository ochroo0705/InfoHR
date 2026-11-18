"""The hire page (`/employees/new/`): its forms, gating and the hire itself, without the HTTP part.

build makes the six forms, resolves the recruitment candidate and the submitted self-form HR hires from, and refuses a
POST that names one of them and can no longer be used: the refusal message goes on the person form and the page comes
back with status 400. submit runs the hire in one transaction. The caller keeps the request and the session: it sets
the one-time login and the order warning from the outcome.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal

from accounts.models import User
from django.core.exceptions import PermissionDenied
from django.db import DataError, IntegrityError, transaction
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict

from employees import access
from employees.forms import (
    BIRTH_FIELDS,
    EmployeeForm,
    HireAddressForm,
    HireContactForm,
    HireExtrasForm,
    HireJobForm,
    HirePersonForm,
    OrderFieldsForm,
    SalaryInsuranceForm,
)
from employees.images import photo_bytes as decode_stored_photo
from employees.models import (
    EXT_FIELDS,
    ContractType,
    Employee,
    HrOrder,
    JobRecord,
    OrderType,
    SelfFormInvitation,
    SelfFormStatus,
)
from employees.selfform import review as selfform_review
from employees.selfform.answers import AnswerErrors, rows_for_confirm
from employees.selfform.service import (
    SelfFormError,
    mark_confirmed,
    positive_id,
    reviewable_submission,
    visible_status,
)
from employees.services import history, logins, macs_writes, orders, records, slots
from employees.services import personal_writes as pw
from employees.services.history import HistoryError
from employees.services.orders import OrderError
from employees.services.page_writes import DB_REFUSED

logger = logging.getLogger(__name__)

HIRE_PREFILL_PERSON = ("family_name", "given_name", "private_phone", "email")


def _prefill_hire_forms(values: Mapping[str, str], person: EmployeeForm, job: HireJobForm) -> None:
    """Start a fresh hire form from GET values (the recruitment «Ажилд авах» link); only these named fields, and the
    form still validates everything on POST. A bad date or id is dropped."""
    for name in HIRE_PREFILL_PERSON:
        if values.get(name):
            person.initial[name] = values[name].strip()
    for name in ("position", "department", "branch"):
        if values.get(name, "").isdigit() and values[name].isascii():
            job.initial[name] = int(values[name])
    try:
        job.initial["start"] = date.fromisoformat(values.get("start", ""))
    except ValueError:
        pass


def _convertible_candidate(user: User, raw: str | None) -> Any:
    from recruitment.services import convert  # local: recruitment imports employees

    return convert.convertible(user, raw)


CANDIDATE_GONE = "Энэ ажил хүсэгч аль хэдийн ажилд авагдсан эсвэл хаагдсан байна. Хуудсыг дахин нээнэ үү."


def _visible_candidate(user: User, raw: str | None) -> bool:
    from recruitment.services import convert  # local: recruitment imports employees

    return convert.visible(user, raw) is not None


SUBMISSION_GONE = "Энэ анкет аль хэдийн шийдвэрлэгдсэн эсвэл буцаагдсан байна. Хуудсыг дахин нээнэ үү."
SUBMISSION_ROW_INVALID = (
    "Ажилтны өгсөн боловсрол эсвэл гэр бүлийн нэг мөр одоогийн шаардлагад тохирохгүй байна. "
    "Анкетыг «Буцаах» товчоор ажилтанд буцаана уу."
)
SUBMISSION_PHOTO_INVALID = "Ажилтны илгээсэн зураг эвдэрсэн байна. Анкетыг «Буцаах» товчоор ажилтанд буцаана уу."
SUBMISSION_NOT_SENT = "Энэ анкет ажилтны гарт байгаа, одоохондоо илгээгээгүй байна."


def _review_context(user: User, submission: SelfFormInvitation | None) -> dict[str, Any]:
    """Template context while HR reviews a submitted self-form on the hire page; {} when there is none."""
    if submission is None:
        return {}
    return {
        "submission_id": submission.pk,
        "review": selfform_review.panel(submission),
        "duplicate": selfform_review.duplicate_for(submission, user),
    }


@dataclass
class HirePage:
    """Everything the hire page shows: the forms, the gating and the self-form review (None when there is none)."""

    person: HirePersonForm
    job: HireJobForm
    extras: HireExtrasForm
    si: SalaryInsuranceForm | None
    address: HireAddressForm
    contact: HireContactForm
    order_form: OrderFieldsForm | None
    allow_salary: bool
    candidate_id: int | None
    submission: SelfFormInvitation | None
    submission_id: int | None
    review: dict[str, Any] | None
    duplicate: dict[str, Any] | None
    refusal_status: int | None  # 400 when build already refused the POST, else None
    order_required: bool


def build(
    user: User, query: Mapping[str, str], data: QueryDict | None, files: MultiValueDict[str, Any] | None
) -> HirePage:
    """The forms and the gating of the hire page (the first half of the old employee_add). `data` None is a GET: the
    forms are prefilled from `query` and from the submission. With `data` the forms are bound, and a candidate or a
    self-form that can no longer be used is refused on the person form."""
    if not access.can_manage(user):
        raise PermissionDenied
    posting = data is not None
    person = HirePersonForm(data, files if posting else None)
    job = HireJobForm(data, user=user)
    # Convert from recruitment: the candidate this hire may link to (a bad or foreign value is ignored silently).
    posted: Mapping[str, str] = data if data is not None else query
    candidate = _convertible_candidate(user, posted.get("candidate"))
    cid = candidate.pk if candidate is not None else None
    # A candidate this user sees but can no longer convert must not be dropped silently on POST: that would hire the
    # person twice. Only a missing, bad or foreign value is ignored.
    gone = posting and candidate is None and _visible_candidate(user, posted.get("candidate"))
    # A submitted self-form HR is hiring from (a bad, foreign or not-submitted value is ignored silently).
    submission = reviewable_submission(user, posted.get("submission"))
    review_ctx = _review_context(user, submission)
    if not posting:
        _prefill_hire_forms(query, person, job)
    extras = HireExtrasForm(data)
    allow_salary = access.can_manage_salary(user)
    si = SalaryInsuranceForm(data, prefix="si") if allow_salary else None
    address = HireAddressForm(data, prefix="addr")
    contact = HireContactForm(data, prefix="contact")
    if submission is not None and not posting:  # never over posted values
        person.initial.update(selfform_review.person_initial(submission))
        contact.initial.update(selfform_review.contact_initial(submission))
    # An install that keeps hire orders on paper (CompanySettings, D-052) gets no order fields and no order.
    order_required = orders.requires_order(OrderType.HIRED.value)
    order_form = OrderFieldsForm(data, prefix="order", required=True) if order_required else None
    page = HirePage(
        person=person,
        job=job,
        extras=extras,
        si=si,
        address=address,
        contact=contact,
        order_form=order_form,
        allow_salary=allow_salary,
        candidate_id=cid,
        submission=submission,
        submission_id=review_ctx.get("submission_id"),
        review=review_ctx.get("review"),
        duplicate=review_ctx.get("duplicate"),
        refusal_status=None,
        order_required=order_required,
    )
    if gone:
        person.add_error(None, CANDIDATE_GONE)
        return replace(page, candidate_id=None, refusal_status=400)
    # A submission HR can see but cannot review now must not turn into a plain hire. Only a missing, bad or foreign
    # value is ignored. An invitation the employee has not sent yet gets its own message.
    seen = visible_status(user, posted.get("submission")) if posting and submission is None else None
    if seen is not None:
        person.add_error(None, SUBMISSION_NOT_SENT if seen == SelfFormStatus.OPEN else SUBMISSION_GONE)
        # The refused id stays in the form, so a second save is refused here too. No review panel for a refused form.
        return replace(page, submission_id=positive_id(posted.get("submission")), refusal_status=400)
    return page


PHOTO_FIELDS = ("photo", "photo_clear")


def _start_onboarding(employee: Employee, job_values: dict[str, Any], start: date, user: User) -> None:
    """The hire is committed: start its onboarding checklist (tracking only; never fails the hire)."""
    from checklists.services import onboarding  # local: checklists imports employees

    employee_type = job_values.get("employee_type")
    onboarding.start_for_hire(
        employee, start_date=start, employee_type=str(employee_type) if employee_type else None, by=user
    )


class _CandidateGone(Exception):
    """The posted candidate cannot be converted any more; the hire is rolled back."""


def _link_candidate_locked(candidate_id: int, employee: Employee, user: User) -> None:
    """Inside the hire transaction: lock the candidate and link it, or raise `_CandidateGone` (rolls the hire back)."""
    from recruitment.services import convert, pipeline  # local: recruitment imports employees

    locked = convert.lock_convertible(candidate_id)
    if locked is None:
        raise _CandidateGone
    try:
        pipeline.mark_hired(locked, employee, by=user)
    except pipeline.PipelineError as error:
        raise _CandidateGone from error


class _SubmissionGone(Exception):
    """The posted self-form is no longer waiting for review; the hire is rolled back."""


def _confirm_submission_locked(
    submission: SelfFormInvitation,
    employee: Employee,
    rows: list[tuple[str, dict[str, Any], dict[str, Any]]],
    stored_photo: bytes | None,
    has_photo: bool,
    user: User,
) -> None:
    """Inside the hire transaction: confirm the submission (or raise `_SubmissionGone`, which rolls the hire back),
    write its education and family rows, and save the submitted photo when HR uploaded none. `rows` and
    `stored_photo` were read before the lock; a re-submission since then makes them stale, so it is refused."""
    try:
        locked = mark_confirmed(submission.pk, employee, user)
    except SelfFormError as error:  # confirmed or closed by another request first
        raise _SubmissionGone from error
    if locked.submitted_at != submission.submitted_at:  # sent again after this page was read: the rows are stale
        raise _SubmissionGone
    for kind, columns, ext in rows:
        pw.add(kind, employee, columns, ext, by=user)
    if not has_photo and stored_photo:
        macs_writes.save_photo(employee, stored_photo)


def _hire_contract_flag(job_values: dict[str, Any], ext: dict[str, Any]) -> str:
    """The MACS contract flag the hire will get, from the submitted values (as history.hire derives the type)."""
    emptype = job_values.get("emptype")
    if emptype is None:
        emptype = (
            9 if ext.get("probation_end") else 5 if job_values.get("contract_type") == ContractType.FIXED_TERM else 1
        )
    return macs_writes.EMPTYPE_FLAGS.get(emptype, ("", "no", None))[1]


@dataclass
class HireOutcome:
    """What `submit` made of the hire. `employee` is None on a refusal. `login` is set only when this hire created a
    login (its password is shown once; the caller keeps it in the session). `hire_order` is the hire order, None when
    the install keeps hire orders on paper. `status` is 200 for a hire and 400 for any failure (invalid or refused); use
    `reason`. `reason` is None for a hire, "invalid" when a form failed validation (the Django view answers 200 for
    this), and "refused" for every other failure (a refusal by build, the slot, a gone candidate or self-form, a
    conflict, a lock, a database refusal)."""

    employee: Employee | None
    login: dict[str, object] | None
    hire_order: HrOrder | None
    status: int
    reason: Literal["invalid", "refused"] | None = None


def _refused(reason: Literal["invalid", "refused"], status: int = 400) -> HireOutcome:
    return HireOutcome(employee=None, login=None, hire_order=None, status=status, reason=reason)


def submit(user: User, page: HirePage) -> HireOutcome:
    """The hire (the second half of the old employee_add): validate every form, then write the hire in one transaction
    and start its onboarding. A refusal adds its message to the forms on `page`, writes nothing and returns
    `employee=None`. The service never touches the request or the session. `page` must come from a bound `build`."""
    if not access.can_manage(user):
        raise PermissionDenied
    if not page.person.is_bound:
        raise ValueError("submit needs a bound page")
    if page.refusal_status is not None:
        return _refused("refused", page.refusal_status)
    person, job, extras = page.person, page.job, page.extras
    si, address, contact, order_form = page.si, page.address, page.contact, page.order_form
    submission, cid, allow_salary = page.submission, page.candidate_id, page.allow_salary
    if not (
        person.is_valid()
        and (order_form is None or order_form.is_valid())
        and job.is_valid()
        and extras.is_valid()
        and (si is None or si.is_valid())
        and address.is_valid()
        and contact.is_valid()
    ):
        return _refused("invalid")
    confirm_rows: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    stored_photo: bytes | None = None
    if submission is not None:
        try:
            confirm_rows = rows_for_confirm(json.loads(submission.answers or "{}"))
        except (AnswerErrors, ValueError, TypeError, AttributeError):  # stored answers are corrupt or stale
            # nothing is written; HR sends the form back
            person.add_error(None, SUBMISSION_ROW_INVALID)
            return _refused("refused")
        if submission.photo_b64:  # decoded before the transaction: a corrupt photo refuses the confirm
            stored_photo = decode_stored_photo(submission.photo_b64.encode())
            if stored_photo is None:
                person.add_error(None, SUBMISSION_PHOTO_INVALID)
                return _refused("refused")
    salary = extras.cleaned_data["base_salary"] if allow_salary else None
    skip = {*EXT_FIELDS, *PHOTO_FIELDS, *BIRTH_FIELDS}
    columns = {k: person.cleaned_data[k] for k in person.fields if k not in skip}
    columns["branch"] = job.cleaned_data["branch"]  # production branch_ident; None when not set
    ext = {k: person.cleaned_data[k] for k in EXT_FIELDS}
    job_values = {f: job.cleaned_data[f] for f in JobRecord.JOB_FIELDS}
    address_values = address.values()[0] if address.filled() else None
    contact_values = contact.values()[0] if contact.filled() else None
    login: dict[str, object] | None = None
    try:
        with transaction.atomic():
            slots.gate(  # inside the hire transaction: the budget rows stay locked until the hire commits
                position=job_values["position"],
                branch=columns["branch"],
                contract_flag=_hire_contract_flag(job_values, ext),
                on=job.cleaned_data["start"],
                override_reason=job.cleaned_data.get("slot_override", ""),
                by=user,
                employee_label=f"{columns.get('family_name', '')} {columns.get('given_name', '')}".strip(),
            )
            employee = history.hire(
                columns,
                ext,
                start=job.cleaned_data["start"],
                job=job_values,
                salary=salary,
                by=user,
                address=address_values,
                contact=contact_values,
                with_order=page.order_required,
                order_number=order_form.cleaned_data["number"] if order_form else "",
                order_date=order_form.cleaned_data["date"] if order_form else None,
                order_summary=order_form.cleaned_data["summary"] if order_form else "",
                order_issued_by=order_form.cleaned_data["issued_by"] if order_form else "",
            )
            if person.cleaned_data.get("birth_city") is not None:
                records.set_birth_place(
                    employee,
                    person.cleaned_data["birth_city"],
                    person.cleaned_data["birth_district"],
                    person.cleaned_data["birth_place_text"],
                    user,
                )
            photo = person.photo_bytes()
            if photo:
                macs_writes.save_photo(employee, photo)
            if si is not None and si.has_changed():
                # Salary and insurance are production columns; logged as one sensitive entry.
                records.update_salary_insurance(employee, {f: si.cleaned_data[f] for f in si.changed_data}, user)
            if submission is not None:  # confirmed here, so a second post cannot confirm it again
                _confirm_submission_locked(submission, employee, confirm_rows, stored_photo, bool(photo), user)
            if extras.cleaned_data["create_login"]:
                created, password = logins.create_login(employee, extras.cleaned_data["username"], by=user)
                login = {"employee": employee.pk, "username": created.username, "password": password}
            if cid is not None:  # locked and re-checked here, so two posts cannot both hire this candidate
                _link_candidate_locked(cid, employee, user)
    except slots.SlotBlocked as error:  # nothing was written: the gate runs before the hire
        person.add_error(None, error.message)
        return _refused("refused")
    except _CandidateGone:  # the hire is rolled back; nothing was saved
        person.add_error(None, CANDIDATE_GONE)
        page.candidate_id = None
        return _refused("refused")
    except _SubmissionGone:  # the hire is rolled back; the form is no longer waiting for review
        person.add_error(None, SUBMISSION_GONE)
        page.review = None  # no review panel for a refused form; the submission id stays on the page
        page.duplicate = None
        return _refused("refused")
    except pw.PersonalConflict as error:  # the hire is rolled back with the address, contact or self-form rows
        person.add_error(None, str(error))
        return _refused("refused")
    except OrderError as error:  # the hire is rolled back with its order
        if order_form is not None:
            order_form.add_service_errors(error.errors)
        return _refused("refused")
    except HistoryError as error:  # another hire holds the hire lock; the hire is rolled back
        person.add_error(None, str(error))
        return _refused("refused")
    except (IntegrityError, DataError) as exc:
        person.add_error(None, DB_REFUSED)
        logger.warning("employee write refused: %s", exc)
        return _refused("refused")
    _start_onboarding(employee, job_values, job.cleaned_data["start"], user)
    return HireOutcome(
        employee=employee,
        login=login,
        hire_order=HrOrder.objects.filter(employee=employee, is_hire=True).first(),
        status=200,
    )
