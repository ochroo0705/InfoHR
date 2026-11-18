"""The hire page's form description: GET /api/v1/employees/new (the «Ажилтан нэмэх» page, `/employees/new/` in Django).

The server sends the tab and section layout (LAYOUT below, copied from employees/add.html), the description of every
field of every form with the HTML names the hire POST uses, the order block's heading text, and the self-form review
panel and duplicate warning. The rules live in employees.services.hire_page; this module only presents them. A missing
right is 403 (code "forbidden"), no login is 401.

GET /employees/new has the same side effect as the Django page: the first read creates the CompanySettings singleton
if it is missing (orders.requires_order).

The three small helpers the page calls on input, under /employees (hire_router):
GET /employees/check-register?register_no= (the live register check), GET /employees/districts?city= (the district
select follows the city), GET /employees/order-suggest?date= (the «Санал болгох» button).

HR's decision on a self-form, under /selfforms (selfform_router): POST /selfforms/{pk}/send-back (body note) and
POST /selfforms/{pk}/reject (body reason). The rules live in employees.selfform.service.
"""

import json
from datetime import date as calendar_date
from datetime import datetime
from typing import Any

from accounts.models import User
from django.contrib import messages as flash
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied
from django.forms import BaseForm
from django.http import Http404, HttpRequest, QueryDict
from django.urls import reverse
from django.utils import timezone
from django.utils.datastructures import MultiValueDict
from employees import access
from employees.forms import HireAddressForm
from employees.selfform import service as selfform_service
from employees.services import hire_page, orders
from employees.services.form_schema import describe_field, describe_form
from employees.validators import normalize_register_no
from employees.views import ONE_TIME_LOGIN_KEY, _remember_warning
from employees.views_selfform import _NOTE_NEEDED, _REASON_NEEDED
from ninja import File, Form, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.security import django_auth

from api.employee_writes import EmployeeFormChoiceOut, EmployeeFormFieldOut
from api.errors import ApiError

hire_router = Router(tags=["employees"])
selfform_router = Router(tags=["selfforms"])

_FORBIDDEN = "Хандах эрх байхгүй."
_BAD_VALUES = "Хадгалах мэдээлэл буруу байна."  # the same message as the employee save
_NOT_FOUND = "Хуудас олдсонгүй"  # the same message as the employee pages
TITLE = "Ажилтан нэмэх"

# Layout markers inside a section's names: "job.*" is the job form's fields not named elsewhere in the same section (in
# form order); "order.*" is every field of the order block (in form order).
JOB_REST = "job.*"
ORDER_ALL = "order.*"

# (tab key, tab label, sections); a section is (heading, kind, names). Names are "form.field" references, resolved
# to the HTML name (the prefix included) when the form is built. Headings and labels are copied from add.html.
LAYOUT: tuple[tuple[str, str, tuple[tuple[str, str, tuple[str, ...]], ...]], ...] = (
    (
        "basic",
        "Үндсэн",
        (
            (
                "Үндсэн мэдээлэл",
                "fields",
                (
                    "person.family_name",
                    "person.given_name",
                    "person.clan_name",
                    "person.register_no",
                    "person.birth_date",
                    "person.gender",
                    "person.photo",
                    "person.work_phone",
                    "person.private_phone",
                    "person.phone2",
                    "person.email",
                ),
            ),
            (
                "Ажил, гэрээ",
                "fields",
                (
                    "job.start",
                    "person.first_hire_date",
                    JOB_REST,
                    "person.second_position",
                    "person.office",
                    "person.section",
                    "person.job_type",
                    "person.job_figure",
                ),
            ),
            ("Тушаал", "order", (ORDER_ALL,)),
        ),
    ),
    (
        "personal",
        "Хувийн",
        (
            (
                "Хувийн мэдээлэл",
                "fields",
                (
                    "person.birth_city",
                    "person.birth_district",
                    "person.birth_place_text",
                    "person.citizenship",
                    "person.passport_no",
                    "person.marital_status",
                    "person.prior_service_years",
                    "person.prior_service_months",
                    "person.work_conditions",
                    "person.work_schedule",
                    "person.probation_end",
                ),
            ),
            (
                "Бусад мэдээлэл",
                "fields",
                (
                    "person.blood_type",
                    "person.blood_rh",
                    "person.social_origin",
                    "person.military_service",
                    "person.housing_condition",
                    "person.living_standard",
                    "person.car_ownership",
                    "person.clothing_size",
                    "person.shoe_size",
                    "person.elected_position",
                ),
            ),
            ("Хаяг", "fields", ("address.city", "address.district", "address.street")),
            (
                "Яаралтай үед холбогдох",
                "fields",
                ("contact.contact_type", "contact.name", "contact.relative", "contact.value"),
            ),
        ),
    ),
    (
        "salary",
        "Цалин, даатгал",
        (
            (
                "Цалин, даатгал",
                "fields",
                (
                    "extras.base_salary",
                    "si.bank",
                    "si.account_no",
                    "si.social_insurance_no",
                    "si.health_insurance_no",
                    "si.insured_category",
                    "si.taxpayer_no",
                    "si.has_disability",
                ),
            ),
        ),
    ),
    (
        "login",
        "Нэвтрэх эрх",
        (("Нэвтрэх эрх", "fields", ("extras.create_login", "extras.username")),),
    ),
)


class HireSectionOut(Schema):
    heading: str
    kind: str  # "fields" or "order" (the hire order block)
    names: list[str]  # HTML names, in the order the page shows them
    note: str  # the order block's note: the text after the heading's «· » («дугаар заавал» ...); "" for other sections


class HireTabOut(Schema):
    key: str  # basic | personal | salary | login
    label: str
    sections: list[HireSectionOut]


class HireReviewOut(Schema):
    submitted_at: str  # YYYY-MM-DD, as the review panel prints it
    has_photo: bool
    education: list[list[list[str]]]  # rows; each row is [label, value] pairs
    family: list[list[list[str]]]  # rows; each row is [label, value] pairs
    contact: list[list[str]]  # [label, value] pairs
    hr_note: str


class HireDuplicateOut(Schema):
    visible: bool  # HR may see the existing employee; otherwise no name or pk is passed on
    employee_pk: int | None
    employee_name: str


class HireFormOut(Schema):
    title: str
    tabs: list[HireTabOut]
    fields: list[EmployeeFormFieldOut]  # every field of every form, with the HTML names the hire POST uses
    candidate: int | None  # the recruitment candidate this hire links to (posted back on the hire)
    submission: int | None  # the self-form HR is hiring from (posted back on the hire)
    review: HireReviewOut | None
    duplicate: HireDuplicateOut | None


class HireResultOut(Schema):
    ok: bool
    pk: int | None  # the new employee's pk on success
    redirect: str  # on success: the new employee's page, or the list when the user may not see that employee
    field_errors: dict[str, list[str]]  # by HTML name, as the hire POST names them
    form_errors: list[str]  # the non-field messages of every form except the order's, the person's first
    order_errors: list[str]  # the order form's non-field messages, shown inside the order block; never in form_errors
    candidate: int | None  # the candidate a refused form still links to (posted back, so a second save is refused too)
    submission: int | None  # the self-form a refused form still hires from


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


def _utf8_text(text: str) -> str:
    """A posted string the hire can use: a lone surrogate (valid JSON, not UTF-8 text) is a 400, nothing is read."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ApiError(400, [_BAD_VALUES]) from None
    return text


def _hire_values(values_json: str) -> dict[str, str]:
    """The `values` part: a JSON object of HTML name -> string. Anything else is a 400 (nothing is read). Deeply nested
    JSON exhausts the parser's recursion and is refused the same way."""
    try:
        values = json.loads(values_json)
    except (ValueError, RecursionError):
        raise ApiError(400, [_BAD_VALUES]) from None
    if not isinstance(values, dict):
        raise ApiError(400, [_BAD_VALUES])
    result: dict[str, str] = {}
    for name, value in values.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ApiError(400, [_BAD_VALUES])
        result[_utf8_text(name)] = _utf8_text(value)
    return result


def _errors(forms: dict[str, BaseForm | None]) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Every form's messages: field errors by the HTML name, non-field messages in form order (person, job, extras, si,
    address, contact, order). Non-field messages are collected from all of them: JobRecord.clean raises messages that
    add.html never rendered, and dropping them would hide a refusal reason. The exception is the order form's non-field
    messages (its `__all__` service errors too): Django draws them inside the order block, so they go to order_errors
    only and are not repeated in form_errors."""
    field_errors: dict[str, list[str]] = {}
    form_errors: list[str] = []
    order_errors: list[str] = []
    for key, form in forms.items():
        if form is None:
            continue
        for name, messages in form.errors.items():
            if name != NON_FIELD_ERRORS:
                field_errors[form.add_prefix(name)] = [str(message) for message in messages]
            elif key == "order":
                order_errors.extend(str(message) for message in messages)
            else:
                form_errors.extend(str(message) for message in messages)
    return field_errors, form_errors, order_errors


def _forms(page: hire_page.HirePage) -> dict[str, BaseForm | None]:
    return {
        "person": page.person,
        "job": page.job,
        "extras": page.extras,
        "si": page.si,
        "address": page.address,
        "contact": page.contact,
        "order": page.order_form,
    }


def _html_name(forms: dict[str, BaseForm | None], ref: str) -> str:
    """The HTML name of a "form.field" reference. A field the layout names but the forms lack is a bug: raise."""
    key, _, field = ref.partition(".")
    form = forms.get(key)
    if form is None or field not in form.fields:
        raise LookupError(f"hire layout names {ref!r}, which the hire forms do not have")
    return str(form[field].html_name)


def _section_names(forms: dict[str, BaseForm | None], refs: tuple[str, ...]) -> list[str]:
    explicit = {ref for ref in refs if ref not in (JOB_REST, ORDER_ALL)}
    names: list[str] = []
    for ref in refs:
        if ref == JOB_REST:
            job = forms["job"]
            assert job is not None
            names.extend(_html_name(forms, f"job.{field}") for field in job.fields if f"job.{field}" not in explicit)
        elif ref == ORDER_ALL:
            order = forms["order"]
            assert order is not None
            names.extend(_html_name(forms, f"order.{field}") for field in order.fields)
        else:
            names.append(_html_name(forms, ref))
    return names


def _order_note(order_form: BaseForm) -> str:
    """The order block's note: the text after the heading's «· » in employees/_order_fields.html (the React block draws
    the heading word «Тушаал» itself). The number is required on a hire (and on a change that needs an order); a blank
    date means the effective date of the change."""
    number = "дугаар заавал" if order_form.fields["number"].required else "тушаал шаардлагатай өөрчлөлтөд дугаар заавал"
    note = number
    if not order_form.fields["date"].required:
        note += ", огноо хоосон бол өөрчлөлтийн огноо"
    return note


def _tabs(page: hire_page.HirePage) -> list[dict[str, Any]]:
    forms = _forms(page)
    tabs: list[dict[str, Any]] = []
    for key, label, sections in LAYOUT:
        if key == "salary" and page.si is None:  # no salary right: no salary tab
            continue
        shown: list[dict[str, Any]] = []
        for heading, kind, refs in sections:
            if kind == "order" and page.order_form is None:  # hire orders kept on paper: no order block
                continue
            note = _order_note(page.order_form) if kind == "order" and page.order_form is not None else ""
            shown.append({"heading": heading, "kind": kind, "names": _section_names(forms, refs), "note": note})
        tabs.append({"key": key, "label": label, "sections": shown})
    return tabs


def _described_fields(page: hire_page.HirePage) -> list[dict[str, object]]:
    fields: list[dict[str, object]] = []
    fields.extend(describe_form(page.person))
    fields.extend(describe_form(page.job))
    # The base salary exists only with the salary right (the service ignores a posted value without it).
    extras_names = [name for name in page.extras.fields if page.allow_salary or name != "base_salary"]
    fields.extend(describe_form(page.extras, names=extras_names))
    if page.si is not None:
        fields.extend(describe_form(page.si))
    fields.extend(describe_form(page.address))
    fields.extend(describe_form(page.contact))
    if page.order_form is not None:
        fields.extend(describe_form(page.order_form))
    return fields


def _day(value: object) -> str:
    """A submission date as YYYY-MM-DD in the local time zone, the way the review panel's date filter prints it."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date().isoformat()
    return str(value)


def _pairs(rows: list[tuple[str, str]]) -> list[list[str]]:
    return [[label, value] for label, value in rows]


def _review(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "submitted_at": _day(review.get("submitted_at")),
        "has_photo": bool(review.get("has_photo")),
        "education": [_pairs(row) for row in review.get("education", [])],
        "family": [_pairs(row) for row in review.get("family", [])],
        "contact": _pairs(review.get("contact", [])),
        "hr_note": str(review.get("hr_note") or ""),
    }


def _duplicate(duplicate: dict[str, Any]) -> dict[str, Any]:
    employee = duplicate.get("employee")
    if employee is None:
        return {"visible": bool(duplicate.get("visible")), "employee_pk": None, "employee_name": ""}
    return {
        "visible": True,
        "employee_pk": employee.pk,
        "employee_name": f"{employee.family_name} {employee.given_name}",
    }


@hire_router.get("/new", auth=django_auth, response=HireFormOut)
def hire_form(request: HttpRequest, candidate: str = "", submission: str = "") -> dict[str, Any]:
    """The hire form's layout, fields and gating. `candidate` and `submission` are the recruitment candidate and the
    self-form HR hires from; the other query values prefill the forms (the recruitment «Ажилд авах» link). A bad or
    foreign id is ignored. 403 without the manage right."""
    user = _user(request)
    if not access.can_manage(user):
        raise ApiError(403, [_FORBIDDEN], code="forbidden")
    query = {**request.GET.dict(), "candidate": candidate, "submission": submission}
    try:
        page = hire_page.build(user, query, None, None)
    except PermissionDenied:
        raise ApiError(403, [_FORBIDDEN], code="forbidden") from None
    return {
        "title": TITLE,
        "tabs": _tabs(page),
        "fields": _described_fields(page),
        "candidate": page.candidate_id,
        "submission": page.submission_id,
        "review": _review(page.review) if page.review is not None else None,
        "duplicate": _duplicate(page.duplicate) if page.duplicate is not None else None,
    }


@hire_router.post("", auth=django_auth, response=HireResultOut)
def hire_create(
    request: HttpRequest,
    values: Form[str],
    candidate: Form[str] = "",
    submission: Form[str] = "",
    photo: File[UploadedFile | None] = None,
) -> dict[str, Any]:
    """Hire a new employee from the add form, the same hire as the Django page. `values` is a JSON object of HTML name
    -> string (every box, a checkbox as "on" or absent); `candidate` and `submission` are the hidden values the form
    posts back. A refused or invalid form answers 200 with ok false and nothing is written. 403 without the manage
    right, 400 for malformed values, 401 without a login."""
    user = _user(request)
    if not access.can_manage(user):
        raise ApiError(403, [_FORBIDDEN], code="forbidden")
    data: QueryDict = QueryDict(mutable=True)
    for name, value in _hire_values(values).items():
        data[name] = value
    if candidate:
        data["candidate"] = _utf8_text(candidate)
    if submission:
        data["submission"] = _utf8_text(submission)
    files = MultiValueDict({"photo": [photo]}) if photo is not None else MultiValueDict()
    try:
        page = hire_page.build(user, {}, data, files)
        outcome = hire_page.submit(user, page)
    except PermissionDenied:
        raise ApiError(403, [_FORBIDDEN], code="forbidden") from None
    ids = {"candidate": page.candidate_id, "submission": page.submission_id}
    if outcome.employee is None:  # invalid or refused: the messages go by HTML name, the ids stay in the form
        field_errors, form_errors, order_errors = _errors(_forms(page))
        return {
            "ok": False,
            "pk": None,
            "redirect": "",
            "field_errors": field_errors,
            "form_errors": form_errors,
            "order_errors": order_errors,
            **ids,
        }
    if outcome.login is not None:  # the password is shown once, on the employee page (the view's rule)
        request.session[ONE_TIME_LOGIN_KEY] = outcome.login
    _remember_warning(request, outcome.hire_order)
    pk = outcome.employee.pk
    # A limited user may hire outside their scope: that page would 404, so the list opens instead.
    if access.visible_employees(user).filter(pk=pk).exists():
        redirect = reverse("employees:detail", args=[pk])
    else:
        redirect = reverse("employees:list")
    return {
        "ok": True,
        "pk": pk,
        "redirect": redirect,
        "field_errors": {},
        "form_errors": [],
        "order_errors": [],
        **ids,
    }


class HireRegisterMatchOut(Schema):
    pk: int
    code: str  # the employee code («Ажилтны код»), "" when none
    full_name: str


class HireRegisterCheckOut(Schema):
    match: HireRegisterMatchOut | None  # the visible employee already under this register number, else null


class HireOrderSuggestOut(Schema):
    number: str  # the next order number of the year of `date`, "" when none can be guessed
    date: str  # YYYY-MM-DD: the date to use when the form's date is still empty


class HireNoteIn(Schema):
    note: str  # the send-back note; a blank text (after the strip) is refused


class HireReasonIn(Schema):
    reason: str  # the rejection reason; a blank text (after the strip) is refused


class HireDecisionOut(Schema):
    ok: bool
    form_errors: list[str]
    redirect: str  # on success: the Django self-forms list, where the flash message shows; "" on a refusal


def _manager(request: HttpRequest) -> User:
    user = _user(request)
    if not access.can_manage(user):
        raise ApiError(403, [_FORBIDDEN], code="forbidden")
    return user


@hire_router.get("/check-register", auth=django_auth, response=HireRegisterCheckOut)
def hire_register_check(request: HttpRequest, register_no: str = "") -> dict[str, Any]:
    """The employee already under this register number, if the user may see them (the live check on the hire page).
    The number is normalised the way the save normalises it; an empty one looks nobody up."""
    user = _manager(request)
    value = normalize_register_no(register_no)
    employee = access.visible_employees(user).filter(register_no=value).first() if value else None
    if employee is None:
        return {"match": None}
    return {
        "match": {"pk": employee.pk, "code": employee.code or "", "full_name": employee.full_name},
    }


@hire_router.get("/districts", auth=django_auth, response=list[EmployeeFormChoiceOut])
def hire_districts(request: HttpRequest, city: str = "") -> list[dict[str, Any]]:
    """The district options of the city, as the hire page's district select shows them. No or an unknown city has no
    district, so the list is empty."""
    _manager(request)
    form = HireAddressForm({"addr-city": city}, prefix="addr")
    choices: list[dict[str, Any]] = describe_field(form["district"])["choices"]
    return choices if any(choice["value"] for choice in choices) else []


@hire_router.get("/order-suggest", auth=django_auth, response=HireOrderSuggestOut)
def hire_order_suggest(request: HttpRequest, date: str = "") -> dict[str, str]:
    """`{number, date}` for the «Санал болгох» button: the next number of the year of `date` (else today) and the date
    to use when the form's date is still empty. A bad or empty date means today."""
    _manager(request)
    try:
        day = calendar_date.fromisoformat(date)
    except ValueError:
        day = calendar_date.today()
    return {"number": orders.suggest_number(day), "date": day.isoformat()}


def _invitation(user: User, pk: int) -> Any:
    """The invitation in the user's scope; one outside it is 404, as on the Django self-form pages."""
    try:
        return selfform_service.invitation_for(user, pk)
    except Http404:
        raise HttpError(404, _NOT_FOUND) from None


def _refused(message: str) -> dict[str, Any]:
    return {"ok": False, "form_errors": [message], "redirect": ""}


@selfform_router.post("/{pk}/send-back", auth=django_auth, response=HireDecisionOut)
def hire_send_back(request: HttpRequest, pk: int, payload: HireNoteIn) -> dict[str, Any]:
    """HR sends a submitted self-form back to the employee with a note. A blank note or a form that is not waiting for
    HR is refused with ok false and nothing is written. 403 without the manage right, 404 outside the user's scope."""
    user = _manager(request)
    invitation = _invitation(user, pk)
    if not payload.note.strip():
        return _refused(_NOTE_NEEDED)
    try:
        selfform_service.send_back(invitation, note=payload.note, by=user)
    except selfform_service.SelfFormError as error:
        return _refused(str(error))
    flash.success(request, "Анкетыг ажилтанд буцаалаа. Ажилтан засаад дахин илгээнэ.")
    return {"ok": True, "form_errors": [], "redirect": reverse("employees:selfforms")}


@selfform_router.post("/{pk}/reject", auth=django_auth, response=HireDecisionOut)
def hire_reject(request: HttpRequest, pk: int, payload: HireReasonIn) -> dict[str, Any]:
    """HR rejects a submitted self-form for good; the reason is kept on the invitation. A blank reason or a form that
    is not waiting for HR is refused with ok false. 403 without the manage right, 404 outside the user's scope."""
    user = _manager(request)
    invitation = _invitation(user, pk)
    if not payload.reason.strip():
        return _refused(_REASON_NEEDED)
    try:
        selfform_service.reject(invitation, reason=payload.reason, by=user)
    except selfform_service.SelfFormError as error:
        return _refused(str(error))
    flash.success(request, "Анкетыг татгалзлаа. Ажилтан дахин бөглөх боломжгүй болсон.")
    return {"ok": True, "form_errors": [], "redirect": reverse("employees:selfforms")}
